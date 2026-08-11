"""LLM-экстракция фактов о пользователях из накопленных сообщений."""

import json
import logging
import re
import time
from dataclasses import dataclass

from core.llm_client import LLMError

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset({"fact", "hobby", "trait"})
_SARCASM_MARKERS = re.compile(r"(ахах|лол\b|шутк|\/s\b|😆|😅|😂|\!{3})", re.IGNORECASE)


@dataclass
class FactCandidate:
    username: str
    fact: str
    category: str


class FactsExtractor:
    def __init__(self, store, llm_client, character_name: str | None = None, memory_config: dict | None = None):
        self.store = store
        self.llm_client = llm_client
        self.character_name = character_name
        cfg = memory_config or {}
        self.extract_every_n_messages = int(cfg.get("extract_every_n_messages", 30))
        self.min_interval_seconds = int(cfg.get("min_interval_seconds", 120))
        self.max_facts_stored = int(cfg.get("max_facts_stored_per_user", 50))
        self._last_run_at: float | None = None

    def run_extraction_cycle(self) -> int:
        """Обрабатывает накопленные сообщения. Возвращает число обработанных."""
        if self._last_run_at is not None:
            elapsed = time.time() - self._last_run_at
            if elapsed < self.min_interval_seconds:
                return 0
        messages = self.store.get_unprocessed_messages(limit=200)
        if not messages:
            return 0

        by_user: dict[str, list] = {}
        for message in messages:
            if self._is_addressed_to_bot(message.text):
                continue
            by_user.setdefault(message.username, []).append(message)

        for username, user_messages in by_user.items():
            candidates = self._extract_candidates(username, user_messages)
            for candidate in self._validate_candidates(candidates):
                self.store.add_fact(candidate.username, candidate.fact, candidate.category, source="observed")

        self.store.mark_processed([m.id for m in messages])
        self._last_run_at = time.time()
        return len(messages)

    def _is_addressed_to_bot(self, text: str) -> bool:
        if not self.character_name:
            return False
        name = self.character_name.lower().replace("ё", "е")
        stripped = text.strip().lower().replace("ё", "е")
        if stripped == name:
            return True
        return bool(re.match(rf"{re.escape(name)}\W", stripped))

    def _extract_candidates(self, username: str, messages) -> list[FactCandidate]:
        lines = "\n".join(f"- {m.text}" for m in messages)
        system = (
            "Ты — экстрактор фактов о пользователях чата. "
            "Извлеки ТОЛЬКО факты, которые пользователь сообщил явно о СЕБЕ (не о других). "
            "Категории: fact (общий факт), hobby (увлечение), trait (черта характера). "
            'Верни JSON-список вида [{"fact": "...", "category": "..."}]. '
            "Если фактов нет — верни []. Не выдумывай и не додумывай."
        )
        user_message = f"Вот сообщения пользователя {username} в чате:\n{lines}"
        try:
            raw = self.llm_client.generate(
                system,
                [{"role": "user", "content": user_message}],
                temperature=0.1,
                max_tokens=512,
            )
        except LLMError as err:
            logger.warning("fact extraction LLM failed: %s", err)
            return []

        candidates: list[FactCandidate] = []
        for item in _parse_json_list(raw):
            if not isinstance(item, dict):
                continue
            fact = str(item.get("fact") or "").strip()
            category = str(item.get("category") or "fact").strip()
            if not fact:
                continue
            if category not in VALID_CATEGORIES:
                category = "fact"
            candidates.append(FactCandidate(username=username, fact=fact, category=category))
        return candidates

    def _validate_candidates(self, candidates: list[FactCandidate]) -> list[FactCandidate]:
        validated = []
        for candidate in candidates:
            fact = candidate.fact.strip()
            if not (3 <= len(fact) <= 200):
                continue
            if _SARCASM_MARKERS.search(fact.lower()):
                continue
            validated.append(candidate)
        return validated


def _parse_json_list(raw: str) -> list:
    if not raw:
        return []
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    logger.warning("could not parse LLM extraction output as JSON list: %r", raw[:200])
    return []
