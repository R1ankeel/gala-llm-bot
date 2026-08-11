import logging
import os

import pytest

from core.character_loader import build_core_system_prompt, load_character
from core.dialogue_history import DialogueHistory
from core.layers import StubMemoryProvider, StubStateProvider
from core.prompt_builder import (
    RENDER_ORDER,
    PromptBuilder,
    build_guard_instruction,
    build_search_instruction,
)
from core.search_guard import build_deflect_instruction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTER_PATH = os.path.join(ROOT, "character", "character.yaml")


class LongStateProvider(StubStateProvider):
    def render(self, addressee_nick: str) -> str | None:
        return "S" * 10000


class LongMemoryProvider(StubMemoryProvider):
    def render(self, addressee_nick: str, current_message: str) -> str | None:
        return "M" * 10000


class FixedStateProvider(StubStateProvider):
    def render(self, addressee_nick: str) -> str | None:
        return "STATE_STRING_" + addressee_nick


class FixedMemoryProvider(StubMemoryProvider):
    def render(self, addressee_nick: str, current_message: str) -> str | None:
        return "MEMORY_STRING_" + current_message


def _make_history(*turns: tuple[str, str]) -> DialogueHistory:
    history = DialogueHistory(max_turns=100)
    for role, content in turns:
        history.add(role, content)
    return history


@pytest.fixture
def character():
    return load_character(CHARACTER_PATH)


def test_identity_always_present_even_when_layers_overflow(character, caplog):
    builder = PromptBuilder(character, LongStateProvider(), LongMemoryProvider(), budget_chars=500)
    caplog.set_level(logging.WARNING)
    history = _make_history(("user", "привет"))

    prompt = builder.build("Вася", "привет", history)

    identity = build_core_system_prompt(character)
    assert identity in prompt
    assert "S" * 10000 not in prompt
    assert "M" * 10000 not in prompt
    assert "привет" not in prompt.split("Тебе сейчас пишет")[0]


def test_budget_for_identity_plus_state_keeps_state_drops_rest(character):
    identity = build_core_system_prompt(character)
    state = FixedStateProvider().render("Вася")
    memory = FixedMemoryProvider().render("Вася", "погода")
    budget = len(identity) + len(state) + 5

    builder = PromptBuilder(character, FixedStateProvider(), FixedMemoryProvider(), budget_chars=budget)
    history = _make_history(("user", "погода"), ("assistant", "туман"))

    prompt = builder.build("Вася", "погода", history)

    assert identity in prompt
    assert state in prompt
    assert memory not in prompt
    rendered_history = history.render("Вася", "Гера")
    assert rendered_history not in prompt


def test_identity_kept_whole_and_warning_logged_when_budget_smaller(character, caplog):
    identity = build_core_system_prompt(character)
    budget = len(identity) - 1000

    builder = PromptBuilder(character, LongStateProvider(), LongMemoryProvider(), budget_chars=budget)
    caplog.set_level(logging.WARNING)

    prompt = builder.build("Вася", "привет")

    assert identity in prompt
    assert len(prompt) > len(identity)
    assert any("identity" in record.message for record in caplog.records)


def test_render_order_is_fixed(character):
    builder = PromptBuilder(character, FixedStateProvider(), FixedMemoryProvider(), budget_chars=100000)
    history = _make_history(("user", "а"), ("assistant", "б"))

    prompt = builder.build("Вася", "в", history)

    identity = build_core_system_prompt(character)
    state = FixedStateProvider().render("Вася")
    memory = FixedMemoryProvider().render("Вася", "в")
    rendered_history = history.render("Вася", "Гера")

    positions = [prompt.index(section) for section in (identity, state, memory, rendered_history)]
    assert positions == sorted(positions)
    assert RENDER_ORDER == (
        "identity",
        "task_guard",
        "deflect",
        "search_context",
        "state",
        "memory",
        "history",
    )


def test_build_with_default_stubs_and_no_history(character):
    builder = PromptBuilder(character, StubStateProvider(), StubMemoryProvider())
    prompt = builder.build("Вася", "привет")

    identity = build_core_system_prompt(character)
    assert identity in prompt
    assert "STATE_STRING" not in prompt
    assert "MEMORY_STRING" not in prompt


def test_history_renders_nick_and_character_name():
    history = DialogueHistory()
    history.add("user", "привет")
    history.add("assistant", "живой")

    rendered = history.render("Вася", "Гера")

    assert rendered == "Вася: привет\nГера: живой"


def test_history_truncates_by_max_turns():
    history = DialogueHistory(max_turns=3)
    for i in range(5):
        history.add("user", f"msg{i}")

    assert len(history.turns) == 3
    assert history.turns[0].content == "msg2"
    assert history.turns[-1].content == "msg4"


