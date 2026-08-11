import logging
from dataclasses import dataclass, field

from core.character_loader import Character, build_core_system_prompt
from core.dialogue_history import DialogueHistory
from core.layers import MemoryProvider, StateProvider

logger = logging.getLogger(__name__)


@dataclass
class PromptLayer:
    name: str
    content: str | None
    priority: int
    droppable: bool = True


RENDER_ORDER = ("identity", "state", "memory", "history")


class PromptBuilder:
    """Многослойный сборщик промпта.

    Порядок рендера фиксирован и не зависит от бюджета:
    identity → state → memory → history → текущее сообщение.

    Порядок отбрасывания при нехватке бюджета отдельный и берётся из
    priority: убираются ЦЕЛИКОМ сначала history, потом memory, потом
    state. Identity не отбрасывается никогда — если он один больше
    бюджета, остаётся целиком и в лог пишется warning.
    """

    def __init__(
        self,
        character: Character,
        state_provider: StateProvider,
        memory_provider: MemoryProvider,
        budget_chars: int = 6000,
    ):
        self.character = character
        self.state_provider = state_provider
        self.memory_provider = memory_provider
        self.budget_chars = budget_chars

    def build(
        self,
        addressee_nick: str,
        current_message: str,
        history: DialogueHistory | None = None,
    ) -> str:
        identity_layer = PromptLayer(
            "identity",
            build_core_system_prompt(self.character),
            priority=100,
            droppable=False,
        )
        state_layer = PromptLayer(
            "state",
            self.state_provider.render(addressee_nick),
            priority=30,
        )
        memory_layer = PromptLayer(
            "memory",
            self.memory_provider.render(addressee_nick, current_message),
            priority=20,
        )
        history_layer = PromptLayer(
            "history",
            history.render(addressee_nick, self.character.name) if history else None,
            priority=10,
        )

        layers = [layer for layer in (identity_layer, state_layer, memory_layer, history_layer) if layer.content is not None]

        total = sum(len(layer.content) for layer in layers)
        while total > self.budget_chars:
            droppable = [layer for layer in layers if layer.droppable]
            if not droppable:
                logger.warning(
                    "Промпт из %d символов превышает бюджет %d, но identity "
                    "неотбрасываемый — итоговый промпт собран целиком.",
                    total,
                    self.budget_chars,
                )
                break
            droppable.sort(key=lambda layer: layer.priority)
            layers.remove(droppable[0])
            total = sum(len(layer.content) for layer in layers)

        layers.sort(key=lambda layer: RENDER_ORDER.index(layer.name))
        system_prompt = "\n\n".join(layer.content for layer in layers)

        system_prompt += (
            f"\n\nТебе сейчас пишет пользователь с ником {addressee_nick}.\n"
            "Ответь на его сообщение в характере.\n"
            "Не указывай его ник в начале ответа — это сделает система."
        )
        return system_prompt
