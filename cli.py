import argparse
import sys

from core.character_loader import load_character
from core.config import Config, ConfigError, load_config
from core.dialogue_history import DialogueHistory
from core.layers import StubMemoryProvider, StubStateProvider
from core.llm_client import LLMClient, LLMError
from core.prompt_builder import PromptBuilder
from core.response_formatter import format_reply


def _make_client(config: Config) -> LLMClient:
    return LLMClient(config.ollama_base_url, config.model_name, think=config.llm_think)


def _make_builder(config: Config, character) -> PromptBuilder:
    return PromptBuilder(
        character,
        StubStateProvider(),
        StubMemoryProvider(),
        budget_chars=config.prompt_budget_chars,
    )


def _generate(client: LLMClient, config: Config, system_prompt: str, message: str) -> str:
    return client.generate(
        system_prompt,
        [{"role": "user", "content": message}],
        temperature=config.default_temperature,
        max_tokens=config.max_tokens,
    )


def run_once(config: Config, character, to: str, msg: str) -> int:
    builder = _make_builder(config, character)
    system_prompt = builder.build(to, msg)
    try:
        raw = _generate(_make_client(config), config, system_prompt, msg)
    except LLMError as err:
        print(f"[llm] {err}", file=sys.stderr)
        return 1
    print(format_reply(raw, to))
    return 0


def run_repl(config: Config, character, nick: str) -> int:
    client = _make_client(config)
    builder = _make_builder(config, character)
    history = DialogueHistory()

    print(f"REPL: ты — {nick}. Пустая строка выходит из цикла.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            break

        history.add("user", line)
        system_prompt = builder.build(nick, line, history)
        try:
            raw = _generate(client, config, system_prompt, line)
        except LLMError as err:
            print(f"[llm] {err}", file=sys.stderr)
            history.turns.pop()
            continue

        reply = format_reply(raw, nick)
        print(reply)
        reply_body = reply[len(f"{nick}, "):]
        history.add("assistant", reply_body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ручной тест персонажа: реплика по сообщению или REPL-диалог."
    )
    parser.add_argument("--to", help="ник собеседника (однострочный режим)")
    parser.add_argument("--msg", help="сообщение собеседника (однострочный режим)")
    parser.add_argument("--repl", action="store_true", help="REPL-режим с историей")
    parser.add_argument("--nick", help="ник собеседника (REPL-режим)")
    args = parser.parse_args(argv)

    try:
        config = load_config()
        character = load_character(config.character_path)
    except (ConfigError, OSError) as err:
        print(f"[config] {err}", file=sys.stderr)
        return 1

    if args.repl:
        if not args.nick:
            print("[usage] --repl требует --nick", file=sys.stderr)
            return 2
        return run_repl(config, character, args.nick)

    if not args.to or not args.msg:
        print(
            "[usage] либо --to И --msg (однострочный режим), "
            "либо --repl --nick <ник>",
            file=sys.stderr,
        )
        return 2
    return run_once(config, character, args.to, args.msg)


if __name__ == "__main__":
    raise SystemExit(main())
