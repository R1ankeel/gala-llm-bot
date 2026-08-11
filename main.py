"""Прод-точка входа (Этап 8): реальный чат через Playwright.

Цикл: опрос DOM -> строгая адресация -> дебаунс -> пайплайн ответа ->
отправка с имитацией печати. Память/отношения/промпт — те же, что в
cli.py (единый пайплайн в core/pipeline.py).

Запуск:
  python main.py            # реальный браузер, вход вручную
  python main.py --fake     # dev-режим: FakeChatClient без браузера
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

import yaml

from chat_io.chat_client import PlaywrightChatClient
from chat_io.fake_chat_client import FakeChatClient
from core.config import Config, ConfigError, load_config
from core.character_loader import Character, load_character
from core.debounce_buffer import DebounceBuffer
from core.memory.realtime_profile import apply_realtime_updates
from core.pipeline import (
    handle_addressed_message,
    load_guard_keywords,
    load_relationship_config,
    load_search_keywords,
    make_client,
    make_runtime,
    make_store,
)
from core.route import parse_addressed_message, should_ignore_message
from core.schedule_provider import ScheduleConfigError, ScheduleProvider

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_PATH = "config/schedule.yaml"
DEFAULT_CHAT_CONFIG_PATH = "config/chat_config.yaml"


def load_chat_config(path: str = DEFAULT_CHAT_CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


async def launch_playwright_chat_client(chat_config: dict) -> PlaywrightChatClient:
    """Запускает браузер, открывает чат и ждёт ручного входа."""
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    page = await browser.new_page()
    await page.goto(chat_config["chat_url"])
    await asyncio.to_thread(
        input,
        "Залогинься в чате вручную и нажми Enter — бот начнёт опрос...",
    )
    return PlaywrightChatClient(
        page,
        typing_chars_per_second=chat_config["typing_chars_per_second"],
        typing_jitter=chat_config["typing_jitter"],
    )


async def run_bot(
    config: Config,
    character: Character,
    chat_config: dict,
    chat_client,
    task_keywords: dict,
    search_keywords: dict,
) -> int:
    llm_client = make_client(config)
    store = make_store(config)
    runtime = make_runtime(config, character, llm_client, store=store)

    bot_username = str(chat_config["bot_username"])
    debounce = DebounceBuffer(
        debounce_seconds=float(chat_config["debounce_seconds"]),
        max_wait_seconds=float(chat_config["debounce_max_wait_seconds"]),
    )
    poll_interval = float(chat_config["poll_interval_ms"]) / 1000.0
    ignored_users: set[str] = set()
    extract_threshold = int(runtime.memory.memory_config.get("extract_every_n_messages", 30))

    print(
        f"Цикл запущен против {bot_username}: опрос каждые "
        f"{poll_interval * 1000:.0f} мс, дебаунс "
        f"{debounce.debounce_seconds}s / потолок {debounce.max_wait_seconds}s. "
        "Ctrl+C — выход."
    )

    while True:
        now = datetime.now(timezone.utc)
        new_messages = await chat_client.poll_new_messages()

        for msg in new_messages:
            if should_ignore_message(msg.username, bot_username, ignored_users):
                continue
            runtime.memory.store.log_message(msg.username, msg.text, msg.timestamp)
            decision = parse_addressed_message(msg.text, bot_username)
            if decision.action == "addressed":
                apply_realtime_updates(runtime.memory.store, msg.username, decision.stripped_text)
                debounce.add(msg.username, decision.stripped_text, now)
            # log_only -> уже залогировано выше, больше ничего

        try:
            if runtime.memory.store.count_unprocessed() >= extract_threshold:
                runtime.memory.extractor.run_extraction_cycle()
        except Exception as err:  # noqa: BLE001 — память не должна ронять цикл
            logger.warning("fact extraction failed, continuing: %s", err)

        for username, combined_text in debounce.pop_ready(now):
            try:
                reply = handle_addressed_message(
                    config,
                    character,
                    username,
                    combined_text,
                    task_keywords,
                    search_keywords,
                    client=llm_client,
                    runtime=runtime,
                    log_to_memory=False,
                )
            except Exception as err:  # noqa: BLE001 — одна реплика не роняет цикл
                logger.warning("response pipeline failed for %s: %s", username, err)
                continue
            await chat_client.send_message(reply)
            runtime.memory.store.log_message(
                bot_username, reply, datetime.now(timezone.utc)
            )
            logger.info("-> %s: %s", username, reply)

        await asyncio.sleep(poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Прод-точка входа: реальный чат galaxy.mobstudio.ru "
        "через Playwright. Ручная отладка — в cli.py."
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="dev-режим: FakeChatClient без браузера (для смоуков)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        config = load_config()
        character = load_character(config.character_path)
        task_keywords = load_guard_keywords()
        search_keywords = load_search_keywords()
        chat_config = load_chat_config()
        ScheduleProvider(DEFAULT_SCHEDULE_PATH)
        load_relationship_config()
        make_store(config)
        if chat_config["bot_username"] != character.name:
            raise ConfigError(
                f"bot_username в chat_config.yaml ({chat_config['bot_username']}) "
                f"не совпадает с именем персонажа ({character.name}) — "
                "адресация и отношения сломаются."
            )
    except (ConfigError, OSError, ScheduleConfigError, KeyError) as err:
        print(f"[config] {err}", file=sys.stderr)
        return 1

    try:
        if args.fake:
            chat_client = FakeChatClient()
            print("dev-режим: FakeChatClient, без браузера.")
        else:
            chat_client = asyncio.run(launch_playwright_chat_client(chat_config))
        return asyncio.run(
            run_bot(
                config,
                character,
                chat_config,
                chat_client,
                task_keywords,
                search_keywords,
            )
        )
    except KeyboardInterrupt:
        print("\nОстановлено.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
