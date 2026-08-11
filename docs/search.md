# Search Guard и веб-поиск (Этап 4)

Два новых поведения, оба защищены по схеме Этапа 3
(классификатор → инструкция в промпте → пост-валидатор):

1. **Поиск фактов/культуры**: бот ищет в DDGS то, чего не знает,
   и отвечает своим голосом — без «я нашла в интернете», без URL.
2. **Уклонение от погоды/науки**: бот НЕ изображает эксперта и не
   выдумывает цифры/факты — уклоняется в характере.

## Разделение зон ответственности

| Guard | Отвечает за | Пример |
|---|---|---|
| `task_guard` (Этап 3) | «сделай за меня работу» (код, задачи, тексты, глубокие академические объяснения) | «напиши код», «объясни подробно как работает двигатель» |
| `search_guard` (Этап 4) | «дай точный факт, который нельзя проверить в реальном времени / нельзя гарантировать точность» | погода, курс, результат матча, узкая наука |

**Приоритет:** task_guard всегда главнее. Если `classify_task_request`
сработал — поиск вообще не запускается, идёт обычный флоу отказа.
Поисковый классификатор проверяется только когда task_guard НЕ сработал.

«Почему идёт дождь» / «как формируется торнадо» пересекаются с
`deep_academic_explain` из Этапа 3 — это НЕ баг: task_guard ловит
большинство таких формулировок раньше, а `search_guard` — подстраховка
на случай, если формулировка прошла мимо.

## Пайплайн (cli.py)

```
classify_task_request(msg)
  ├─ triggered? ──► build(guard_category=...)  # поиск НЕ запускается
  └─ нет ──► classify_query(msg)
        ├─ search  ──► SearchClient.search → format_search_context
        │             ──► build(search_context=...)
        ├─ deflect ──► build(deflect_category=...)  # blocked_weather/blocked_science
        └─ none    ──► build(...)  # обычный флоу
raw = generate(prompt)
  ├─ task_guard triggered и looks_like_compliance(raw)     ──► pick_refusal_line
  ├─ deflect и looks_like_hallucinated_fact(raw, category) ──► pick_deflect_line
  └─ иначе raw без изменений
reply = format_reply(raw, nick)
```

На каждое сообщение активен максимум ОДИН из `{task_guard, deflect,
search_context}` — инвариант держит вызывающий код (cli.py).
`PromptBuilder.build` физически позволяет любую комбинацию и просто
рендерит то, что ему передали.

## Модули

| Модуль | Ответственность |
|---|---|
| `core/search_classifier.py` | `classify_query` → `SearchVerdict(action, category)`. Regex/подстроки без LLM. `blocked_*` → `deflect`, `factual`/`culture` → `search`, ничего → `none`. Паттерны в `config/search_keywords.yaml`. |
| `core/search_client.py` | Обёртка над DDGS. Таймаут 5 сек, любая ошибка → `[]`, исключения наружу не летят. URL хранится только для логов. |
| `core/search_formatter.py` | `format_search_context` — сжатая сводка фактов (не цитат), обрезка до `max_chars`, без URL. `None` при пустом результате. |
| `core/search_guard.py` | `build_deflect_instruction` (инструкция-уклонение), `looks_like_hallucinated_fact` (пост-валидатор), `pick_deflect_line` (canned-уклонение из `character.deflect_style`). |

## Как НЕ упоминается интернет

В `search_context`-слой вплетена жёсткая инструкция: «НЕ говори, что
искал(а) в интернете, и не давай URL — отвечай как будто просто
знаешь». URL сознательно не попадают в промпт вообще — в
`SearchResult.url` они живут только для логов/дебага. Снипеты не
цитируются дословно: они сжимаются и обрезаются, потому что модель
локальная и без своего copyright-фильтра.

## Оценка

`scripts/eval_character.py` прогоняет `search_eval_cases` через
реальную LLM и реальный поиск (это единственное место, где сеть
разрешена — в pytest только `FakeSearchClient`). Считает:

- % deflect-кейсов с галлюцинированными цифрами (пойманными фолбэком);
- % search-кейсов с проболткой про интернет/URL.
