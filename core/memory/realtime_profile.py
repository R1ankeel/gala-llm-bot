"""Realtime-профиль: извлечение фактов о себе по простым regex-паттернам.

Без LLM: парсим входящее сообщение на лету и сразу обновляем user_profile.
"""

import re

PATTERNS: dict[str, list] = {
    "real_name": [
        r"меня зовут (\w+)",
        r"я\s*[-—]\s*(\w+)$",
    ],
    "age": [
        r"мне (\d{1,2}) лет",
        r"мне (\d{1,2}) год",
        r"мне (\d{1,2})\b",
    ],
    "city": [
        r"я из (\w+)",
        r"живу в (\w+)",
    ],
    "gender": [
        (r"\bя\s+девушка\b", "female"),
        (r"\bя\s+парень\b", "male"),
        (r"\bя\s+девочка\b", "female"),
        (r"\bя\s+мальчик\b", "male"),
    ],
    "job": [
        r"работаю (\w+)",
        r"я работаю (\w+)",
    ],
}

_INSTRUMENTAL_ENDINGS = ("ом", "ем", "ой", "ей")

_REAL_NAME_STOPWORDS = frozenset(
    {"и", "а", "что", "как", "кто", "где", "когда", "зачем", "почему", "это", "то", "чтобы", "не"}
)


def _strip_job_ending(word: str) -> str:
    """Приводит профессию к словарной форме: "таксистом" -> "таксист"."""
    for ending in _INSTRUMENTAL_ENDINGS:
        if len(word) > len(ending) + 2 and word.endswith(ending):
            return word[: -len(ending)]
    return word


def extract_realtime_updates(text: str) -> dict[str, str]:
    """Возвращает {поле: значение} по паттернам. Пустой dict — ничего не найдено."""
    updates: dict[str, str] = {}
    for field, patterns in PATTERNS.items():
        for pattern in patterns:
            if isinstance(pattern, tuple):
                regex, value = pattern
                if re.search(regex, text, re.IGNORECASE):
                    updates[field] = value
                    break
            else:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1)
                    if field == "job":
                        value = _strip_job_ending(value)
                    if field == "real_name" and value in _REAL_NAME_STOPWORDS:
                        continue
                    updates[field] = value
                    break
    return updates


def apply_realtime_updates(store, username: str, text: str) -> None:
    """Применяет найденные факты к профилю через store (с проверкой безопасности)."""
    updates = extract_realtime_updates(text)
    for field, value in updates.items():
        if field == "gender":
            store.upsert_profile_field(username, "gender", value)
            store.upsert_profile_field(username, "gender_source", "self_declared")
        else:
            store.upsert_profile_field(username, field, value)
