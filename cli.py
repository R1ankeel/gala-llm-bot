import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

from core.character_loader import load_character
from core.config import Config, ConfigError, load_config
from core.dialogue_history import DialogueHistory
from core.llm_client import LLMClient, LLMError
from core.memory.facts_extractor import FactsExtractor
from core.memory.memory_provider import FactsMemoryProvider
from core.memory.realtime_profile import apply_realtime_updates
from core.memory.store import MemoryStore
from core.prompt_builder import PromptBuilder
from core.response_formatter import format_reply
from core.schedule_provider import ScheduleProvider, ScheduleConfigError
from core.search_classifier import SearchVerdict, classify_query
from core.search_client import SearchClient
from core.search_formatter import format_search_context
from core.search_guard import (
    looks_like_hallucinated_fact,
    pick_deflect_line,
)
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


@dataclass
class MemoryRuntime:
    store: MemoryStore
    extractor: FactsExtractor
    memory_provider: FactsMemoryProvider
    memory_config: dict


def _make_client(config: Config) -> LLMClient:
    return LLMClient(config.ollama_base_url, config.model_name, think=config.llm_think)


def _make_store(config: Config) -> MemoryStore:
    return MemoryStore(config.db_path)


def make_memory_runtime(
    config: Config,
    character,
    llm_client: LLMClient,
    store: MemoryStore | None = None,
) -> MemoryRuntime:
    store = store or _make_store(config)
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


def _make_builder(config: Config, character, memory_provider) -> PromptBuilder:
    return PromptBuilder(
        character,
        ScheduleProvider(DEFAULT_SCHEDULE_PATH),
        memory_provider,
        budget_chars=config.prompt_budget_chars,
    )


def _generate(client: LLMClient, config: Config, system_prompt: str, message: str) -> str:
    return client.generate(
        system_prompt,
        [{"role": "user", "content": message}],
        temperature=config.default_temperature,
        max_tokens=config.max_tokens,
    )


def _run_memory_pipeline(memory: MemoryRuntime, to: str, msg: str) -> None:
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


def _build_system_prompt(
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


def _apply_guard_fallback(character, raw: str, task_verdict, search_verdict: SearchVerdict) -> str:
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


def _respond(
    config: Config,
    character,
    to: str,
    msg: str,
    task_keywords: dict,
    search_keywords: dict,
    client: LLMClient | None = None,
    search_client: SearchClient | None = None,
    store: MemoryStore | None = None,
    memory: MemoryRuntime | None = None,
) -> str:
    client = client or _make_client(config)
    memory = memory or make_memory_runtime(config, character, client, store=store)
    _run_memory_pipeline(memory, to, msg)

    task_verdict = classify_task_request(msg, task_keywords)
    search_verdict = SearchVerdict(action="none", category=None)

    if not task_verdict.triggered:
        search_verdict = classify_query(msg, search_keywords)

    builder = _make_builder(config, character, memory.memory_provider)
    system_prompt = _build_system_prompt(
        builder, to, msg, task_verdict, search_verdict, search_client
    )

    raw = _generate(client, config, system_prompt, msg)
    raw = _apply_guard_fallback(character, raw, task_verdict, search_verdict)
    return format_reply(raw, to)


def run_once(
    config: Config,
    character,
    to: str,
    msg: str,
    task_keywords: dict,
    search_keywords: dict,
    client: LLMClient | None = None,
    search_client: SearchClient | None = None,
    store: MemoryStore | None = None,
    memory: MemoryRuntime | None = None,
) -> str:
    return _respond(
        config,
        character,
        to,
        msg,
        task_keywords,
        search_keywords,
        client=client,
        search_client=search_client,
        store=store,
        memory=memory,
    )


def run_repl(
    config: Config,
    character,
    nick: str,
    task_keywords: dict,
    search_keywords: dict,
    client: LLMClient | None = None,
    store: MemoryStore | None = None,
) -> int:
    client = client or _make_client(config)
    memory = make_memory_runtime(config, character, client, store=store)
    builder = _make_builder(config, character, memory.memory_provider)
    history = DialogueHistory()

    print(f"REPL-режим. Крутимся против {nick}. Пустая строка или Ctrl+C/Ctrl+D — выход.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            break

        history.add("user", line)
        _run_memory_pipeline(memory, nick, line)
        task_verdict = classify_task_request(line, task_keywords)
        search_verdict = SearchVerdict(action="none", category=None)
        if not task_verdict.triggered:
            search_verdict = classify_query(line, search_keywords)

        system_prompt = _build_system_prompt(
            builder, nick, line, task_verdict, search_verdict, None
        )
        try:
            raw = _generate(client, config, system_prompt, line)
        except LLMError as err:
            print(f"[llm] {err}", file=sys.stderr)
            history.turns.pop()
            continue

        raw = _apply_guard_fallback(character, raw, task_verdict, search_verdict)
        reply = format_reply(raw, nick)
        print(reply)
        history.add("assistant", reply[len(f"{nick}, "):])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ностальгирующий клоун-продавец из круглосуточного ларька: "
        "онлайн-режим одиночного сообщения или REPL-диалог."
    )
    parser.add_argument("--to", help="ник собеседника (для одиночного режима)")
    parser.add_argument("--msg", help="текст сообщения (для одиночного режима)")
    parser.add_argument("--repl", action="store_true", help="REPL-режим для тестирования")
    parser.add_argument("--nick", help="ник собеседника (REPL-режим)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        config = load_config()
        character = load_character(config.character_path)
        task_keywords = load_guard_keywords()
        search_keywords = load_search_keywords()
        ScheduleProvider(DEFAULT_SCHEDULE_PATH)
        _make_store(config)
    except (ConfigError, OSError, ScheduleConfigError) as err:
        print(f"[config] {err}", file=sys.stderr)
        return 1

    if args.repl:
        if not args.nick:
            print("[usage] --repl требует --nick", file=sys.stderr)
            return 2
        return run_repl(config, character, args.nick, task_keywords, search_keywords)

    if not args.to or not args.msg:
        print(
            "[usage] передай --to и --msg (для одиночного режима), "
            "или --repl --nick <ник>",
            file=sys.stderr,
        )
        return 2

    try:
        reply = run_once(
            config, character, args.to, args.msg, task_keywords, search_keywords
        )
    except LLMError as err:
        print(f"[llm] {err}", file=sys.stderr)
        return 1
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
