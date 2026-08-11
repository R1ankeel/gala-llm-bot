import argparse
import logging
import sys

from core.character_loader import load_character
from core.config import Config, ConfigError, load_config
from core.dialogue_history import DialogueHistory
from core.llm_client import LLMClient, LLMError
from core.memory.store import MemoryStore
from core.pipeline import (
    MemoryRuntime,
    Runtime,
    apply_guard_fallback,
    build_system_prompt,
    generate,
    handle_addressed_message,
    load_guard_keywords,
    load_relationship_config,
    load_search_keywords,
    make_builder,
    make_client,
    make_runtime,
    make_store,
    run_memory_pipeline,
    run_relationship_evaluation,
)
from core.response_formatter import format_reply
from core.schedule_provider import ScheduleProvider, ScheduleConfigError
from core.search_classifier import SearchVerdict, classify_query
from core.task_guard import classify_task_request

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_PATH = "config/schedule.yaml"


def run_once(
    config: Config,
    character,
    to: str,
    msg: str,
    task_keywords: dict,
    search_keywords: dict,
    client: LLMClient | None = None,
    search_client=None,
    store: MemoryStore | None = None,
    memory: MemoryRuntime | None = None,
    runtime: Runtime | None = None,
) -> str:
    return handle_addressed_message(
        config,
        character,
        to,
        msg,
        task_keywords,
        search_keywords,
        client=client,
        search_client=search_client,
        store=store,
        memory=memory,
        runtime=runtime,
    )


def run_repl(
    config: Config,
    character,
    nick: str,
    task_keywords: dict,
    search_keywords: dict,
    client: LLMClient | None = None,
    store: MemoryStore | None = None,
) -> int:
    client = client or make_client(config)
    runtime = make_runtime(config, character, client, store=store)
    builder = make_builder(
        config, character, runtime.memory.memory_provider, runtime.state_provider
    )
    history = DialogueHistory()

    print(f"REPL-режим. Крутимся против {nick}. Пустая строка или Ctrl+C/Ctrl+D — выход.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            break

        history.add("user", line)
        run_memory_pipeline(runtime.memory, nick, line)
        run_relationship_evaluation(runtime, nick)
        task_verdict = classify_task_request(line, task_keywords)
        search_verdict = SearchVerdict(action="none", category=None)
        if not task_verdict.triggered:
            search_verdict = classify_query(line, search_keywords)

        system_prompt = build_system_prompt(
            builder, nick, line, task_verdict, search_verdict, None
        )
        try:
            raw = generate(client, config, system_prompt, line)
        except LLMError as err:
            print(f"[llm] {err}", file=sys.stderr)
            history.turns.pop()
            continue

        raw = apply_guard_fallback(character, raw, task_verdict, search_verdict)
        reply = format_reply(raw, nick)
        print(reply)
        history.add("assistant", reply[len(f"{nick}, "):])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ностальгирующий клоун-продавец из круглосуточного ларька: "
        "ручная отладка (--to/--msg/--repl). Прод-путь к реальному чату — main.py."
    )
    parser.add_argument("--to", help="ник собеседника (для одиночного режима)")
    parser.add_argument("--msg", help="текст сообщения (для одиночного режима)")
    parser.add_argument("--repl", action="store_true", help="REPL-режим для тестирования")
    parser.add_argument("--nick", help="ник собеседника (REPL-режим)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        config = load_config()
        character = load_character(config.character_path)
        task_keywords = load_guard_keywords()
        search_keywords = load_search_keywords()
        ScheduleProvider(DEFAULT_SCHEDULE_PATH)
        load_relationship_config()
        make_store(config)
    except (ConfigError, OSError, ScheduleConfigError) as err:
        print(f"[config] {err}", file=sys.stderr)
        return 1

    if args.repl:
        if not args.nick:
            print("[usage] --repl требует --nick", file=sys.stderr)
            return 2
        return run_repl(config, character, args.nick, task_keywords, search_keywords)

    if not args.to or not args.msg:
        print(
            "[usage] передай --to и --msg (для одиночного режима), "
            "или --repl --nick <ник>",
            file=sys.stderr,
        )
        return 2

    try:
        reply = run_once(
            config, character, args.to, args.msg, task_keywords, search_keywords
        )
    except LLMError as err:
        print(f"[llm] {err}", file=sys.stderr)
        return 1
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
