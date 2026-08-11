from dataclasses import dataclass, field

import yaml


class CharacterLoadError(Exception):
    """Ошибка чтения карточки персонажа."""


@dataclass
class Character:
    name: str
    short_bio: str
    speech_style: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)
    refusal_style: list[str] = field(default_factory=list)
    example_dialogues: list[dict] = field(default_factory=list)
    never_do: list[str] = field(default_factory=list)
    deflect_style: list[str] = field(default_factory=list)


_REQUIRED_FIELDS = {
    "name",
    "short_bio",
    "speech_style",
    "boundaries",
    "refusal_style",
    "example_dialogues",
    "never_do",
}


def load_character(path: str) -> Character:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise CharacterLoadError(f"{path}: корень YAML должен быть словарём")

    missing = _REQUIRED_FIELDS - set(data)
    if missing:
        raise CharacterLoadError(
            f"{path}: отсутствуют обязательные поля: {', '.join(sorted(missing))}"
        )

    return Character(
        name=str(data["name"]),
        short_bio=str(data["short_bio"]),
        speech_style=[str(item) for item in data["speech_style"]],
        boundaries=[str(item) for item in data["boundaries"]],
        refusal_style=[str(item) for item in data["refusal_style"]],
        example_dialogues=[
            {"user": str(pair.get("user", "")), "bot": str(pair.get("bot", ""))}
            for pair in data["example_dialogues"]
        ],
        never_do=[str(item) for item in data["never_do"]],
        deflect_style=[str(item) for item in data.get("deflect_style", [])],
    )


def build_core_system_prompt(character: Character) -> str:
    """Собирает единый неразрезаемый core-блок: bio + стиль + границы +
    отказы + few-shot + жёсткие запреты.

    В будущих этапах этот блок ВСЕГДА идёт первым и целиком — PromptBuilder
    не имеет права его резать или переставлять.
    """
    blocks = [f"Ты — {character.name}.\n\n{character.short_bio}"]

    blocks.append(
        "Стиль речи:\n" + "\n".join(f"- {item}" for item in character.speech_style)
    )

    blocks.append(
        "Что не делаешь:\n" + "\n".join(f"- {item}" for item in character.boundaries)
    )

    blocks.append(
        "Как отказываешь:\n"
        + "\n".join(f"- {item}" for item in character.refusal_style)
    )

    dialogues = [
        f"Пользователь: {pair['user']}\n{character.name}: {pair['bot']}"
        for pair in character.example_dialogues
    ]
    blocks.append("Примеры диалогов:\n" + "\n".join(dialogues))

    blocks.append(
        "Жёсткие запреты:\n" + "\n".join(f"- {item}" for item in character.never_do)
    )

    return "\n\n".join(blocks)
