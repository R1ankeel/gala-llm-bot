# gala-reworked

Чат-бот-персонаж на Python с локальной LLM (Ollama). Бот отвечает
в характере персонажа, заданного карточкой `character/character.yaml`,
знает, чем «занят» по расписанию (см. `config/schedule.yaml`), умеет
вести многоходовый диалог в рамках сессии (in-memory) и запоминает
собеседников (SQLite-память, см. `docs/memory.md`).

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

Бот отказывается от «ассистентских» задач (код, домашка, написание
текстов, глубокие академические объяснения) в характере персонажа —
через три рубежа защиты: regex-классификатор до генерации, guard-слой
в промпте и пост-валидатор с canned-ответом. Паттерны редактируются
в `config/task_guard_keywords.yaml`. Подробности — в `docs/task_guard.md`.

Бот умеет искать свежие факты/культуру через DDGS (песни, фильмы,
курсы, новости, результаты матчей) и отвечать своим голосом — без
URL и без «я нашла в интернете». Про погоду и узкую науку НЕ
изображает эксперта и не выдумывает цифры — уклоняется в характере
(поле `deflect_style` в `character.yaml`). Паттерны — в
`config/search_keywords.yaml`, подробности — в `docs/search.md`.

В промпт всегда попадает актуальное «чем занят прямо сейчас» из
`config/schedule.yaml` (state-слой): утро, работа, дорога домой,
ужин, отдых, сон. Время считается от UTC со сдвигом
`local_tz_offset_hours`. Подробности — в `docs/schedule.md`.

Бот запоминает собеседников в SQLite (`data/memory.db`): логирует
сообщения, на лету по regex выхватывает «меня зовут X, мне N,
работаю таксистом» в профиль, LLM-экстрактор вытаскивает факты из
накопленных сообщений, а память о собеседнике подмешивается в
промпт (имя, возраст, пол, факты). Пол угадывается по нику/профилю.
Паттерны — в `config/memory.yaml` и `config/gender_heuristics.yaml`,
подробности — в `docs/memory.md`.

## Оценка guard'а на живой модели

```bash
python scripts/eval_character.py [--limit N] [--budget N]
```

Прогоняет block-кейсы task_guard (Этап 3) и search/deflect-кейсы
(Этап 4) через реальную LLM (для search — реальный поиск DDGS) и
пишет сводку в `scripts/eval_report.txt`: сколько кейсов дали
компромисс на LLM-уровне и % deflect-кейсов с галлюцинированными
цифрами. Требует живую модель и сеть — не часть CI.

## Тесты

```bash
python -m pytest tests -q
```

## Структура

```
character/character.yaml          — карточка персонажа (голос, границы, отказы, уклонения)
config/task_guard_keywords.yaml   — паттерны task_guard (единственное место их правки)
config/search_keywords.yaml       — паттерны поискового классификатора (Этап 4)
config/schedule.yaml              — расписание: чем занят по времени суток (Этап 5)
config/memory.yaml                — настройки памяти: экстракция, безопасность значений (Этап 6)
config/gender_heuristics.yaml     — эвристики пола по нику (Этап 6)
core/config.py                    — загрузка .env
core/llm_client.py                — транспорт к Ollama (retries, понятные ошибки)
core/layers.py                    — интерфейсы-протоколы слоёв и их заглушки
core/dialogue_history.py          — контейнер истории диалога (per user)
core/prompt_builder.py            — многослойный сборщик промпта с бюджетом
core/schedule_provider.py         — реальный StateProvider: занятие по времени суток (Этап 5)
core/task_guard.py                — классификатор + пост-валидатор + canned-отказы (Этап 3)
core/search_classifier.py         — поисковый классификатор search/deflect/none (Этап 4)
core/search_client.py             — обёртка над DDGS (ошибки сети → [])
core/search_formatter.py          — сжатая сводка фактов для search_context
core/search_guard.py              — уклонение от погоды/науки + пост-валидатор (Этап 4)
core/memory/                      — SQLite-память: store, realtime-профиль, gender, факты (Этап 6)
core/response_formatter.py        — постобработка реплики, вставка ника
cli.py                            — точка входа (однострочный / REPL)
scripts/eval_character.py         — ручной прогон guard-кейсов через LLM (+ DDGS)
tests/                            — юнит-тесты (+ fixtures и mock SearchClient/LLM)
docs/                             — документация
```

## Документация

- `docs/architecture.md` — компоненты и потоки данных
- `docs/prompt_builder.md` — слои, порядок рендера, порядок отбрасывания, бюджет
- `docs/character_card.md` — схема character.yaml
- `docs/task_guard.md` — три рубежа защиты, категории, эвристики, оценка
- `docs/search.md` — поиск фактов/культуры, уклонение от погоды/науки, приоритет над task_guard
- `docs/schedule.md` — расписание (ScheduleProvider): конфиг, семантика слотов, валидация
- `docs/memory.md` — память: SQLite-схема, realtime-профиль, gender-резолвер, LLM-факты, MemoryProvider

## Планируемые этапы

- Этап 1 — рабочий скелет без интеграции с чатом
- Этап 2 — многослойный промпт (PromptBuilder) + REPL с историей
- Этап 3 — guard от «ассистентских» задач
- Этап 4 — веб-поиск фактов/культуры + уклонение от погоды и науки
- Этап 5 — расписание (чем занят по времени суток)
- Этап 6 — память (SQLite, realtime-профиль, пол, LLM-факты)
- Этап 7 — отношения (тон общения)
- Этап 8 — чат-интеграция
