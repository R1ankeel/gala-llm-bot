import asyncio

from chat_io.chat_client import (
    PlaywrightChatClient,
    build_dom_key,
    dedup_messages,
    SeenKeys,
)
from chat_io.fake_chat_client import FakeChatClient
from tests.mocks.sample_dom_snapshots import (
    SNAPSHOT_INCREMENTAL,
    SNAPSHOT_LEGIT_REPEAT,
    SNAPSHOT_MULTI_USER,
    SNAPSHOT_ONE,
)


class FakeElement:
    def __init__(self, children=None, text=""):
        self.children = children or {}
        self.text = text

    async def query_selector(self, selector):
        return self.children.get(selector)

    async def text_content(self):
        return self.text


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    async def type(self, text):
        self.page.typed.append(text)

    async def press(self, key):
        self.page.keys_pressed.append(key)


class FakePage:
    def __init__(self, snapshot):
        self.elements = [self._element_from_dict(d) for d in snapshot]
        self.clicks = []
        self.typed = []
        self.keys_pressed = []
        self.keyboard = FakeKeyboard(self)

    def _element_from_dict(self, d):
        return FakeElement(
            children={
                ".channel-message__content__title": FakeElement(text=d["username"]),
                ".channel-message__time": FakeElement(text=d["timestamp_raw"]),
                ".channel-message__content__text": FakeElement(text=d["text"]),
            }
        )

    async def query_selector_all(self, selector):
        return self.elements

    async def click(self, selector):
        self.clicks.append(selector)

    def set_snapshot(self, snapshot):
        self.elements = [self._element_from_dict(d) for d in snapshot]


# ---------- build_dom_key: чистая функция ----------


def test_build_dom_key_is_deterministic():
    key1 = build_dom_key("Вася", "21:05", "Анька, привет", 1)
    key2 = build_dom_key("Вася", "21:05", "Анька, привет", 1)
    assert key1 == key2


def test_build_dom_key_differs_on_text_and_timestamp():
    base = build_dom_key("Вася", "21:05", "Анька, привет", 1)
    assert base != build_dom_key("Вася", "21:06", "Анька, привет", 1)
    assert base != build_dom_key("Вася", "21:05", "Анька, пока", 1)
    assert base != build_dom_key("Пётр", "21:05", "Анька, привет", 1)


def test_build_dom_key_differs_on_occurrence():
    first = build_dom_key("Вася", "21:05", "Анька, привет", 1)
    second = build_dom_key("Вася", "21:05", "Анька, привет", 2)
    assert first != second


# ---------- дедуп через чистую dedup_messages ----------


def test_dedup_legit_repeat_both_new():
    seen = SeenKeys(maxlen=100)
    messages = dedup_messages(SNAPSHOT_LEGIT_REPEAT, seen)
    assert [m.text for m in messages] == ["Анька, привет", "Анька, привет"]


def test_dedup_same_snapshot_twice_second_empty():
    seen = SeenKeys(maxlen=100)
    first = dedup_messages(SNAPSHOT_MULTI_USER, seen)
    second = dedup_messages(SNAPSHOT_MULTI_USER, seen)
    assert len(first) == 3
    assert second == []


def test_dedup_incremental_returns_only_new():
    seen = SeenKeys(maxlen=100)
    first = dedup_messages(SNAPSHOT_ONE, seen)
    second = dedup_messages(SNAPSHOT_INCREMENTAL, seen)
    assert [m.text for m in first] == ["Анька, привет"]
    assert [m.text for m in second] == ["Анька, ты тут?", "ау"]


# ---------- PlaywrightChatClient через FakePage ----------


def test_poll_new_messages_via_fake_page():
    async def run():
        page = FakePage(SNAPSHOT_MULTI_USER)
        client = PlaywrightChatClient(page, typing_chars_per_second=12.0, typing_jitter=0.3)
        first = await client.poll_new_messages()
        second = await client.poll_new_messages()
        return first, second

    first, second = asyncio.run(run())
    assert len(first) == 3
    assert first[1].username == "Пётр"
    assert first[1].text == "Анька, как дела"
    assert second == []


