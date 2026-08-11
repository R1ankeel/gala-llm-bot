"""Синтетические «снимки» DOM-чата: списки распарсенных сообщений
{username, timestamp_raw, text} — как если бы их вернул парсинг DOM
PlaywrightChatClient. Для тестов build_dom_key()/дедупа без реального
браузера.
"""

SNAPSHOT_ONE = [
    {"username": "Вася", "timestamp_raw": "21:05", "text": "Анька, привет"},
]

# Одинаковый текст от одного юзера дважды подряд (легитимный повтор,
# не дубль парсинга) — оба должны попасть в результат как РАЗНЫЕ
# сообщения: дедуп различает их через порядковый номер повтора.
SNAPSHOT_LEGIT_REPEAT = [
    {"username": "Вася", "timestamp_raw": "21:05", "text": "Анька, привет"},
    {"username": "Вася", "timestamp_raw": "21:05", "text": "Анька, привет"},
]

SNAPSHOT_MULTI_USER = [
    {"username": "Вася", "timestamp_raw": "21:05", "text": "привет всем"},
    {"username": "Пётр", "timestamp_raw": "21:06", "text": "Анька, как дела"},
    {"username": "Пётр", "timestamp_raw": "21:06", "text": "ты тут?"},
]

# Инкрементальный случай: поверх SNAPSHOT_ONE приходят ещё два
# сообщения (для второго вызова poll_new_messages).
SNAPSHOT_INCREMENTAL = [
    {"username": "Вася", "timestamp_raw": "21:05", "text": "Анька, привет"},
    {"username": "Пётр", "timestamp_raw": "21:06", "text": "Анька, ты тут?"},
    {"username": "Пётр", "timestamp_raw": "21:06", "text": "ау"},
]
