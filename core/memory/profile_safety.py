"""Проверка значений профиля перед записью в БД.

Защита от очевидных инъекций в тексте промпта: длинные/пустые строки,
markup-теги и запрещённые маркеры (например, "игнорируй инструкции").
"""

import logging
from functools import lru_cache

import yaml

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_CONFIG_PATH = "config/memory.yaml"

_FORBIDDEN_MARKERS: tuple[str, ...] | None = None


def _load_forbidden_markers() -> tuple[str, ...]:
    global _FORBIDDEN_MARKERS
    if _FORBIDDEN_MARKERS is None:
        try:
            with open(DEFAULT_MEMORY_CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            markers = data.get("forbidden_value_markers", []) or []
            _FORBIDDEN_MARKERS = tuple(str(m).lower() for m in markers)
        except OSError:
            logger.warning("memory config missing, forbidden markers disabled")
            _FORBIDDEN_MARKERS = ()
    return _FORBIDDEN_MARKERS


def is_safe_value(field: str, value) -> bool:
    if field == "age":
        try:
            age = int(value)
        except (TypeError, ValueError):
            return False
        return 1 <= age <= 120

    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > 100:
        return False
    if "<" in text or ">" in text:
        return False

    lowered = text.lower()
    for marker in _load_forbidden_markers():
        if marker in lowered:
            return False
    return True