def test_poll_incremental_via_fake_page():
    async def run():
        page = FakePage(SNAPSHOT_ONE)
        client = PlaywrightChatClient(page, typing_chars_per_second=12.0, typing_jitter=0.3)
        first = await client.poll_new_messages()
        page.set_snapshot(SNAPSHOT_INCREMENTAL)
        second = await client.poll_new_messages()
        return first, second

    first, second = asyncio.run(run())
    assert [m.text for m in first] == ["Анька, привет"]
    assert [m.text for m in second] == ["Анька, ты тут?", "ау"]


def test_read_username_strips_time_from_title():
    async def run():
        page = FakePage(SNAPSHOT_ONE)
        page.elements[0].children[".channel-message__content__title"].text = "21:05\nВася"
        client = PlaywrightChatClient(page, typing_chars_per_second=100.0, typing_jitter=0.0)
        return await client.poll_new_messages()

    messages = asyncio.run(run())
    assert len(messages) == 1
    assert messages[0].username == "Вася"


# ---------- send_message: клики и «печать» ----------
def test_send_message_clicks_input_then_send_button():
    async def run():
        page = FakePage([])
        client = PlaywrightChatClient(page, typing_chars_per_second=100.0, typing_jitter=0.0)
        await client.send_message("Вася, ну ты даёшь")
        return page

    page = asyncio.run(run())
    assert page.clicks == [
        ".channel-new-message__text-field__input",
        "#channel-new-message__send-button",
    ]
    assert page.typed == ["Вася,", " ", "ну", " ", "ты", " ", "даёшь"]


def test_send_message_presses_enter_when_no_send_selector():
    async def run():
        page = FakePage([])
        client = PlaywrightChatClient(
            page,
            typing_chars_per_second=100.0,
            typing_jitter=0.0,
            send_selector=None,
        )
        await client.send_message("Вася, ну ты даёшь")
        return page

    page = asyncio.run(run())
    assert page.clicks == [".channel-new-message__text-field__input"]
    assert page.keys_pressed == ["Enter"]


def test_delay_for_unit_is_within_jitter_bounds():
    page = FakePage([])
    client = PlaywrightChatClient(page, typing_chars_per_second=10.0, typing_jitter=0.3)
    import random as random_module

    original = random_module.uniform
    try:
        values = iter([1.0, -1.0, 0.0])
        random_module.uniform = lambda a, b: next(values)
        assert client._delay_for_unit(10) == 10 / 10.0 * (1 + 0.3)
        assert client._delay_for_unit(10) == 10 / 10.0 * (1 - 0.3)
        assert client._delay_for_unit(10) == 10 / 10.0 * (1 + 0.0)
    finally:
        random_module.uniform = original


# ---------- FakeChatClient: протокол для тестов main/route ----------


def _msg(username, text):
    from datetime import datetime, timezone

    from chat_io.chat_client import build_dom_key

    return type(
        "M",
        (),
        {
            "username": username,
            "text": text,
            "timestamp": datetime.now(timezone.utc),
            "dom_key": build_dom_key(username, "21:00", text, 0),
        },
    )()


def test_fake_chat_client_serves_batches_and_records_sent():
    async def run():
        client = FakeChatClient(
            [
                [_msg("Вася", "Анька, привет")],
                [_msg("Пётр", "Анька, как дела")],
            ]
        )
        first = await client.poll_new_messages()
        second = await client.poll_new_messages()
        third = await client.poll_new_messages()
        await client.send_message("Вася, привет")
        return first, second, third, client.sent_messages

    first, second, third, sent = asyncio.run(run())
    assert [m.text for m in first] == ["Анька, привет"]
    assert [m.text for m in second] == ["Анька, как дела"]
    assert third == []
    assert sent == ["Вася, привет"]
