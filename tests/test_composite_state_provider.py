import os

import pytest

from core.character_loader import load_character
from core.layers import StubMemoryProvider
from core.prompt_builder import PromptBuilder
from core.relationship.relationship_provider import RelationshipProvider
from core.relationship.store import RelationshipStore
from core.schedule_provider import ScheduleProvider
from core.state.composite_state_provider import CompositeStateProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_PATH = os.path.join(ROOT, "config", "schedule.yaml")
CHARACTER_PATH = os.path.join(ROOT, "character", "character.yaml")


def _set(store, username, level):
    store.get(username)
    store.conn.execute(
        "UPDATE relationship SET level = ?, progress = 0, updated_at = ? WHERE username = ?",
        (level, "2026-01-01", username),
    )
    store.conn.commit()


def _schedule():
    return ScheduleProvider(SCHEDULE_PATH)


def test_schedule_provider_alone_is_unit_testable(memory_store):
    text = _schedule().render("Любой")
    assert text.startswith("Сейчас ты:")


def test_relationship_provider_alone_is_unit_testable(memory_store):
    store = RelationshipStore(memory_store.conn)
    _set(store, "Вася", 8)
    text = RelationshipProvider(store).render("Вася")
    assert "враждебно" in text


def test_neutral_relationship_contributes_nothing(memory_store):
    store = RelationshipStore(memory_store.conn)
    assert RelationshipProvider(store).render("Вася") is None


def test_composite_combines_schedule_and_relationship(memory_store):
    rel_store = RelationshipStore(memory_store.conn)
    _set(rel_store, "Вася", 8)
    composite = CompositeStateProvider([_schedule(), RelationshipProvider(rel_store)])
    text = composite.render("Вася")
    assert text.startswith("Сейчас ты:")
    assert "враждебно" in text


def test_composite_with_neutral_relationship_is_only_schedule(memory_store):
    rel_store = RelationshipStore(memory_store.conn)
    composite = CompositeStateProvider([_schedule(), RelationshipProvider(rel_store)])
    text = composite.render("Вася")
    assert text.startswith("Сейчас ты:")
    assert "враждебно" not in text
    assert text.rstrip().endswith(".")


def test_composite_all_none_returns_none():
    class _NoneProvider:
        def render(self, addressee_nick):
            return None

    composite = CompositeStateProvider([_NoneProvider(), _NoneProvider()])
    assert composite.render("кто-то") is None


def test_composite_joins_parts_with_single_space():
    class _P:
        def __init__(self, text):
            self.text = text

        def render(self, addressee_nick):
            return self.text

    composite = CompositeStateProvider([_P("часть один"), _P("часть два")])
    assert composite.render("кто-то") == "часть один часть два"


def test_prompt_builder_renders_relationship_only_when_not_neutral(memory_store):
    character = load_character(CHARACTER_PATH)
    rel_store = RelationshipStore(memory_store.conn)
    composite = CompositeStateProvider([_schedule(), RelationshipProvider(rel_store)])
    builder = PromptBuilder(character, composite, StubMemoryProvider(), budget_chars=6000)

    neutral_prompt = builder.build("Вася", "привет")
    assert "враждебно" not in neutral_prompt

    _set(rel_store, "Вася", 8)
    hostile_prompt = builder.build("Вася", "привет")
    assert "враждебно" in hostile_prompt
    assert len(hostile_prompt) > len(neutral_prompt)
