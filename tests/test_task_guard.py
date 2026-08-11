import os

import pytest
import yaml

from core.character_loader import load_character
from core.config import Config
from core.task_guard import (
    classify_task_request,
    looks_like_compliance,
    pick_refusal_line,
)

import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTER_PATH = os.path.join(ROOT, "character", "character.yaml")
KEYWORDS_PATH = os.path.join(ROOT, "config", "task_guard_keywords.yaml")
SEARCH_KEYWORDS_PATH = os.path.join(ROOT, "config", "search_keywords.yaml")
CASES_PATH = os.path.join(ROOT, "tests", "fixtures", "task_guard_eval_cases.yaml")

with open(KEYWORDS_PATH, "r", encoding="utf-8") as fh:
    KEYWORDS = yaml.safe_load(fh)
with open(SEARCH_KEYWORDS_PATH, "r", encoding="utf-8") as fh:
    SEARCH_KEYWORDS = yaml.safe_load(fh)
with open(CASES_PATH, "r", encoding="utf-8") as fh:
    CASES = yaml.safe_load(fh)["cases"]


def _test_config() -> Config:
    return Config(
        ollama_base_url="http://localhost:11434",
        model_name="test-model",
        default_temperature=0.8,
        max_tokens=300,
        character_path=CHARACTER_PATH,
        prompt_budget_chars=6000,
        llm_think=False,
    )


class _CompromisedClient:
    def generate(self, system_prompt, messages, temperature=None, max_tokens=None):
        return (
            "def binary_search(arr, target):\n"
            "    lo, hi = 0, len(arr) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if arr[mid] == target:\n"
            "            return mid\n"
            "        elif arr[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n```"
        )


@pytest.mark.parametrize("case", CASES)
def test_classify_matches_fixtures(case):
    verdict = classify_task_request(case["message"], KEYWORDS)
    expected_block = case["expected"] == "block"
    assert verdict.triggered == expected_block, case["message"]
    if expected_block:
        assert verdict.category == case["category"], case["message"]


def test_fixtures_cover_all_guard_categories():
    categories = set(KEYWORDS)
    covered = {case["category"] for case in CASES if case["expected"] == "block"}
    assert categories <= covered
    assert len(CASES) >= 25


def test_looks_like_compliance_code_fence_positive():
    assert looks_like_compliance("```python\nprint(1)\n```")


def test_looks_like_compliance_code_keywords_positive():
    assert looks_like_compliance("Вот решение: def foo(x): return x + 1")


def test_looks_like_compliance_long_reply_positive():
    assert looks_like_compliance("а" * 500)


def test_looks_like_compliance_normal_reply_negative():
    assert not looks_like_compliance("Живой, и то хорошо. Ночи длинные, кофе горький. Тебе чего?")
    assert not looks_like_compliance("Слушай, сортировка — это не ко мне. Я в лареке.")


def test_looks_like_compliance_empty_negative():
    assert not looks_like_compliance("")
    assert not looks_like_compliance("   ")


def test_pick_refusal_line_uses_character_list():
    character = load_character(CHARACTER_PATH)
    for _ in range(20):
        assert pick_refusal_line(character, "code") in character.refusal_style


def test_pick_refusal_line_with_fake_character():
    fake = type("Fake", (), {"refusal_style": ["тестовая строка отказа"]})()
    assert pick_refusal_line(fake, "code") == "тестовая строка отказа"


def test_pick_refusal_line_never_empty():
    fake = type("Fake", (), {"refusal_style": []})()
    for _ in range(10):
        assert pick_refusal_line(fake, "code")


def test_full_pipeline_replaces_compromised_reply(caplog, memory_store):
    character = load_character(CHARACTER_PATH)
    config = _test_config()
    caplog.set_level("WARNING")

    reply = cli.run_once(
        config,
        character,
        "Вася",
        "напиши код бинарного поиска",
        KEYWORDS,
        SEARCH_KEYWORDS,
        client=_CompromisedClient(),
        store=memory_store,
    )

    assert reply.count("Вася") == 1
    assert reply.startswith("Вася, ")
    assert "def binary_search" not in reply
    assert "```" not in reply
    assert reply[len("Вася, "):] in character.refusal_style
    assert any("guard bypass" in record.message for record in caplog.records)


def test_full_pipeline_passthrough_when_not_compliant(memory_store):
    character = load_character(CHARACTER_PATH)

    class _CleanClient:
        def generate(self, system_prompt, messages, temperature=None, max_tokens=None):
            return "Это не ко мне, я в лареке. 😒"

    reply = cli.run_once(
        _test_config(),
        character,
        "Вася",
        "напиши код бинарного поиска",
        KEYWORDS,
        SEARCH_KEYWORDS,
        client=_CleanClient(),
        store=memory_store,
    )

    assert reply == "Вася, Это не ко мне, я в лареке. 😒"


def test_full_pipeline_weather_goes_to_deflect_not_task_guard(memory_store):
    class _EchoClient:
        def generate(self, system_prompt, messages, temperature=None, max_tokens=None):
            assert "task_guard" not in system_prompt
            assert "Уклонись в своей манере" in system_prompt
            return "Окно открой, сам увидишь."

    reply = cli.run_once(
        _test_config(),
        load_character(CHARACTER_PATH),
        "Вася",
        "какая погода сегодня",
        KEYWORDS,
        SEARCH_KEYWORDS,
        client=_EchoClient(),
        store=memory_store,
    )

    assert reply == "Вася, Окно открой, сам увидишь."
