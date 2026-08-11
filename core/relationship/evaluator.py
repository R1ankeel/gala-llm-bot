"""Фоновая оценка отношений (write-path): LLM-дельта по сообщениям,
адресованным боту. Оцениваются только такие сообщения — в отличие от
facts_extractor, который читает весь чат."""

import json
import logging
import re

from core.llm_client import LLMError

logger = logging.getLogger(__name__)

DEFAULT_EVAL_EVERY_N_MESSAGES = 10
DEFAULT_DELTA_MIN = -3
DEFAULT_DELTA_MAX = 3

_SYSTEM_PROMPT = (
    "Ты — оценщик отношений. Оцени, как изменилось отношение пользователя к тебе "
    "по его последним сообщениям, от -3 до +3:\n"
    "  +3 — сильная забота, тепло, поддержка\n"
    "  +2 — заметно позитивно\n"
    "  +1 — слегка позитивно\n"
    "   0 — обычное общение\n"
    "  -1 — лёгкая грубость\n"
    "  -2 — токсичность\n"
    "  -3 — сильная агрессия, унижение\n"
    "Обычные вопросы и нейтральные реплики без грубости — это 0, "
    "не занижай просто за «скучный» разговор.\n"
    'Верни JSON вида {"delta": N, "reason": "кратко почему"}.'
)


class RelationshipEvaluator:
    """Считает сообщения на пользователя и раз в N запускает LLM-оценку.

    Счётчик сообщений хранится in-memory ({username: count}) — не
    персистентный между перезапусками. Осознанное упрощение: после
    рестарта бот просто «досчитает» с нуля, это некритично.
    """

    def __init__(self, store, memory_store, llm_client, config=None, character_name=None):
        self.store = store
        self.memory_store = memory_store
        self.llm_client = llm_client
        self.character_name = character_name
        cfg = config or {}
        self.eval_every_n_messages = int(cfg.get("eval_every_n_messages", DEFAULT_EVAL_EVERY_N_MESSAGES))
        self.delta_min = int(cfg.get("delta_min", DEFAULT_DELTA_MIN))
        self.delta_max = int(cfg.get("delta_max", DEFAULT_DELTA_MAX))
        self._counts: dict[str, int] = {}

    def count_message(self, username: str) -> int:
        """Увеличивает счётчик сообщений пользователя и возвращает его."""
        self._counts[username] = self._counts.get(username, 0) + 1
        return self._counts[username]

    def maybe_evaluate(self, username: str, message_count_since_last: int | None = None) -> RelationshipState | None:
        """Если с последней оценки накопилось меньше eval_every_n_messages —
        ничего не делать (None). Иначе — оценить и сбросить счётчик.

        message_count_since_last: при не-переданном значении берётся из
        внутреннего счётчика (или сбрасывается на 0).
        """
        if message_count_since_last is None:
            message_count_since_last = self._counts.get(username, 0)
        if message_count_since_last < self.eval_every_n_messages:
            return None

        recent_messages = self._recent_messages(username, limit=self.eval_every_n_messages)
        self._counts[username] = 0
        if not recent_messages:
            return None

        delta, reason = self._evaluate(username, recent_messages)
        delta = max(self.delta_min, min(self.delta_max, delta))
        return self.store.apply_delta(username, delta, reason)

    def _recent_messages(self, username: str, limit: int) -> list[str]:
        """Последние сообщения пользователя, адресованные боту."""
        rows = self.memory_store.conn.execute(
            "SELECT text FROM global_chat WHERE username = ? ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
        texts = [row["text"] for row in reversed(rows)]
        if not self.character_name:
            return texts
        return [text for text in texts if _is_addressed_to_bot(text, self.character_name)]

    def _evaluate(self, username: str, recent_messages: list[str]) -> tuple[int, str]:
        """Один LLM-вызов с низкой температурой. Фолбэк при невалидном JSON:
        (0, "parse_error") — отношения не должны портиться из-за сбоя парсинга."""
        rendered = " | ".join(recent_messages)
        user_message = (
            f"Вот последние сообщения пользователя {username}, адресованные тебе (боту): "
            f"{rendered}"
        )
        try:
            raw = self.llm_client.generate(
                _SYSTEM_PROMPT,
                [{"role": "user", "content": user_message}],
                temperature=0.1,
                max_tokens=256,
            )
        except LLMError as err:
            logger.warning("relationship evaluation LLM failed: %s", err)
            return 0, "llm_error"
        return _parse_delta_json(raw)


def _is_addressed_to_bot(text: str, character_name: str) -> bool:
    name = character_name.lower().replace("ё", "е")
    stripped = text.strip().lower().replace("ё", "е")
    if stripped == name:
        return True
    return bool(re.match(rf"{re.escape(name)}\W", stripped))


def _parse_delta_json(raw: str) -> tuple[int, str]:
    if not raw:
        return 0, "parse_error"
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("could not parse relationship delta JSON: %r", raw[:200])
            return 0, "parse_error"
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("could not parse relationship delta JSON: %r", raw[:200])
            return 0, "parse_error"
    if not isinstance(data, dict):
        logger.warning("relationship delta JSON не объект: %r", raw[:200])
        return 0, "parse_error"
    try:
        delta = int(data.get("delta", 0))
    except (TypeError, ValueError):
        delta = 0
    reason = str(data.get("reason") or "").strip()
    if not reason:
        reason = "no_reason"
    return delta, reason
