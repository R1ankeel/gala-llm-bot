import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

import yaml


@dataclass
class ScheduleSlot:
    start: time
    end: time
    activity: str


class ScheduleConfigError(Exception):
    """Понятная ошибка при загрузке конфига расписания."""


def _parse_hhmm(value) -> time:
    if not isinstance(value, str):
        raise ScheduleConfigError(f"время должно быть строкой HH:MM, а не {value!r}")
    parts = value.strip().split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ScheduleConfigError(f"невалидное время {value!r}: ожидается HH:MM")
    if len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ScheduleConfigError(f"невалидное время {value!r}: ожидается HH:MM (две цифры)")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleConfigError(
            f"невалидное время {value!r}: час должен быть 0-23, минуты 0-59"
        )
    return time(hour=hour, minute=minute)


class ScheduleProvider:
    """Реальная реализация StateProvider: чем бот «занят» по времени суток.

    Конфиг читается и валидируется ОДИН раз в __init__, а не при каждом
    render(). Ошибки конфига падают сразу при старте процесса, а не тихо
    в рантайме. Смещение часового пояса берётся из конфига — системная
    таймзона хост-машины не используется вообще.
    """

    def __init__(self, config_path: str):
        if not os.path.exists(config_path):
            raise ScheduleConfigError(f"Файл расписания {config_path} не найден")
        with open(config_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if not isinstance(data, dict):
            raise ScheduleConfigError(f"{config_path}: корень YAML должен быть словарём")

        try:
            self.offset_hours = int(data.get("local_tz_offset_hours", 0))
        except (TypeError, ValueError) as err:
            raise ScheduleConfigError(
                f"{config_path}: local_tz_offset_hours должно быть числом"
            ) from err

        default_activity = data.get("default_activity", "")
        if not isinstance(default_activity, str) or not default_activity.strip():
            raise ScheduleConfigError(f"{config_path}: default_activity не может быть пустой")
        self.default_activity = default_activity.strip()

        raw_slots = data.get("slots", [])
        if not isinstance(raw_slots, list) or not raw_slots:
            raise ScheduleConfigError(f"{config_path}: нужен хотя бы один слот в 'slots'")

        self.slots = []
        for index, raw in enumerate(raw_slots, start=1):
            if not isinstance(raw, dict):
                raise ScheduleConfigError(f"{config_path}: слот #{index} должен быть словарём")
            start = _parse_hhmm(raw.get("start"))
            end = _parse_hhmm(raw.get("end"))
            activity = raw.get("activity", "")
            if not isinstance(activity, str) or not activity.strip():
                raise ScheduleConfigError(f"{config_path}: слот #{index}: пустой activity")
            self.slots.append(ScheduleSlot(start=start, end=end, activity=activity.strip()))

    def _current_local_time(self) -> time:
        """UTC + local_tz_offset_hours -> time(). Без системной таймзоны."""
        return (datetime.now(timezone.utc) + timedelta(hours=self.offset_hours)).time()

    def _find_slot(self, now: time) -> str:
        """Ищет слот, в который попадает now (диапазон [start, end)).

        Переход через полночь (start > end): now >= start OR now < end.
        Первое совпадение по порядку в конфиге побеждает. Если ничего
        не подошло — default_activity (защита от дыр в конфиге).
        """
        for slot in self.slots:
            if slot.start <= slot.end:
                inside = slot.start <= now < slot.end
            else:
                inside = now >= slot.start or now < slot.end
            if inside:
                return slot.activity
        return self.default_activity

    def render(self, addressee_nick: str) -> str | None:
        """Протокол StateProvider. addressee_nick игнорируется — расписание
        общее состояние бота, не завязано на собеседника. Никогда не None."""
        return f"Сейчас ты: {self._find_slot(self._current_local_time())}."
