# Реальный чат (Этап 8)

Бот подключается к чату galaxy.mobstudio.ru через Playwright: читает DOM,
строго адресуется по «{ник}, …», склеивает серию коротких сообщений в
одну задачу (дебаунс) и отвечает с имитацией набора. Реальные LLM-цепочки
(память, отношения, промпт) не менялись — вызываются через общий пайплайн
`core/pipeline.py`.

## Точки входа

- `python main.py` — прод: открывает браузер (headless=False),
  логинишься вручную, Enter — и цикл опроса запущен.
- `python main.py --fake` — dev-режим: `FakeChatClient` без браузера,
  для смоуков.
- `python cli.py --to Ник --msg ...` / `--repl` — по-прежнему ручная
  отладка одной реплики без браузера.

Оба входа используют один пайплайн ответа из `core/pipeline.py`:
`handle_addressed_message(...)`. Логика cli.py не дублируется.

## Строгая адресация

`core/route.py`. Ответ только на «{ник_бота}, …» в начале сообщения
(регистронезависимо, 0–1 пробел после запятой):

| Сообщение | Действие |
|---|---|
| `Гера, привет` | addressed → дебаунс → ответ |
| `Гере привет` (без запятой) | log_only |
| `привет, Гера` (ник не в начале) | log_only |
| `Гера,` без текста | log_only |
| `Гера,, привет` (пунктуация после запятой) | log_only |

Словоформы/склонения ника — будущий этап, сейчас никакие `геру/гере/гера`
не матчатся как адрес. `bot_username` в `config/chat_config.yaml` ДОЛЖЕН
совпадать с `name` в `character/character.yaml` (на это наложена проверка
при старте): фильтр «сообщения боту» в отношениях завязан на имя персонажа.

## Дебаунс

`core/debounce_buffer.py`. Буфер на пользователя: сообщение добавляется в
`parts`, флашится одной задачей (parts через пробел) когда:

- тишина ≥ `debounce_seconds` с последнего сообщения, ИЛИ
- от первого сообщения прошло ≥ `debounce_max_wait_seconds` (жёсткий потолок).

Тик-based: время подставляется в `add/pop_ready` снаружи — тесты без
реальных ожиданий. Только addressed-сообщения попадают в буфер; log_only
сразу уходят в `global_chat` без обработки.

## Чтение чата (Playwright)

`chat_io/chat_client.py`. Каждый опрос:

1. `poll_new_messages()` вытаскивает строки чата из DOM (selectors в
   `_parse_chat_rows`, при отсутствии элементов — `[]`).
2. `build_dom_key` делает ключ строки (sha256 от username|timestamp|text
   + счётчик повтора), `SeenKeys` (deque+set, 2000 последних) отсеивает
   уже виденное, легитимный повтор (та же строка, новый счётчик повтора)
   не схлопывается.

## Отправка ответа

`send_message(reply)`: печатает по словам в поле ввода с паузой

```
длина_слова / typing_chars_per_second * (1 + uniform(-jitter, jitter))
```

и жмёт Enter. Кулдаунов после отправки нет.

## Цикл в main.py

1. `poll_new_messages()` → `should_ignore_message` (в т.ч. свои же
   сообщения) → `log_message` в `global_chat`.
2. addressed: `apply_realtime_updates` + `debounce.add`.
3. раз в `extract_every_n_messages` — цикл экстракции фактов.
4. `debounce.pop_ready` → `handle_addressed_message(..., log_to_memory=False)`
   (память о реплике уже легла на шаге 1) → `send_message` → ответ тоже
   логируется в `global_chat`.
5. сон `poll_interval_ms`.

log_only-сообщения только логируются; в LLM не идут.

## Конфиг

`config/chat_config.yaml`:

```yaml
bot_username: "Гера"        # = character.name, строгая адресация
chat_url: "https://galaxy.mobstudio.ru"
debounce_seconds: 3.5       # тишина → флаш
debounce_max_wait_seconds: 15
poll_interval_ms: 2000
typing_chars_per_second: 12
typing_jitter: 0.3
```

## Известные ограничения

- `FactsExtractor` не фильтрует сообщения самого бота (логика памяти не
  трогалась по ТЗ): адресованные боту ответы попадают в пакет экстракции
  как «факты о боте». Безвредно, но запомнится.
- Пакет назван `chat_io/`, а не `io/` из ТЗ: top-level пакет `io` в Python
  не импортируется (конфликт со stdlib, уже лежащей в `sys.modules`).

## Установка

```bash
pip install playwright
python -m playwright install chromium
```

## Тесты

- `tests/test_route.py` — адресация (17 случаев).
- `tests/test_debounce_buffer.py` — склейка/флаши (5 случаев).
- `tests/test_chat_client_dedup.py` — build_dom_key, дедуп, типинг (11 случаев).
- `tests/mocks/sample_dom_snapshots.py` — снимки DOM для мануальных прогонов.

Смоук (`python main.py --fake`-цикл): серия коротких addressed-сообщений
→ ровно один вызов пайплайна с объединённым текстом; log_only-сообщения
лежат в `global_chat` без ответа; свои сообщения бот игнорирует.
