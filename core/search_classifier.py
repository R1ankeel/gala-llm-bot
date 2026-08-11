import re
from dataclasses import dataclass


@dataclass
class SearchVerdict:
    action: str
    category: str | None


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _match(pattern: str, normalized: str) -> bool:
    """Подстрока для фраз, слово (с возможными окончаниями) для одиночных
    паттернов. Граница слова спасает от ложных срабатываний вроде «игра»
    внутри «выиграл», а \\w* ловит склонения типа «градус» → «градусов»."""
    if " " in pattern:
        return pattern in normalized
    return bool(re.search(rf"\b{re.escape(pattern)}\w*", normalized))


def classify_query(text: str, keywords: dict) -> SearchVerdict:
    """Классифицирует запрос для поиска.

    blocked_weather/blocked_science → action="deflect"
    culture/factual                 → action="search"
    ничего не совпало               → action="none"

    blocked_* проверяются первыми: если запрос похож и на факт, и на
    явление — уклоняемся, а не ищем. Факты (цена, дата выхода, результат
    матча) имеют приоритет над culture при пересечении: «сколько стоит
    новая игра» — это факт про цену, а не разговор про игру как контент.
    Регистронезависимо, без LLM (тот же принцип, что и в task_guard).
    """
    normalized = _normalize(text)
    for category in ("blocked_weather", "blocked_science"):
        for pattern in keywords.get(category, []):
            if _match(_normalize(pattern), normalized):
                return SearchVerdict(action="deflect", category=category)
    for category in ("factual", "culture"):
        for pattern in keywords.get(category, []):
            if _match(_normalize(pattern), normalized):
                return SearchVerdict(action="search", category=category)
    return SearchVerdict(action="none", category=None)
