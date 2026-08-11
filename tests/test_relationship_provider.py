import pytest

from core.relationship.levels import NEUTRAL_LEVEL
from core.relationship.relationship_provider import RelationshipProvider
from core.relationship.store import RelationshipStore


@pytest.fixture
def store(memory_store):
    return RelationshipStore(memory_store.conn)


def _set(store, username, level, progress=0):
    store.get(username)
    store.conn.execute(
        "UPDATE relationship SET level = ?, progress = ?, updated_at = ? WHERE username = ?",
        (level, progress, "2026-01-01", username),
    )
    store.conn.commit()


def _render(store, username):
    return RelationshipProvider(store).render(username)


def test_unknown_user_renders_none(store):
    assert _render(store, "Незнакомец") is None


def test_neutral_level_renders_none(store):
    _set(store, "Вася", NEUTRAL_LEVEL)
    assert _render(store, "Вася") is None


def test_love_levels_instruction(store):
    for level in (0, 1, 2):
        _set(store, f"user{level}", level)
        text = _render(store, f"user{level}")
        assert text is not None
        assert "очень тепло" in text


def test_friendship_levels_instruction(store):
    for level in (3, 4):
        _set(store, f"user{level}", level)
        text = _render(store, f"user{level}")
        assert "дружелюбно" in text


def test_pleasantness_level_instruction(store):
    _set(store, "Вася", 5)
    assert "скорее позитивно" in _render(store, "Вася")


def test_dislike_level_instruction(store):
    _set(store, "Вася", 7)
    assert "прохладен" in _render(store, "Вася")


def test_hostility_levels_instruction(store):
    for level in (8, 9):
        _set(store, f"user{level}", level)
        assert "враждебно" in _render(store, f"user{level}")


def test_render_never_leaks_level_number(store):
    for level in range(10):
        _set(store, "Вася", level, progress=42)
        text = _render(store, "Вася")
        if text is not None:
            assert str(level) not in text
            assert "42" not in text
            assert "progress" not in text.lower()
