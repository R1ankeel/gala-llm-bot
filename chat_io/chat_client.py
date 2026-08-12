"""I/O к чату: чтение сообщений из DOM и отправка с имитацией печати.

PlaywrightChatClient — единственное место, знающее про реальный браузер.
Парсинг и дедуп вынесены в чистые функции (build_dom_key, dedup_messages,
SeenKeys) — они тестируются без реального Playwright.

Пакет называется chat_io (а не io), потому что `io` в Python занят
стандартной библиотекой — пакет с таким именем невозможно импортировать.
"""

import asyncio
import hashlib
import logging
import random
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

logger = logging.getLogger(__name__)

PARSE_TIMEOUT_SECONDS = 8.0

# Селекторы — под реальную структуру DOM galaxy.mobstudio.ru:
# текстовые сообщения в .channel-message.channel-message--text, системные
# topic/server исключаются, ник и время лежат в
# .channel-message__content__title, текст — в
# .channel-message__content__text, поле ввода —
# .channel-new-message__text-field__input, отправка — по кнопке.
DEFAULT_MESSAGE_SELECTOR = (
    ".channel-message.channel-message--text"
    ":not(.channel-message--topic):not(.channel-message--server)"
)
DEFAULT_USERNAME_SELECTOR = ".channel-message__content__title"
DEFAULT_TIMESTAMP_SELECTOR = ".channel-message__time"
DEFAULT_TEXT_SELECTOR = ".channel-message__content__text"
DEFAULT_INPUT_SELECTOR = ".channel-new-message__text-field__input"
DEFAULT_SEND_SELECTOR = "#channel-new-message__send-button"


@dataclass
class ChatMessage:
    username: str
    text: str
    timestamp: datetime
    dom_key: str  # стабильный ключ для дедупа


class ChatClient(Protocol):
    async def poll_new_messages(self) -> list[ChatMessage]:
        """Вернуть НОВЫЕ сообщения с прошлого вызова (дедуп внутри)."""
        ...

    async def send_message(self, text: str) -> None:
        """Набрать текст с имитацией печати и отправить."""
        ...


def build_dom_key(username: str, timestamp_raw: str, text: str, occurrence: int = 0) -> str:
    """Стабильный ключ для дедупа.

    occurrence — порядковый номер повтора одинаковой тройки
    (username, timestamp_raw, text) внутри одного снимка: легитимный
    повтор «Анька, привет» дважды подряд даёт РАЗНЫЕ ключи, а повторное
    распарсивание того же снимка — одинаковые.
    """
    payload = f"{username}|{timestamp_raw}|{text}|{occurrence}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SeenKeys:
    """Ограниченное по памяти множество виденных dom_key.

    deque(maxlen) отвечает за порядок и потолок памяти, set — за
    O(1)-проверку принадлежности. При переполнении старейшие ключи
    вытесняются из обоих.
    """

    def __init__(self, maxlen: int = 2000) -> None:
        self._maxlen = maxlen
        self._order: deque[str] = deque()
        self._set: set[str] = set()

    def seen(self, key: str) -> bool:
        return key in self._set

    def add(self, key: str) -> None:
        self._set.add(key)
        self._order.append(key)
        if len(self._set) > self._maxlen:
            self._set.discard(self._order.popleft())


def dedup_messages(parsed_items: list[dict], seen_keys: SeenKeys) -> list[ChatMessage]:
    """Из сырого списка {username, timestamp_raw, text} возвращает только
    НОВЫЕ ChatMessage и помечает их ключи как виденные.

    Повтор одинаковой тройки внутри одного снимка различается номером
    повтора (occurrence) — это легитимное повторное сообщение, а не
    дубль парсинга.
    """
    occurrence: dict[tuple, int] = {}
    new_messages: list[ChatMessage] = []
    for item in parsed_items:
        username = item["username"]
        timestamp_raw = item["timestamp_raw"]
        text = item["text"]
        triple = (username, timestamp_raw, text)
        occurrence[triple] = occurrence.get(triple, 0) + 1
        dom_key = build_dom_key(username, timestamp_raw, text, occurrence[triple])
        if seen_keys.seen(dom_key):
            continue
        seen_keys.add(dom_key)
        new_messages.append(
            ChatMessage(
                username=username,
                text=text,
                timestamp=datetime.now(timezone.utc),
                dom_key=dom_key,
            )
        )
    return new_messages


