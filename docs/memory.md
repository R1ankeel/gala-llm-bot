# Память (Этап 6)

Бот запоминает собеседников в SQLite и подмешивает память в промпт.
Память не должна ронять диалог: любой сбой в её цепочке логируется и
обходится.

## Схема БД

Файл БД задаётся `MEMORY_DB_PATH` в `.env` (по умолчанию
`data/memory.db`), создаётся при первом запуске. Таблицы:

- `global_chat(id, username, text, created_at, processed)` — все
  входящие сообщения. `processed=0` — ещё не обработаны экстрактором.
- `user_profile(username PK, display_name, real_name, gender,
  gender_source, age, job, city, updated_at)` — профиль собеседника.
  Значение `age` хранится как `INTEGER`, остальные — строки.
- `user_facts(id, username, fact, category, source, created_at)` —
  извлечённые факты. Категории: `fact`, `hobby`, `trait`.

## Поток обработки входящего сообщения

В `_run_memory_pipeline` (cli.py) на каждое сообщение:

1. `MemoryStore.log_message()` — сообщение в `global_chat`.
2. `apply_realtime_updates()` — regex-паттерны из
   `core/memory/realtime_profile.py` на лету обновляют профиль:
   `меня зовут X`, `мне N лет`, `я из X` / `живу в X`, `работаю X`,
   `я девушка/парень/...`. Паттерны ловят только факты о себе и не
   пишут «игнорируй инструкции»-подобные значения (см. безопасность).
3. Если `count_unprocessed() >= extract_every_n_messages` —
   `FactsExtractor.run_extraction_cycle()` (пакетная LLM-экстракция).

Никаких глобальных состояний: каждый вызов строит `MemoryRuntime`
вокруг переданного `MemoryStore`. В REPL рантайм создаётся один раз,
чтобы интервал экстракции не сбрасывался между репликами.

## LLM-экстракция фактов

`FactsExtractor` копит непрочитанные сообщения (не чаще, чем раз в
`min_interval_seconds`), группирует по отправителю, отбрасывает
сообщения, адресованные боту (по имени персонажа), и отдаёт пакет
LLM с просьбой вернуть JSON-список фактов о себе:

```json
[{"fact": "любит аниме", "category": "hobby"}]
```

Валидация кандидатов: длина факта 3–200 символов, категория из
допустимых, отбрасываются явно саркастичные (`ахах`, `лол`, `шутк`,
`/s`, смеющиеся эмодзи). Дубликаты не пишутся (нормализация по
регистру и `ё/е`). После цикла все сообщения помечаются `processed=1`.

Настройки — в `config/memory.yaml`:

- `extract_every_n_messages` — порог накопленных сообщений (30);
- `min_interval_seconds` — минимальный интервал между экстракциями (120);
- `max_facts_rendered` — сколько последних фактов попадает в промпт (3);
- `max_facts_stored_per_user` — лимит фактов на пользователя (50);
- `forbidden_value_markers` — значения-маркеры, которые не пишутся в профиль.

## Определение пола

`core/memory/gender_resolver.py`, порядок:

1. Явный `gender` из профиля (`gender_source=explicit`).
2. Эвристика по нику: первый словесный фрагмент (`Вася123` → `вася`),
   поиск в `common_male_names`/`common_female_names`, затем суффиксы
   фамилий (`Дмитриев` → male, `Дмитриева` → female).
3. Неизвестно → `(None, None)`.

Настройки — в `config/gender_heuristics.yaml`.

## Рендер памяти в промпт

`FactsMemoryProvider.render(nick, message)` собирает строку
«Ты знаешь об этом собеседнике: …» (имя, возраст, работа, город, пол
и до `max_facts_rendered` последних фактов) и возвращает `None`, если
ничего не известно. Строка попадает в промпт как memory-слой
(`priority` между state и user-историей, см. `docs/prompt_builder.md`).

## Безопасность значений профиля

`core/memory/profile_safety.py` — `is_safe_value(field, value)`:
пустые/длинные значения, `<`/`>`, и значения, содержащие маркеры из
`forbidden_value_markers` (`system`, `prompt`, `игнорируй` и т.п.),
в БД не записываются. Возраст валидируется как число от 1 до 120.

## Конфиг

```bash
# .env
MEMORY_DB_PATH=data/memory.db
```

## Тесты

- `tests/test_memory_store.py` — CRUD, дедупликация фактов, лимиты;
- `tests/test_realtime_profile.py` — regex-паттерны и безопасность;
- `tests/test_gender_resolver.py` — явный пол, эвристики, неизвестно;
- `tests/test_facts_extractor.py` — циклы, дедуп, шум, ошибки LLM;
- `tests/test_memory_provider.py` — рендер и интеграция с `run_once`.

Данные для мануальных прогонов экстрактора — в
`tests/fixtures/sample_chat_logs.yaml`, контролируемый LLM —
`tests/mocks/fake_llm_client.py`.