def test_swapping_memory_provider_does_not_break_build(character, caplog):
    class HugeMemoryProvider(StubMemoryProvider):
        def render(self, addressee_nick: str, current_message: str) -> str | None:
            return "X" * 10000

    builder = PromptBuilder(character, StubStateProvider(), HugeMemoryProvider(), budget_chars=500)
    caplog.set_level(logging.WARNING)

    prompt = builder.build("Вася", "привет")

    identity = build_core_system_prompt(character)
    assert identity in prompt
    assert "X" * 10000 not in prompt
    assert any("identity" in record.message for record in caplog.records)


def test_guard_instruction_contains_refusal_examples(character):
    instruction = build_guard_instruction(character, "code")

    assert "категория: code" in instruction
    for line in character.refusal_style:
        assert line in instruction


def test_guard_layer_rendered_after_identity(character):
    builder = PromptBuilder(character, FixedStateProvider(), FixedMemoryProvider(), budget_chars=100000)

    prompt = builder.build("Вася", "в", guard_category="code")

    identity = build_core_system_prompt(character)
    guard = build_guard_instruction(character, "code")
    state = FixedStateProvider().render("Вася")
    assert prompt.index(identity) < prompt.index(guard) < prompt.index(state)


def test_guard_layer_not_dropped_when_budget_tight(character, caplog):
    identity = build_core_system_prompt(character)
    guard = build_guard_instruction(character, "code")
    budget = len(identity) + len(guard) + 10

    builder = PromptBuilder(character, LongStateProvider(), LongMemoryProvider(), budget_chars=budget)

    prompt = builder.build("Вася", "в", guard_category="code")

    assert identity in prompt
    assert guard in prompt
    assert "S" * 10000 not in prompt
    assert "M" * 10000 not in prompt
    assert not any("identity" in record.message for record in caplog.records)


def test_deflect_layer_position_after_guard_before_state(character):
    builder = PromptBuilder(character, FixedStateProvider(), FixedMemoryProvider(), budget_chars=100000)

    prompt = builder.build("Вася", "в", guard_category="code", deflect_category="blocked_weather")

    identity = build_core_system_prompt(character)
    guard = build_guard_instruction(character, "code")
    deflect = build_deflect_instruction(character, "blocked_weather")
    state = FixedStateProvider().render("Вася")
    assert prompt.index(identity) < prompt.index(guard) < prompt.index(deflect) < prompt.index(state)


def test_search_context_position_after_deflect_before_state(character):
    builder = PromptBuilder(character, FixedStateProvider(), FixedMemoryProvider(), budget_chars=100000)

    prompt = builder.build("Вася", "в", deflect_category="blocked_science", search_context="КОНТЕКСТ")

    deflect = build_deflect_instruction(character, "blocked_science")
    search = build_search_instruction("КОНТЕКСТ")
    state = FixedStateProvider().render("Вася")
    assert prompt.index(deflect) < prompt.index(search) < prompt.index(state)


def test_deflect_layer_not_dropped_when_budget_tight(character):
    identity = build_core_system_prompt(character)
    deflect = build_deflect_instruction(character, "blocked_weather")
    budget = len(identity) + len(deflect) + 10

    builder = PromptBuilder(character, LongStateProvider(), LongMemoryProvider(), budget_chars=budget)
    prompt = builder.build("Вася", "в", deflect_category="blocked_weather")

    assert identity in prompt
    assert deflect in prompt
    assert "S" * 10000 not in prompt
    assert "M" * 10000 not in prompt


def test_search_context_dropped_when_budget_very_tight(character, caplog):
    identity = build_core_system_prompt(character)
    budget = len(identity) + 5

    builder = PromptBuilder(character, StubStateProvider(), StubMemoryProvider(), budget_chars=budget)
    caplog.set_level(logging.WARNING)
    prompt = builder.build("Вася", "в", search_context="КОНТЕКСТ")

    assert identity in prompt
    assert "КОНТЕКСТ" not in prompt
    assert any("search_context" in record.message for record in caplog.records)


def test_search_context_survives_before_state_drops(character):
    identity = build_core_system_prompt(character)
    search = build_search_instruction("КОНТЕКСТ")
    budget = len(identity) + len(search) + 10

    builder = PromptBuilder(character, LongStateProvider(), LongMemoryProvider(), budget_chars=budget)
    prompt = builder.build("Вася", "в", search_context="КОНТЕКСТ")

    assert identity in prompt
    assert search in prompt
    assert "S" * 10000 not in prompt
    assert "M" * 10000 not in prompt
