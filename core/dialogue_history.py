from dataclasses import dataclass, field


@dataclass
class Turn:
    role: str
    content: str


@dataclass
class DialogueHistory:
    """История диалога одного пользователя, хранится in-memory.

    Персистентность в БД — не этот этап (будет побочным продуктом
    Этапа 6), логику заранее не дублировать.
    """

    max_turns: int = 8
    turns: list[Turn] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.turns.append(Turn(role, content))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def render(self, addressee_nick: str, character_name: str) -> str | None:
        """Формат для промпта:

        Вася: привет
        Гера: привет, чего хотел
        """
        if not self.turns:
            return None
        lines = []
        for turn in self.turns:
            if turn.role == "assistant":
                speaker = character_name
            else:
                speaker = addressee_nick
            lines.append(f"{speaker}: {turn.content}")
        return "\n".join(lines)
