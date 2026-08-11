# PromptBuilder: слои, бюджет, порядки

`core/prompt_builder.py` собирает единый system-промпт из слоёв.
Главное различие, которое нельзя путать:

- **Порядок рендера** — фиксирован всегда и не зависит от бюджета:
  `identity → task_guard → deflect → search_context → state → memory →
  history`. Плюс финальная инструкция с текущим сообщением и запретом
  на «Ник,» в начале ответа.
- **Порядок отбрасывания** — отдельная сущность (поле `priority`):
  при нехватке места слои убираются **целиком** в порядке
  `history → memory → state → search_context`.

Слой отбрасывается или есть целиком — «отрезания по весам внутри
блока» не существует.

## Приоритеты по умолчанию

| Слой | priority | droppable |
|---|---|---|
| identity | 100 | нет |
| task_guard | 95 | нет |
| deflect | 94 | нет |
| search_context | 90 | да |
| state | 30 | да |
| memory | 20 | да |
| history | 10 | да |

Чем меньше `priority` — тем раньше слой убирается.

`task_guard` и `deflect` — guard-классы задач: они не должны вымываться
бюджетом, иначе бот начнёт выдумывать погоду при большом контексте.
`search_context` важен, но не критичен для безопасности — при очень
малом бюджете лучше короткий ответ без справки, чем сломанный промпт.
При сбросе любого droppable-слоя в лог пишется `warning` с его именем.

## Поведение при переполнении бюджета

1. Слои с `content is None` (провайдер вернул «нечего показать»)
   исключаются ещё до подсчёта бюджета.
2. Пока суммарная длина > `budget_chars`: удаляется droppable-слой
   с наименьшим `priority`. При каждом сбросе пишется `warning`
   с именем слоя.
3. Если droppable-слоёв не осталось (остался только identity),
   цикл останавливается — даже если identity один больше бюджета.
   В лог пишется `warning` (не исключение).
4. Оставшиеся слои собираются строго в порядке рендера
   `identity → task_guard → deflect → search_context → state →
   memory → history`.
5. После слоёв добавляется финальная инструкция (никак не учитывается
   в бюджете).

Активен максимум один из `{task_guard, deflect, search_context}` — они
взаимоисключающие по построению пайплайна в cli.py. `PromptBuilder`
сам инвариант не проверяет: `build()` рендерит любую переданную
комбинацию.

## Подключение реальных провайдеров

Реальные реализации должны просто реализовать протоколы из
`core/layers.py`:

```python
class FactsMemoryProvider:
    def render(self, addressee_nick: str, current_message: str) -> str | None:
        ...
```

Подстановка — одна строка в месте конструирования `PromptBuilder`:

```python
builder = PromptBuilder(
    character,
    ScheduleProvider(...),      # вместо StubStateProvider
    FactsMemoryProvider(...),   # вместо StubMemoryProvider
    budget_chars=6000,
)
```

Сам `PromptBuilder` не меняется.
