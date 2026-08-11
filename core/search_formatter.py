import re

from core.search_client import SearchResult


def _condense(text: str, limit: int = 200) -> str:
    condensed = " ".join(text.split())
    if len(condensed) > limit:
        condensed = condensed[: limit - 1].rstrip() + "…"
    return condensed


def format_search_context(
    results: list[SearchResult], max_chars: int = 500
) -> str | None:
    """Схлопывает результаты в компактную внутреннюю сводку.

    Это контекст для модели, а не материал для дословного цитирования:
    URL не включаются, снипеты сжимаются (лишние пробелы, обрезка).
    Возвращает None, если показывать нечего.
    """
    if not results:
        return None

    parts = []
    for result in results:
        if not result.snippet or not result.snippet.strip():
            continue
        parts.append(f"- {_condense(result.snippet)}")

    if not parts:
        return None

    text = "Найдено по теме:\n" + "\n".join(parts)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text
