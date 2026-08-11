# Архитектура

Проект — чат-бот-персонаж. На этом этапе реализованы: карточка
персонажа, транспорт к LLM, многослойный промпт, история диалога,
guard от «ассистентских» задач, веб-поиск фактов/культуры с
уклонением от погоды и науки, расписание, SQLite-память о
собеседниках, отношения с собеседником, и две точки входа в CLI.

## Поток данных (одна реплика)

```
пользователь
    │
    ▼
cli.py (--to/--msg или REPL)
    │  classify_task_request(msg)          # Этап 3, приоритет №1
    │  └─ не сработал? ──► classify_query(msg)   # Этап 4
    │        ├─ search  ──► SearchClient.search ──► format_search_context
    │        └─ deflect ──► (без поиска)
    ▼
память: log_message → apply_realtime_updates → (экстракция фактов)   # Этап 6
    │  (падение цепочки памяти не роняет диалог)
    ▼
отношения: count_message → раз в N сообщений LLM-оценка → apply_delta   # Этап 7
    │  (пишется в relationship; падение оценки не роняет диалог)
    ▼
PromptBuilder.build(nick, message, guard_category?/deflect_category?/search_context?)
    │  запрашивает слои у провайдеров
    ▼
state_provider (CompositeStateProvider: ScheduleProvider + RelationshipProvider)
  / memory_provider (FactsMemoryProvider) / history
    │
    ▼
system_prompt (identity → guard/deflect/search → state → memory → history + инструкция)
    │
    ▼
LLMClient.generate(system_prompt, [user message])
    │
    ├─ looks_like_compliance / looks_like_hallucinated_fact
    │  └─ сработало? → canned-ответ (pick_refusal_line / pick_deflect_line)
    ▼
response_formatter.format_reply(raw, nick)  →  "Ник, реплика"
    │
    ▼
печать; в REPL ответ добавляется в историю (role="assistant")
```

Подробности поискового флоу — в `docs/search.md`, флоу отказа — в
`docs/task_guard.md`, флоу памяти — в `docs/memory.md`, отношения — в
`docs/relationship.md`.

## Компоненты

| Модуль | Ответственность |
|---|---|
| `core/llm_client.py` | Транспорт к Ollama: `/api/chat`, ретраи на сетевые ошибки и 5xx/429, понятные `LLMError`. Не знает о персонажах. |
| `core/config.py` | Загрузка `.env` (Ollama URL, модель, температура, бюджет промпта). Критичные поля без дефолта → явная ошибка. |
| `core/layers.py` | Протоколы `StateProvider` и `MemoryProvider` + заглушки. Реальные реализации (Этапы 5–7) подключаются заменой одного аргумента конструктора. |
| `core/schedule_provider.py` | Реальный `StateProvider` (Этап 5): «чем занят» по времени суток из `config/schedule.yaml`. Валидация конфига при старте, время от UTC + сдвиг из конфига. |
| `core/state/composite_state_provider.py` | Объединение нескольких `StateProvider` в один (расписание + отношения), провайдеры тестируются и порознь, и вместе (Этап 7). |
| `core/relationship/levels.py` | Единственное место описания шкалы уровней 0–9 и их названий (Этап 7). |
| `core/relationship/store.py` | SQLite `relationship` + `relationship_log` на том же conn, что у памяти; `apply_delta` с прогрессом и границами (Этап 7). |
| `core/relationship/evaluator.py` | Раз в N сообщений LLM-оценка тона (только сообщения боту), клампинг дельты, фолбэки (Этап 7). |
| `core/relationship/relationship_provider.py` | Реальный `StateProvider`: словесная инструкция по тону, нейтраль = `None`, никаких чисел в промпте (Этап 7). |
| `core/dialogue_history.py` | `DialogueHistory` — in-memory история одного пользователя, обрезается по `max_turns`. |
| `core/prompt_builder.py` | Многослойный сборщик с бюджетом и двумя разными порядками (рендер / отбрасывание). |
| `core/task_guard.py` | Классификатор «ассистентских» задач + пост-валидатор + canned-отказы (Этап 3). |
| `core/search_classifier.py` | Классификатор поисковых запросов: `search`/`deflect`/`none` (Этап 4). |
| `core/search_client.py` | Обёртка над DDGS: ошибки сети → `[]`, URL не идёт дальше логов. |
| `core/search_formatter.py` | Сжатая сводка фактов для search_context (без URL, обрезка). |
| `core/search_guard.py` | Инструкция-уклонение + пост-валидатор галлюцинаций + canned-уклонение (Этап 4). |
| `core/memory/store.py` | SQLite-хранилище: `global_chat`, `user_profile`, `user_facts` (Этап 6). |
| `core/memory/realtime_profile.py` | Regex-паттерны «меня зовут X / мне N / работаю X» — профиль на лету (Этап 6). |
| `core/memory/profile_safety.py` | Проверка значений профиля перед записью (инъекции в промпт) (Этап 6). |
| `core/memory/gender_resolver.py` | Пол: явный из профиля → эвристика по нику (Этап 6). |
| `core/memory/facts_extractor.py` | Пакетная LLM-экстракция фактов из накопленных сообщений (Этап 6). |
| `core/memory/memory_provider.py` | Реальный `MemoryProvider`: рендер «что знаю о собеседнике» (Этап 6). |
| `core/response_formatter.py` | Страховочная зачистка сырого ответа и вставка ровно одного ника. |
| `character/character.yaml` | Карточка персонажа: голос, границы, отказы, уклонения, few-shot. |

## Порядок внедрения будущих этапов

- Этап 5 (расписание) — реализован: `ScheduleProvider` подставлен
  вместо `StubStateProvider` в `cli.py`. Заглушка осталась в
  `core/layers.py` нетронутой для юнит-тестов.
- Этап 6 (память о фактах) — реализован: `FactsMemoryProvider`
  (поверх SQLite) подставлен вместо `StubMemoryProvider` в `cli.py`.
  Персистентная история (`global_chat`) — побочный продукт этапа.
- Этап 7 (отношения) — реализован: `CompositeStateProvider`
  (ScheduleProvider + RelationshipProvider) подставлен вместо
  одиночного `ScheduleProvider` в `cli.py`. Оценка тона — отдельное
  звено `RelationshipEvaluator` на write-пути, клампинг и фолбэки не
  роняют диалог.

`PromptBuilder` при этом не меняется — он зависит только от
интерфейсов из `core/layers.py`.
