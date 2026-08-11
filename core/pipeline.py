"""Единая точка пайплайна ответа: всё, что нужно, чтобы превратить
адресованное сообщение в готовую реплику бота.

Два потребителя:
  - cli.py  — ручная отладка (--to/--msg/--repl) с фейковым источником;
  - main.py — прод-путь: реальный чат (chat_io), дебаунс, отправка.

Оба вызывают handle_addressed_message(). Логика этапов 3-7 (task_guard,
search, relationships, prompt, generate, post-validation, format) живёт
здесь ОДИН раз.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

from core.character_loader import Character
from core.config import Config
from core.llm_client import LLMClient
from core.memory.facts_extractor import FactsExtractor
from core.memory.memory_provider import FactsMemoryProvider
from core.memory.realtime_profile import apply_realtime_updates
from core.memory.store import MemoryStore
from core.prompt_builder import PromptBuilder
from core.relationship.evaluator import RelationshipEvaluator
from core.relationship.relationship_provider import RelationshipProvider
from core.relationship.store import RelationshipStore
from core.response_formatter import format_reply
from core.schedule_provider import ScheduleProvider
from core.search_classifier import SearchVerdict, classify_query
from core.search_client import SearchClient
from core.search_formatter import format_search_context
from core.search_guard import looks_like_hallucinated_fact, pick_deflect_line
from core.state.composite_state_provider import CompositeStateProvider
from core.task_guard import (
    classify_task_request,
    looks_like_compliance,
    pick_refusal_line,
)

logger = logging.getLogger(__name__)

DEFAULT_TASK_GUARD_KEYWORDS_PATH = "config/task_guard_keywords.yaml"
DEFAULT_SEARCH_KEYWORDS_PATH = "config/search_keywords.yaml"
DEFAULT_SCHEDULE_PATH = "config/schedule.yaml"
DEFAULT_MEMORY_CONFIG_PATH = "config/memory.yaml"
DEFAULT_GENDER_HEURISTICS_PATH = "config/gender_heuristics.yaml"
DEFAULT_RELATIONSHIP_CONFIG_PATH = "config/relationship.yaml"
DEFAULT_DB_PATH = "data/memory.db"


def load_guard_keywords(path: str = DEFAULT_TASK_GUARD_KEYWORDS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_search_keywords(path: str = DEFAULT_SEARCH_KEYWORDS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_memory_config(path: str = DEFAULT_MEMORY_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_gender_heuristics(path: str = DEFAULT_GENDER_HEURISTICS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_relationship_config(path: str = DEFAULT_RELATIONSHIP_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class MemoryRuntime:
    store: MemoryStore
    extractor: FactsExtractor
    memory_provider: FactsMemoryProvider
    memory_config: dict


@dataclass
class RelationshipRuntime:
    store: RelationshipStore
    evaluator: RelationshipEvaluator
    provider: RelationshipProvider
    config: dict


@dataclass
class Runtime:
    memory: MemoryRuntime
    relationship: RelationshipRuntime
    state_provider: CompositeStateProvider


def make_client(config: Config) -> LLMClient:
    return LLMClient(config.ollama_base_url, config.model_name, think=config.llm_think)


def make_store(config: Config) -> MemoryStore:
    return MemoryStore(config.db_path)


def make_memory_runtime(
    config: Config,
    character: Character,
    llm_client: LLMClient,
    store: MemoryStore | None = None,
) -> MemoryRuntime:
    store = store or make_store(config)
    memory_config = load_memory_config()
    gender_heuristics = load_gender_heuristics()
    extractor = FactsExtractor(
        store,
        llm_client,
        character_name=character.name,
        memory_config=memory_config,
    )
    max_facts = int(memory_config.get("max_facts_rendered", 3))
    provider = FactsMemoryProvider(store, gender_heuristics, max_facts=max_facts)
    return MemoryRuntime(
        store=store,
        extractor=extractor,
        memory_provider=provider,
        memory_config=memory_config,
    )


def make_runtime(
    config: Config,
    character: Character,
    llm_client: LLMClient,
    store: MemoryStore | None = None,
    memory: MemoryRuntime | None = None,
) -> Runtime:
    memory = memory or make_memory_runtime(config, character, llm_client, store=store)
    relationship_config = load_relationship_config()
    relationship_store = RelationshipStore(memory.store.conn)
    evaluator = RelationshipEvaluator(
        relationship_store,
        memory.store,
        llm_client,
        config=relationship_config,
        character_name=character.name,
    )
    relationship_provider = RelationshipProvider(relationship_store)
    relationship = RelationshipRuntime(
        store=relationship_store,
        evaluator=evaluator,
        provider=relationship_provider,
        config=relationship_config,
    )
    state_provider = CompositeStateProvider(
        [ScheduleProvider(DEFAULT_SCHEDULE_PATH), relationship_provider]
    )
    return Runtime(
        memory=memory,
        relationship=relationship,
        state_provider=state_provider,
    )


def make_builder(config: Config, character: Character, memory_provider, state_provider) -> PromptBuilder:
    return PromptBuilder(
        character,
        state_provider,
        memory_provider,
        budget_chars=config.prompt_budget_chars,
    )


def generate(client: LLMClient, config: Config, system_prompt: str, message: str) -> str:
    return client.generate(
        system_prompt,
        [{"role": "user", "content": message}],
        temperature=config.default_temperature,
        max_tokens=config.max_tokens,
    )


def run_memory_pipeline(memory: MemoryRuntime, to: str, msg: str) -> None:
    """Логирует сообщение и обновляет память; падение не роняет диалог."""
    try:
        now = datetime.now(timezone.utc)
        memory.store.log_message(to, msg, now)
        apply_realtime_updates(memory.store, to, msg)
        threshold = int(memory.memory_config.get("extract_every_n_messages", 30))
        if memory.store.count_unprocessed() >= threshold:
            memory.extractor.run_extraction_cycle()
    except Exception as err:  # noqa: BLE001 — память не должна ронять диалог
        logger.warning("memory pipeline failed, continuing without it: %s", err)


def run_relationship_evaluation(runtime: Runtime, to: str) -> None:
    """Считает сообщение и (по накоплению) оценивает отношение; сбой не
    роняет диалог. Вызывается ДО генерации, чтобы state-слой в этом же
    ответе уже видел свежий уровень."""
    try:
        runtime.relationship.evaluator.count_message(to)
        runtime.relationship.evaluator.maybe_evaluate(to)
    except Exception as err:  # noqa: BLE001
        logger.warning("relationship evaluation failed, continuing without it: %s", err)


def build_system_prompt(
    builder: PromptBuilder,
    to: str,
    msg: str,
    task_verdict,
    search_verdict: SearchVerdict,
    search_client: SearchClient | None,
) -> str:
    if task_verdict.triggered:
        return builder.build(to, msg, guard_category=task_verdict.category)

    if search_verdict.action == "search":
        search_client = search_client or SearchClient()
        results = search_client.search(msg)
        ctx = format_search_context(results)
        return builder.build(to, msg, search_context=ctx)

    if search_verdict.action == "deflect":
        return builder.build(to, msg, deflect_category=search_verdict.category)

    return builder.build(to, msg)


def apply_guard_fallback(character: Character, raw: str, task_verdict, search_verdict: SearchVerdict) -> str:
    if task_verdict.triggered and looks_like_compliance(raw):
        logger.warning("guard bypass on category=%s", task_verdict.category)
        return pick_refusal_line(character, task_verdict.category)
    if (
        search_verdict.action == "deflect"
        and search_verdict.category
        and looks_like_hallucinated_fact(raw, search_verdict.category)
    ):
        logger.warning("search guard deflect bypass on category=%s", search_verdict.category)
        return pick_deflect_line(character, search_verdict.category)
    return raw


def handle_addressed_message(
    config: Config,
    character: Character,
    to: str,
    msg: str,
    task_keywords: dict,
    search_keywords: dict,
    client: LLMClient | None = None,
    search_client: SearchClient | None = None,
    store: MemoryStore | None = None,
    memory: MemoryRuntime | None = None,
    runtime: Runtime | None = None,
    log_to_memory: bool = True,
) -> str:
    """Полный пайплайн ответа на адресованное сообщение.

    log_to_memory=False — для main.py: сообщение уже залогировано и
    realtime-профиль уже обновлён в цикле опроса, не надо дважды.
    cli.py всегда передаёт по умолчанию True (лог + realtime внутри).
    """
    client = client or make_client(config)
    runtime = runtime or make_runtime(config, character, client, store=store, memory=memory)
    if log_to_memory:
        run_memory_pipeline(runtime.memory, to, msg)
    run_relationship_evaluation(runtime, to)

    task_verdict = classify_task_request(msg, task_keywords)
    search_verdict = SearchVerdict(action="none", category=None)

    if not task_verdict.triggered:
        search_verdict = classify_query(msg, search_keywords)

    builder = make_builder(
        config, character, runtime.memory.memory_provider, runtime.state_provider
    )
    system_prompt = build_system_prompt(
        builder, to, msg, task_verdict, search_verdict, search_client
    )

    raw = generate(client, config, system_prompt, msg)
    raw = apply_guard_fallback(character, raw, task_verdict, search_verdict)
    return format_reply(raw, to)
