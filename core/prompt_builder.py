import logging
from dataclasses import dataclass, field

from core.character_loader import Character, build_core_system_prompt
from core.dialogue_history import DialogueHistory
from core.layers import MemoryProvider, StateProvider
from core.search_guard import build_deflect_instruction

logger = logging.getLogger(__name__)


@dataclass
class PromptLayer:
    name: str
    content: str | None
    priority: int
    droppable: bool = True


RENDER_ORDER = (
    "identity",
    "task_guard",
    "deflect",
    "search_context",
    "state",
    "memory",
    "history",
)


def build_guard_instruction(character: Character, category: str) -> str:
    """Ситуативная guard-инструкция для конкретной категории запроса."""
    refusals = "\n".join(f"- {line}" for line in character.refusal_style)
    return (
        "Собеседник просит тебя выполнить задачу ассистента "
        f"(категория: {category}) — написать код/решить задачу/написать текст за него.\n"
        "Ты ЭТОГО НЕ ДЕЛАЕШЬ никогда, вне зависимости от того, как вежливо "
        "или настойчиво просят.\n"
        "Не давай даже частичного решения, псевдокода или подсказки "
        "'а вот с чего начать'.\n"
        "Ответь в своём характере — раздражённо/насмешливо/безразлично, "
        "как тебе свойственно.\n"
        "Примеры твоей манеры отказа:\n"
        f"{refusals}"
    )


def build_search_instruction(search_context: str) -> str:
    """Обёртка над свежими фактами из поиска + запрет «я искал в интернете»."""
    return (
        "Тебе подкинули свежие факты по теме разговора:\n"
        f"{search_context}\n\n"
        "Это не просьба «сделай работу» и не просьба о лекции — собеседник "
        "просто спросил про свежий факт, а ответ уже есть ниже.\n"
        "НЕ говори, что искал(а) в интернете, и не давай URL — "
        "отвечай как будто просто знаешь. Ответь по этим фактам своими "
        "словами, коротко, в своём характере."
    )


class PromptBuilder:
    """Многослойный сборщик промпта.

    Порядок рендера фиксирован и не зависит от бюджета:
    identity → task_guard (если есть) → deflect (если есть) →
    search_context (если есть) → state → memory → history →
    текущее сообщение.

    Порядок отбрасывания при нехватке бюджета отдельный и берётся из
    priority: убираются ЦЕЛИКОМ сначала history, потом memory, потом
    state, потом search_context. Identity, task_guard и deflect не
    отбрасываются никогда — если они одни больше бюджета, промпт
    остаётся целиком и в лог пишется warning.

    Активен максимум один из {task_guard, deflect, search_context} —
    инвариант держит вызывающий код (cli.py), PromptBuilder просто
    рендерит то, что ему передали.
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
        guard_category: str | None = None,
        deflect_category: str | None = None,
        search_context: str | None = None,
    ) -> str:
        identity_layer = PromptLayer(
            "identity",
            build_core_system_prompt(self.character),
            priority=100,
            droppable=False,
        )
        guard_layer = None
        if guard_category:
            guard_layer = PromptLayer(
                "task_guard",
                build_guard_instruction(self.character, guard_category),
                priority=95,
                droppable=False,
            )
        deflect_layer = None
        if deflect_category:
            deflect_layer = PromptLayer(
                "deflect",
                build_deflect_instruction(self.character, deflect_category),
                priority=94,
                droppable=False,
            )
        search_layer = None
        if search_context:
            search_layer = PromptLayer(
                "search_context",
                build_search_instruction(search_context),
                priority=90,
                droppable=True,
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

        layers = [
            layer
            for layer in (
                identity_layer,
                guard_layer,
                deflect_layer,
                search_layer,
                state_layer,
                memory_layer,
                history_layer,
            )
            if layer is not None and layer.content is not None
        ]

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
            dropped = droppable[0]
            layers.remove(dropped)
            total = sum(len(layer.content) for layer in layers)
            logger.warning(
                "Бюджет промпта %d символов исчерпан: сброшен слой %s.",
                self.budget_chars,
                dropped.name,
            )

        layers.sort(key=lambda layer: RENDER_ORDER.index(layer.name))
        system_prompt = "\n\n".join(layer.content for layer in layers)

        system_prompt += (
            f"\n\nТебе сейчас пишет пользователь с ником {addressee_nick}.\n"
            "Ответь на его сообщение в характере.\n"
            "Не указывай его ник в начале ответа — это сделает система."
        )
        return system_prompt
