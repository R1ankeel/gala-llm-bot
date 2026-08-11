import argparse
import sys

from core.character_loader import build_core_system_prompt, load_character
from core.config import ConfigError, load_config
from core.llm_client import LLMClient, LLMError
from core.response_formatter import format_reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ручной тест персонажа: отправляет сообщение и печатает реплику."
    )
    parser.add_argument("--to", required=True, help="ник собеседника")
    parser.add_argument("--msg", required=True, help="сообщение собеседника")
    args = parser.parse_args(argv)

    try:
        config = load_config()
        character = load_character(config.character_path)
    except (ConfigError, OSError) as err:
        print(f"[config] {err}", file=sys.stderr)
        return 1

    system_prompt = build_core_system_prompt(character)
    system_prompt += (
        f"\n\nТебе сейчас пишет пользователь с ником {args.to}.\n"
        "Ответь на его сообщение в характере.\n"
        "Не указывай его ник в начале ответа — это сделает система."
    )

    client = LLMClient(
        config.ollama_base_url, config.model_name, think=config.llm_think
    )
    try:
        raw = client.generate(
            system_prompt,
            [{"role": "user", "content": args.msg}],
            temperature=config.default_temperature,
            max_tokens=config.max_tokens,
        )
    except LLMError as err:
        print(f"[llm] {err}", file=sys.stderr)
        return 1

    print(format_reply(raw, args.to))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
