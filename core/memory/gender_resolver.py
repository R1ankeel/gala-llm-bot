"""Определение пола собеседника.

Порядок: 1) явный пол из профиля; 2) ник по имени/суффиксам (эвристика).
"""

import re


def _nick_base(nick: str) -> str:
    match = re.match(r"([а-яёa-z]+)", nick.lower().replace("ё", "е"))
    return match.group(1) if match else ""


def resolve_gender(username: str, profile, gender_heuristics: dict) -> tuple[str | None, str | None]:
    """Возвращает (пол, источник) или (None, None), если неизвестно."""
    if profile is not None and profile.gender:
        return profile.gender, "explicit"

    base = _nick_base(username)
    if not base:
        return None, None

    def norm(values) -> set[str]:
        return {str(v).lower().replace("ё", "е") for v in (values or [])}

    male_names = norm(gender_heuristics.get("common_male_names", []))
    female_names = norm(gender_heuristics.get("common_female_names", []))
    if base in male_names:
        return "male", "heuristic"
    if base in female_names:
        return "female", "heuristic"

    female_suffixes = sorted(
        (s.lower() for s in gender_heuristics.get("female_suffixes", [])),
        key=len,
        reverse=True,
    )
    male_suffixes = sorted(
        (s.lower() for s in gender_heuristics.get("male_suffixes", [])),
        key=len,
        reverse=True,
    )
    for suffix in female_suffixes:
        if len(base) > len(suffix) and base.endswith(suffix):
            return "female", "heuristic"
    for suffix in male_suffixes:
        if len(base) > len(suffix) and base.endswith(suffix):
            return "male", "heuristic"
    return None, None
