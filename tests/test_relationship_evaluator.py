from datetime import datetime, timezone

import pytest

from core.llm_client import LLMError
from core.relationship.evaluator import RelationshipEvaluator
from core.relationship.store import RelationshipStore
from tests.mocks.fake_llm_client import FakeLLMClient

EVAL_CONFIG = {
    "eval_every_n_messages": 3,
    "delta_min": -3,
    "delta_max": 3,
}


@pytest.fixture
def store(memory_store):
    return RelationshipStore(memory_store.conn)


def _log(memory_store, username, text):
    memory_store.log_message(username, text, datetime.now(timezone.utc))


def _eval(store, memory_store, llm, character_name=None, config=None):
    return RelationshipEvaluator(
        store,
        memory_store,
        llm,
        config=config or EVAL_CONFIG,
        character_name=character_name,
    )


def _reach_threshold(ev, n):
    for _ in range(n):
        ev.count_message("Вася")


def test_below_threshold_does_not_contact_llm(store, memory_store):
    _log(memory_store, "Вася", "привет")
    llm = FakeLLMClient({"Вася": '{"delta": 1, "reason": "тепло"}'})
    ev = _eval(store, memory_store, llm)
    assert ev.maybe_evaluate("Вася", message_count_since_last=2) is None
    assert llm.calls == []
    assert store.get("Вася").level == 6
    assert store.get("Вася").progress == 0


def test_at_threshold_applies_delta_and_resets_counter(store, memory_store):
    _log(memory_store, "Вася", "спасибо тебе, ты лучший")
    _log(memory_store, "Вася", "очень ценю твою помощь")
    _log(memory_store, "Вася", "ты клёвый")
    llm = FakeLLMClient({"Вася": '{"delta": 3, "reason": "тёплые слова"}'})
    ev = _eval(store, memory_store, llm)
    _reach_threshold(ev, 3)

    state = ev.maybe_evaluate("Вася")
    assert state is not None
    assert state.level == 6
    assert state.progress == 30

    assert ev.maybe_evaluate("Вася") is None  # счётчик сброшен


def test_invalid_json_falls_back_to_zero(store, memory_store):
    for _ in range(3):
        _log(memory_store, "Вася", "привет")
    llm = FakeLLMClient({"Вася": "не json вообще"})
    ev = _eval(store, memory_store, llm)
    _reach_threshold(ev, 3)

    state = ev.maybe_evaluate("Вася")
    assert state is not None
    assert state.level == 6
    assert state.progress == 0

    row = store.conn.execute(
        "SELECT reason FROM relationship_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["reason"] == "parse_error"


def test_llm_error_falls_back_without_crash(store, memory_store):
    for _ in range(3):
        _log(memory_store, "Вася", "привет")
    llm = FakeLLMClient(error=LLMError("модель недоступна"))
    ev = _eval(store, memory_store, llm)
    _reach_threshold(ev, 3)

    state = ev.maybe_evaluate("Вася")
    assert state is not None
    assert state.level == 6
    assert state.progress == 0


def test_delta_clamped_to_config_range(store, memory_store):
    for _ in range(3):
        _log(memory_store, "Вася", "привет")
    llm = FakeLLMClient({"Вася": '{"delta": 99, "reason": "слишком много"}'})
    ev = _eval(store, memory_store, llm)
    _reach_threshold(ev, 3)

    state = ev.maybe_evaluate("Вася")
    assert state.progress == 30  # delta 99 -> 3 -> *10


def test_only_bot_addressed_messages_fed_to_llm(store, memory_store):
    _log(memory_store, "Вася", "всем привет")  # не боту
    _log(memory_store, "Вася", "Гера, ты самый лучший")  # боту
    _log(memory_store, "Вася", "Гера, спасибо большое")  # боту
    llm = FakeLLMClient({"Вася": '{"delta": 2, "reason": "благодарность"}'})
    ev = _eval(store, memory_store, llm, character_name="Гера")
    _reach_threshold(ev, 3)

    ev.maybe_evaluate("Вася")
    user_content = llm.calls[0]["messages"][0]["content"]
    assert "всем привет" not in user_content
    assert "ты самый лучший" in user_content
    assert "спасибо большое" in user_content


def test_empty_history_does_not_contact_llm(store, memory_store):
    llm = FakeLLMClient(default='{"delta": 1, "reason": "хм"}')
    ev = _eval(store, memory_store, llm)
    _reach_threshold(ev, 3)
    assert ev.maybe_evaluate("Вася") is None
    assert llm.calls == []
