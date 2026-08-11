"""CompositeStateProvider — объединяет несколько StateProvider в один.

ScheduleProvider и RelationshipProvider не модифицируются: они оборачиваются.
Это проверка Protocol из Этапа 2 — PromptBuilder не знает, что state_provider
теперь составной.
"""

from core.layers import StateProvider


class CompositeStateProvider:
    """Реализация StateProvider Protocol."""

    def __init__(self, providers: list[StateProvider]):
        self.providers = providers

    def render(self, addressee_nick: str) -> str | None:
        parts = [provider.render(addressee_nick) for provider in self.providers]
        parts = [part for part in parts if part]
        if not parts:
            return None
        return " ".join(parts)
