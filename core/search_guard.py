import random
import re

from core.character_loader import Character

DEFAULT_DEFLECT = "А я почём знаю. Сам глянь, не маленький."


def _deflect_examples(character: Character) -> str:
    examples = getattr(character, "deflect_style", None) or []
    if not examples:
        return "не моя тема, сам разберёшься"
    return "\n".join(f"- {line}" for line in examples)


def build_deflect_instruction(character: Character, category: str) -> str:
    """Инструкция-уклонение для blocked_weather / blocked_science."""
    topic = "погоде" if category == "blocked_weather" else "научном явлении"
    return (
        f"Собеседник спрашивает про {topic} — у тебя нет способа проверить "
        "это точно прямо сейчас.\n"
        "НЕ называй конкретные цифры (градусы, проценты, даты, единицы), "
        "НЕ изображай эксперта и НЕ выдумывай факты.\n"
        "Уклонись в своей манере — шуткой, встречным вопросом, «сам посмотри».\n"
        "Примеры твоей манеры:\n"
        f"{_deflect_examples(character)}"
    )


_WEATHER_NUMBER = re.compile(
    r"\d+\s*(?:°|градус)|"
    r"\d+\s*%\s*(?:осадк|влажност|вероятност)|"
    r"(?:осадк|влажност|вероятност)\w*\s+\d+\s*%|"
    r"\d+\s*мм|"
    r"(?:без|с)\s+осадков|"
    r"(?:дождь|снег|ветер)\s+\d+",
    re.IGNORECASE,
)

_SCIENCE_TERMS = re.compile(
    r"(гравитац|квант|частиц|атом|молекул|электромагнитн|ядро|плазм"
    r"|фотон|электрон|нейтрон|термодинам|давлен|энтропи|излучен"
    r"|скорость света|спектр|длина волн)"
)

_SCIENCE_LONG_REPLY = 300


def looks_like_hallucinated_fact(text: str, category: str) -> bool:
    """Пост-валидатор: модель всё же выдала конкретику/экспертность.

    blocked_weather — regex на цифры погоды (°C, проценты осадков…).
    blocked_science — грубая эвристика: длинный ответ + плотность
    спец.терминов.
    """
    if not text:
        return False
    if category == "blocked_weather":
        return bool(_WEATHER_NUMBER.search(text))
    if category == "blocked_science":
        stripped = text.strip()
        if len(stripped) <= _SCIENCE_LONG_REPLY:
            return False
        return len(_SCIENCE_TERMS.findall(stripped)) >= 3
    return False


def pick_deflect_line(character: Character, category: str) -> str:
    """Canned-уклонение из character.deflect_style (тон другой, чем
    в refusal_style: не раздражение, а «а я почём знаю»)."""
    examples = getattr(character, "deflect_style", None) or []
    if not examples:
        return DEFAULT_DEFLECT
    return random.choice(examples)
