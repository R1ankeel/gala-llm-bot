from datetime import datetime, timedelta

from core.debounce_buffer import DebounceBuffer

T0 = datetime(2026, 1, 1, 12, 0, 0)


def _t(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _fill(buffer, username, texts, start, interval):
    """Подаёт texts в буфер: первый в start, дальше каждые interval секунд."""
    now = start
    for text in texts:
        buffer.add(username, text, now)
        now += timedelta(seconds=interval)
    return now


def test_short_burst_joins_into_one_reply():
    buffer = DebounceBuffer(debounce_seconds=3.5, max_wait_seconds=15)
    last = _fill(buffer, "Вася", ["Приве", "как", "твои", "дела"], _t(0), 0.5)

    assert buffer.pop_ready(_t(0.5)) == []  # тишина ещё не наступила

    ready = buffer.pop_ready(last + timedelta(seconds=4))
    assert ready == [("Вася", "Приве как твои дела")]
    assert not buffer.has_pending("Вася")


def test_continuous_stream_flushes_by_max_wait_cap():
    buffer = DebounceBuffer(debounce_seconds=3.5, max_wait_seconds=15)
    last = _fill(buffer, "Вася", ["раз", "два", "три"] * 10, _t(0), 0.5)

    ready = buffer.pop_ready(last)
    # поток не останавливался, тишины не было — сработал потолок
    assert len(ready) == 1
    username, text = ready[0]
    assert username == "Вася"
    assert text.startswith("раз два три")


def test_two_users_have_independent_buffers():
    buffer = DebounceBuffer(debounce_seconds=3.5, max_wait_seconds=15)
    _fill(buffer, "Вася", ["Приве", "как"], _t(0), 0.5)
    _fill(buffer, "Пётр", ["Ку"], _t(0.2), 0.5)

    ready = buffer.pop_ready(_t(4.5))
    ready.sort()
    assert ready == [("Вася", "Приве как"), ("Пётр", "Ку")]


def test_not_ready_buffer_stays_after_pop():
    buffer = DebounceBuffer(debounce_seconds=3.5, max_wait_seconds=15)
    _fill(buffer, "Вася", ["привет"], _t(0), 0.5)

    assert buffer.pop_ready(_t(2)) == []
    assert buffer.has_pending("Вася")
    assert buffer.pop_ready(_t(4)) == [("Вася", "привет")]
    assert not buffer.has_pending("Вася")


def test_add_after_pop_starts_fresh_buffer():
    buffer = DebounceBuffer(debounce_seconds=3.5, max_wait_seconds=15)
    _fill(buffer, "Вася", ["старое"], _t(0), 0.5)
    assert buffer.pop_ready(_t(4)) == [("Вася", "старое")]

    _fill(buffer, "Вася", ["новое"], _t(5), 0.5)
    assert buffer.has_pending("Вася")
    assert buffer.pop_ready(_t(9)) == [("Вася", "новое")]
    assert not buffer.has_pending("Вася")
