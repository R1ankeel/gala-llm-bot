# gala-reworked

Чат-бот-персонаж на Python с локальной LLM (Ollama). Бот отвечает
в характере персонажа, заданного карточкой `character/character.yaml`,
и умеет вести многоходовый диалог в рамках сессии (in-memory).

## Требования

- Python 3.10+
- Ollama с загруженной моделью (см. `MODEL_NAME` в `.env`)

## Установка

```bash
pip install -r requirements.txt        # зависимости
pip install -r requirements-dev.txt    # + pytest для тестов

copy .env.example .env                 # Windows
# и задать MODEL_NAME под свою установленную модель
```

## Использование

Однострочный режим (одна реплика, без истории):

```bash
python cli.py --to Вася --msg "Привет как дела"
```

REPL-режим (диалог с историей в памяти сессии):

```bash
python cli.py --repl --nick Вася
```

Пустая строка (или Ctrl+C / Ctrl+D) выходит из REPL.

## Тесты

```bash
python -m pytest tests -q
```

## Структура

```
character/character.yaml   — карточка персонажа (голос, границы, отказы)
core/config.py             — загрузка .env
core/llm_client.py         — транспорт к Ollama (retries, понятные ошибки)
core/layers.py             — интерфейсы-протоколы слоёв и их заглушки
core/dialogue_history.py   — контейнер истории диалога (per user)
core/prompt_builder.py     — многослойный сборщик промпта с бюджетом
core/response_formatter.py — постобработка реплики, вставка ника
cli.py                     — точка входа (однострочный / REPL)
tests/                     — юнит-тесты
docs/                      — документация
```

## Документация

- `docs/architecture.md` — компоненты и потоки данных
- `docs/prompt_builder.md` — слои, порядок рендера, порядок отбрасывания, бюджет
- `docs/character_card.md` — схема character.yaml

## Планируемые этапы

- Этап 1 — рабочий скелет без интеграции с чатом
- Этап 2 — многослойный промпт (PromptBuilder) + REPL с историей
- Этапы 3–8 — guard, память, расписание, отношения, чат-интеграция
