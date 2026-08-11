import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Понятная ошибка конфигурации."""


@dataclass(frozen=True)
class Config:
    ollama_base_url: str
    model_name: str
    default_temperature: float
    max_tokens: int
    character_path: str
    llm_think: bool = False
    prompt_budget_chars: int = 6000


def _parse_env_file(env_path: str) -> dict:
    values = {}
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key] = value
    return values


def load_config(env_path: str = ".env") -> Config:
    if not os.path.exists(env_path):
        raise ConfigError(
            f"Файл {env_path} не найден. Скопируй .env.example в .env "
            "и укажи MODEL_NAME."
        )

    values = _parse_env_file(env_path)

    model_name = values.get("MODEL_NAME", "").strip()
    if not model_name:
        raise ConfigError(
            "В .env не задан MODEL_NAME — без модели нечего запускать. "
            "Пример: MODEL_NAME=goetia-26b-a4b-q4"
        )

    try:
        temperature = float(values.get("DEFAULT_TEMPERATURE", "0.8"))
        max_tokens = int(values.get("MAX_TOKENS", "300"))
    except ValueError as err:
        raise ConfigError(f"В .env кривое число: {err}") from err

    if max_tokens <= 0:
        raise ConfigError("MAX_TOKENS в .env должен быть больше нуля.")

    try:
        prompt_budget_chars = int(values.get("PROMPT_BUDGET_CHARS", "6000"))
    except ValueError as err:
        raise ConfigError(f"В .env кривое число: {err}") from err
    if prompt_budget_chars <= 0:
        raise ConfigError("PROMPT_BUDGET_CHARS в .env должен быть больше нуля.")

    llm_think = values.get("LLM_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}

    return Config(
        ollama_base_url=values.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        model_name=model_name,
        default_temperature=temperature,
        max_tokens=max_tokens,
        character_path=values.get("CHARACTER_PATH", "./character/character.yaml"),
        llm_think=llm_think,
        prompt_budget_chars=prompt_budget_chars,
    )
