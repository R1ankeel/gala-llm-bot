import pytest

from core.relationship.levels import LEVEL_PROGRESS_CAP, NEUTRAL_LEVEL
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


def test_get_creates_neutral_row(store):
    state = store.get("Вася")
    assert state.username == "Вася"
    assert state.level == NEUTRAL_LEVEL
    assert state.progress == 0
    assert state.name == "Нейтральность"
    assert store.get("Вася").level == NEUTRAL_LEVEL


def test_apply_delta_positive_accumulates_progress(store):
    state = store.apply_delta("Вася", 1, "тепло")
    assert state.level == NEUTRAL_LEVEL
    assert state.progress == 10
    state = store.apply_delta("Вася", 2, "ещё теплее")
    assert state.level == NEUTRAL_LEVEL
    assert state.progress == 30


def test_apply_delta_triggers_level_up(store):
    store.apply_delta("Вася", 9, "почти")  # progress 90
    state = store.apply_delta("Вася", 1, "перешло")  # 100 -> уровень лучше
    assert state.level == 5
    assert state.progress == 0


def test_apply_delta_triggers_level_down(store):
    store.apply_delta("Вася", 1, "слегка тепло")  # progress 10
    state = store.apply_delta("Вася", -2, "грубость")  # 10 - 20 < 0
    assert state.level == 7
    assert state.progress == LEVEL_PROGRESS_CAP


def test_boundary_top_level_keeps_progress_capped(store):
    _set(store, "Вася", 0, LEVEL_PROGRESS_CAP)
    state = store.apply_delta("Вася", 3, "ещё теплее")
    assert state.level == 0
    assert state.progress == LEVEL_PROGRESS_CAP


def test_boundary_bottom_level_keeps_progress_at_zero(store):
    _set(store, "Вася", 9, 0)
    state = store.apply_delta("Вася", -3, "ещё хуже")
    assert state.level == 9
    assert state.progress == 0


def test_boundary_gradual_move_away_from_top(store):
    _set(store, "Вася", 0, LEVEL_PROGRESS_CAP)
    state = store.apply_delta("Вася", -1, "холодок")
    assert state.level == 0
    assert state.progress == LEVEL_PROGRESS_CAP - 10


def test_apply_delta_writes_log(store):
    store.apply_delta("Вася", -2, "токсичность")
    row = store.conn.execute(
        "SELECT username, delta, reason FROM relationship_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["username"] == "Вася"
    assert row["delta"] == -2
    assert row["reason"] == "токсичность"
