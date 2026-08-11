"""Тестовая реализация ChatClient: без браузера, для тестов и dev-режима."""

import asyncio

from chat_io.chat_client import ChatMessage


class FakeChatClient:
    """Реализация Protocol для тестов и main.py в dev-режиме без браузера.

    Конструктор принимает заранее заданную очередь пачек ChatMessage:
    poll_new_messages() отдаёт по одной пачке за вызов (симулирует
    поступление сообщений во времени). send_message() просто складывает
    отправленные тексты в self.sent_messages.
    """

    def __init__(self, message_batches: list[list[ChatMessage]] | None = None) -> None:
        self._batches: list[list[ChatMessage]] = list(message_batches or [])
        self._batch_index = 0
        self.sent_messages: list[str] = []
        self.typing_delay_seconds: float = 0.0

    async def poll_new_messages(self) -> list[ChatMessage]:
        if self._batch_index >= len(self._batches):
            return []
        batch = self._batches[self._batch_index]
        self._batch_index += 1
        return batch

    async def send_message(self, text: str) -> None:
        if self.typing_delay_seconds > 0:
            await asyncio.sleep(self.typing_delay_seconds)
        self.sent_messages.append(text)

    def add_batch(self, batch: list[ChatMessage]) -> None:
        self._batches.append(batch)
