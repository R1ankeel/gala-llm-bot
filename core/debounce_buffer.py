"""Дебаунс: склейка серии коротких сообщений одного пользователя в
одну задачу ПЕРЕД отправкой в LLM.

Тик-based дизайн (НЕ asyncio.sleep/таймеры): буфер синхронизирован с
основным циклом опроса чата, а "текущее время" подставляется в
pop_ready/add снаружи — поэтому тесты гоняются без реальных ожиданий.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PendingBuffer:
    username: str
    first_message_at: datetime
    last_message_at: datetime
    parts: list[str] = field(default_factory=list)


class DebounceBuffer:
    """Копит сообщения пользователя до тишины или до жёсткого потолка."""

    def __init__(self, debounce_seconds: float, max_wait_seconds: float) -> None:
        self.debounce_seconds = debounce_seconds
        self.max_wait_seconds = max_wait_seconds
        self._buffers: dict[str, PendingBuffer] = {}

    def add(self, username: str, text: str, now: datetime) -> None:
        """Если для username уже есть pending-буфер — добавить text
        в parts и обновить last_message_at. Иначе создать новый буфер
        с first_message_at=last_message_at=now."""
        buffer = self._buffers.get(username)
        if buffer is None:
            self._buffers[username] = PendingBuffer(
                username=username,
                first_message_at=now,
                last_message_at=now,
                parts=[text],
            )
        else:
            buffer.parts.append(text)
            buffer.last_message_at = now

    def has_pending(self, username: str) -> bool:
        return username in self._buffers

    def pop_ready(self, now: datetime) -> list[tuple[str, str]]:
        """Возвращает список (username, объединённый_текст) для всех
        буферов, готовых к обработке:
          - now - last_message_at >= debounce_seconds  (тишина)
          ИЛИ
          - now - first_message_at >= max_wait_seconds (потолок)

        Объединённый текст — parts через пробел (одна смысловая
        реплика: "привет как дела" из отдельных слов). Извлечённые
        буферы УДАЛЯЮТСЯ (pop, не peek)."""
        ready: list[tuple[str, str]] = []
        for username in list(self._buffers):
            buffer = self._buffers[username]
            silent = (now - buffer.last_message_at).total_seconds() >= self.debounce_seconds
            overdue = (now - buffer.first_message_at).total_seconds() >= self.max_wait_seconds
            if silent or overdue:
                ready.append((username, " ".join(buffer.parts)))
                del self._buffers[username]
        return ready
