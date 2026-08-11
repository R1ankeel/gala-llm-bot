from typing import Protocol


class StateProvider(Protocol):
    """Текущее состояние бота: занятие, настроение, отношение.

    Вызывается на каждый ответ, поэтому не должен обращаться к
    сети/БД дольше нескольких миллисекунд. Возвращает строку или None.
    """

    def render(self, addressee_nick: str) -> str | None: ...


class MemoryProvider(Protocol):
    """Сжатая сводка релевантных фактов о собеседнике.

    Возвращает пару строк максимум или None.
    """

    def render(self, addressee_nick: str, current_message: str) -> str | None: ...


class StubStateProvider:
    """Заглушка Этапа 2. Реальная реализация придёт на Этапе 5/7."""

    def render(self, addressee_nick: str) -> str | None:
        return None


class StubMemoryProvider:
    """Заглушка Этапа 2. Реальная реализация придёт на Этапе 6."""

    def render(self, addressee_nick: str, current_message: str) -> str | None:
        return None
