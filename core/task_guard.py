import random
import re
from dataclasses import dataclass

from core.character_loader import Character

DEFAULT_REFUSAL = "Не, не моя тема."
LONG_REPLY_THRESHOLD = 400


@dataclass
class GuardVerdict:
    triggered: bool
    category: str | None


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def classify_task_request(text: str, keywords: dict) -> GuardVerdict:
    """Детектирует «ассистентские» запросы ДО генерации.

    Нормализует текст (lower, ё→е, схлопывание пробелов), проверяет
    подстроки по категориям в порядке объявления. Возвращает первую
    сработавшую категорию. Чисто строковая логика, без LLM, быстро
    и детерминированно.
    """
    normalized = _normalize(text)
    for category, patterns in keywords.items():
        for pattern in patterns:
            if _normalize(pattern) in normalized:
                return GuardVerdict(triggered=True, category=category)
    return GuardVerdict(triggered=False, category=None)


_CODE_FENCE = re.compile(r"```")
_CODE_KEYWORDS = re.compile(
    r"(?:\bdef\s+\w+\s*\(|\bfunction\s+\w+\s*\(|\bclass\s+\w+"
    r"|\bimport\s+\w+|\bfrom\s+\w+\s+import|\bprint\s*\("
    r"|\breturn\s+\w+|\bconst\s+\w+|#include)"
)
_STEP_MARKER = re.compile(r"\bшаг\s*[1-9]|\bэтап\s*[1-9]")
_TECH_TERM = re.compile(
    r"(код|программ|алгоритм|функци|скрипт|питон|python|java|sql"
    r"|база\s+данн|двигател|теор|математик|решение)"
)


def looks_like_compliance(text: str) -> bool:
    """Пост-генерационная проверка: ответ модели похож на фактическое
    выполнение задачи, а не на отказ. True — модель «скомпрометирована».
    """
    if not text:
        return False
    if _CODE_FENCE.search(text):
        return True
    if _CODE_KEYWORDS.search(text):
        return True
    if _STEP_MARKER.search(text) and _TECH_TERM.search(text):
        return True
    if len(text.strip()) > LONG_REPLY_THRESHOLD:
        return True
    return False


def pick_refusal_line(character: Character, category: str | None) -> str:
    """Гарантированный canned-ответ из character.refusal_style.

    Никогда не возвращает пустую строку: если список пуст — дефолт.
    """
    if not character.refusal_style:
        return DEFAULT_REFUSAL
    return random.choice(character.refusal_style)
