import os
from datetime import datetime, time, timedelta, timezone

import pytest

from core.schedule_provider import ScheduleConfigError, ScheduleProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "schedule.yaml")


def provider_at(now: str, config_path: str = CONFIG_PATH) -> ScheduleProvider:
    """ScheduleProvider с подставленным «текущим» временем HH:MM."""
    provider = ScheduleProvider(config_path)
    hour, minute = now.split(":")
    provider._current_local_time = lambda: time(hour=int(hour), minute=int(minute))
    return provider


def _write_config(tmp_path, content: str) -> str:
    path = tmp_path / "schedule.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_work_day():
    assert provider_at("12:00")._find_slot(time(hour=12)) == "на работе, отвечает между делом"


def test_commute_home():
    assert provider_at("18:30")._find_slot(time(hour=18, minute=30)) == (
        "едет домой, отвечает с телефона в транспорте"
    )


def test_cooking_dinner():
    assert provider_at("20:00")._find_slot(time(hour=20)) == (
        "готовит ужин, могут быть паузы в ответах"
    )


def test_resting_home():
    assert provider_at("22:00")._find_slot(time(hour=22)) == (
        "отдыхает дома, самое разговорчивое время"
    )


def test_sleep_wrap_midnight():
    assert provider_at("02:00")._find_slot(time(hour=2)) == (
        "спит или должна спать, отвечает вяло/неохотно"
    )


def test_sleep_boundary_before_morning():
    assert provider_at("06:59")._find_slot(time(hour=6, minute=59)) == (
        "спит или должна спать, отвечает вяло/неохотно"
    )


def test_morning_start_inclusive():
    assert provider_at("07:00")._find_slot(time(hour=7)) == "собирается, утренняя суета"


def test_slot_start_inclusive_end_exclusive():
    assert provider_at("09:00")._find_slot(time(hour=9)) == "на работе, отвечает между делом"
    assert provider_at("17:59")._find_slot(time(hour=17, minute=59)) == (
        "на работе, отвечает между делом"
    )
    assert provider_at("18:00")._find_slot(time(hour=18)) == (
        "едет домой, отвечает с телефона в транспорте"
    )


def test_night_slot_boundaries():
    assert provider_at("23:29")._find_slot(time(hour=23, minute=29)) == (
        "отдыхает дома, самое разговорчивое время"
    )
    assert provider_at("23:30")._find_slot(time(hour=23, minute=30)) == (
        "спит или должна спать, отвечает вяло/неохотно"
    )


def test_hole_in_schedule_uses_default(tmp_path):
    config = _write_config(
        tmp_path,
        "local_tz_offset_hours: 3\n"
        "default_activity: залипает в телефон\n"
        "slots:\n"
        '  - start: "10:00"\n'
        '    end: "11:00"\n'
        "    activity: на работе\n",
    )
    provider = ScheduleProvider(config)
    assert provider._find_slot(time(hour=10, minute=30)) == "на работе"
    assert provider._find_slot(time(hour=11, minute=0)) == "залипает в телефон"
    assert provider._find_slot(time(hour=15, minute=0)) == "залипает в телефон"


def test_first_slot_wins_on_overlap(tmp_path):
    config = _write_config(
        tmp_path,
        "local_tz_offset_hours: 3\n"
        "default_activity: дефолт\n"
        "slots:\n"
        '  - start: "10:00"\n'
        '    end: "12:00"\n'
        "    activity: первый\n"
        '  - start: "11:00"\n'
        '    end: "13:00"\n'
        "    activity: второй\n",
    )
    assert ScheduleProvider(config)._find_slot(time(hour=11, minute=30)) == "первый"


def test_render_returns_state_string():
    assert provider_at("20:00").render("Вася") == (
        "Сейчас ты: готовит ужин, могут быть паузы в ответах."
    )


def test_render_never_none():
    for now in ("00:00", "09:15", "23:59"):
        assert provider_at(now).render("Вася") is not None


def test_invalid_time_format_raises(tmp_path):
    for bad_time in ("9:00", "25:00", "abc", "09-00", "09:00:00"):
        config = _write_config(
            tmp_path,
            "local_tz_offset_hours: 3\n"
            "default_activity: дефолт\n"
            "slots:\n"
            f'  - start: "{bad_time}"\n'
            '    end: "10:00"\n'
            "    activity: слот\n",
        )
        with pytest.raises(ScheduleConfigError):
            ScheduleProvider(config)


def test_empty_default_activity_raises(tmp_path):
    config = _write_config(
        tmp_path,
        "local_tz_offset_hours: 3\n"
        "default_activity: ' '\n"
        "slots:\n"
        '  - start: "10:00"\n'
        '    end: "11:00"\n'
        "    activity: слот\n",
    )
    with pytest.raises(ScheduleConfigError):
        ScheduleProvider(config)


def test_no_slots_raises(tmp_path):
    config = _write_config(
        tmp_path,
        "local_tz_offset_hours: 3\n"
        "default_activity: дефолт\n"
        "slots: []\n",
    )
    with pytest.raises(ScheduleConfigError):
        ScheduleProvider(config)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ScheduleConfigError):
        ScheduleProvider(str(tmp_path / "nope.yaml"))


def test_current_local_time_applies_offset(monkeypatch):
    from core import schedule_provider as sp_module

    fixed_utc = datetime(2026, 6, 15, 10, 30, tzinfo=timezone.utc)

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fixed_utc

    monkeypatch.setattr(sp_module, "datetime", FakeDateTime)
    provider = ScheduleProvider(CONFIG_PATH)
    assert provider.offset_hours == 3
    assert provider._current_local_time() == time(hour=13, minute=30)
