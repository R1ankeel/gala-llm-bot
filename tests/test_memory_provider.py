import os

import yaml

from core.character_loader import load_character
from core.config import Config
from core.memory.memory_provider import FactsMemoryProvider
from core.prompt_builder import PromptBuilder
from core.schedule_provider import ScheduleProvider

import cli
from tests.mocks.fake_llm_client import FakeLLMClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTER_PATH = os.path.join(ROOT, "character", "character.yaml")
HEURISTICS_PATH = os.path.join(ROOT, "config", "gender_heuristics.yaml")
SCHEDULE_PATH = os.path.join(ROOT, "config", "schedule.yaml")
TASK_KEYWORDS_PATH = os.path.join(ROOT, "config", "task_guard_keywords.yaml")
SEARCH_KEYWORDS_PATH = os.path.join(ROOT, "config", "search_keywords.yaml")

with open(HEURISTICS_PATH, "r", encoding="utf-8") as fh:
    HEURISTICS = yaml.safe_load(fh)
with open(TASK_KEYWORDS_PATH, "r", encoding="utf-8") as fh:
    TASK_KEYWORDS = yaml.safe_load(fh)
with open(SEARCH_KEYWORDS_PATH, "r", encoding="utf-8") as fh:
    SEARCH_KEYWORDS = yaml.safe_load(fh)


def _config() -> Config:
    return Config(
        ollama_base_url="http://localhost:11434",
        model_name="test-model",
        default_temperature=0.8,
        max_tokens=300,
        character_path=CHARACTER_PATH,
        db_path=str(ROOT) + "/data/memory.db",
        prompt_budget_chars=6000,
        llm_think=False,
    )


def _provider(memory_store, max_facts=3):
    return FactsMemoryProvider(memory_store, HEURISTICS, max_facts=max_facts)


def test_render_none_when_nothing_known(memory_store):
    assert _provider(memory_store).render("user4821", "привет") is None


def test_render_partial_profile_has_no_none_text(memory_store):
    memory_store.upsert_profile_field("Вася", "real_name", "Василий")
    text = _provider(memory_store).render("Вася", "привет")
    assert text is not None
    assert "None" not in text
    assert "Василий" in text
    assert "Пол: мужской." in text


def test_render_with_age_job_city(memory_store):
    memory_store.upsert_profile_field("Оля", "age", "25")
    memory_store.upsert_profile_field("Оля", "job", "учитель")
    memory_store.upsert_profile_field("Оля", "city", "Воронежа")
    text = _provider(memory_store).render("Оля", "привет")
    assert "25 лет" in text
    assert "учитель" in text
    assert "из Воронежа" in text
    assert "Пол: женский." in text


def test_render_includes_recent_facts_limited(memory_store):
    memory_store.add_fact("Аня", "любит рисовать", "hobby", "observed")
    memory_store.add_fact("Аня", "боится пауков", "fact", "observed")
    text = _provider(memory_store, max_facts=1).render("Аня", "привет")
    assert "боится пауков" in text
    assert "любит рисовать" not in text


def test_render_explicit_gender_overrides_nickname(memory_store):
    memory_store.upsert_profile_field("Вася", "gender", "female")
    memory_store.upsert_profile_field("Вася", "gender_source", "self_declared")
    text = _provider(memory_store).render("Вася", "привет")
    assert "Пол: женский." in text


def test_prompt_builder_renders_memory_layer(memory_store):
    character = load_character(CHARACTER_PATH)
    memory_store.upsert_profile_field("Вася", "real_name", "Василий")
    builder = PromptBuilder(
        character,
        ScheduleProvider(SCHEDULE_PATH),
        _provider(memory_store),
        budget_chars=6000,
    )
    prompt = builder.build("Вася", "как дела")
    assert "Ты знаешь об этом собеседнике" in prompt
    assert "Василий" in prompt


def test_run_once_persists_realtime_profile_and_renders_memory(memory_store):
    character = load_character(CHARACTER_PATH)
    client = FakeLLMClient(default="Привет, Вася!")

    reply = cli.run_once(
        _config(),
        character,
        "Вася",
        "меня зовут Вася, мне 22, работаю таксистом",
        TASK_KEYWORDS,
        SEARCH_KEYWORDS,
        client=client,
        store=memory_store,
    )

    assert reply == "Вася, Привет, Вася!"
    profile = memory_store.get_profile("Вася")
    assert profile.real_name == "Вася"
    assert profile.age == 22
    assert profile.job == "таксист"

    prompt = client.calls[0]["system_prompt"]
    assert "Ты знаешь об этом собеседнике" in prompt
    assert "22 лет" in prompt
    assert "Пол: мужской." in prompt