class PlaywrightChatClient:
    """Реальная реализация ChatClient поверх Playwright (async API).

    poll_new_messages: парсинг DOM -> дедуп по dom_key -> только новые.
    send_message: клик в поле ввода, «печать» по словам с задержкой из
    typing_chars_per_second + джиттер, отправка по Enter. Никаких
    кулдаунов после отправки.
    """

    def __init__(
        self,
        page,
        typing_chars_per_second: float = 12.0,
        typing_jitter: float = 0.3,
        message_selector: str = DEFAULT_MESSAGE_SELECTOR,
        username_selector: str = DEFAULT_USERNAME_SELECTOR,
        timestamp_selector: str = DEFAULT_TIMESTAMP_SELECTOR,
        text_selector: str = DEFAULT_TEXT_SELECTOR,
        input_selector: str = DEFAULT_INPUT_SELECTOR,
        send_selector: str | None = DEFAULT_SEND_SELECTOR,
        seen_keys_maxlen: int = 2000,
    ) -> None:
        self.page = page
        self.typing_chars_per_second = typing_chars_per_second
        self.typing_jitter = typing_jitter
        self.message_selector = message_selector
        self.username_selector = username_selector
        self.timestamp_selector = timestamp_selector
        self.text_selector = text_selector
        self.input_selector = input_selector
        self.send_selector = send_selector
        self._seen_keys = SeenKeys(maxlen=seen_keys_maxlen)

    async def poll_new_messages(self) -> list[ChatMessage]:
        try:
            parsed = await asyncio.wait_for(self._parse_dom(), timeout=PARSE_TIMEOUT_SECONDS)
        except Exception as err:  # noqa: BLE001 — парсинг не должен ронять цикл
            logger.warning("chat DOM parse failed/timed out, skipping poll: %s", err)
            return []
        return dedup_messages(parsed, self._seen_keys)

    async def _parse_dom(self) -> list[dict]:
        elements = await self.page.query_selector_all(self.message_selector)
        parsed: list[dict] = []
        for element in elements:
            username = await self._read_username(element)
            timestamp = await self._read_text(element, self.timestamp_selector)
            text = await self._read_text(element, self.text_selector)
            if username and text:
                parsed.append({"username": username, "timestamp_raw": timestamp, "text": text})
        return parsed

    async def _read_username(self, element) -> str:
        """Ник из .channel-message__content__title минус время.

        В DOM ник — текстовый узел внутри того же span, где лежит
        .channel-message__time: text_content() даёт «02:22\nНик»,
        поэтому время вырезаем из заголовка.
        """
        title = await element.query_selector(self.username_selector)
        if title is None:
            return ""
        full = (await title.text_content() or "").strip()
        time = await self._read_text(element, self.timestamp_selector)
        if time:
            full = full.replace(time, "", 1)
        return full.strip()

    @staticmethod
    async def _read_text(element, selector: str) -> str:
        node = await element.query_selector(selector)
        if node is None:
            return ""
        content = await node.text_content()
        return (content or "").strip()

    async def send_message(self, text: str) -> None:
        await self.page.click(self.input_selector)
        await self._type_with_delay(text)
        if self.send_selector:
            await self.page.click(self.send_selector)
        else:
            await self.page.keyboard.press("Enter")

    async def _type_with_delay(self, text: str) -> None:
        words = [word for word in text.split(" ") if word]
        for index, word in enumerate(words):
            delay = self._delay_for_unit(len(word))
            if delay > 0:
                await asyncio.sleep(delay)
            await self.page.keyboard.type(word)
            if index < len(words) - 1:
                await self.page.keyboard.type(" ")

    def _delay_for_unit(self, unit_chars: int) -> float:
        """Пауза перед «печатью» слова: средняя скорость стремится к
        typing_chars_per_second, джиттер в пределах typing_jitter."""
        base = unit_chars / self.typing_chars_per_second
        jitter = self.typing_jitter * random.uniform(-1.0, 1.0)
        return max(0.0, base * (1.0 + jitter))
