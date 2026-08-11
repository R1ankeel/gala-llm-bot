"""Ручной прогон guard-кейсов через реальную LLM (и реальный поиск).

НЕ часть pytest CI — требует живую модель и сеть для search-кейсов.
Запуск:

    python scripts/eval_character.py [--limit N] [--budget N]

Прогоняет:
  - block-кейсы task_guard (Этап 3) — считает компромиссы на LLM-уровне;
  - search/deflect/task_guard-кейсы поискового набора (Этап 4) —
    считает % deflect-кейсов с галлюцинированными цифрами (fallback
    поймал) и % search-кейсов, где бот проболтался про интернет/URL.

Компромисс, пойманный фолбэком, всё равно сигнал, что промпт слабый.
Отчёт пишется в scripts/eval_report.txt.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.character_loader import load_character
from core.config import load_config
from core.layers import StubMemoryProvider
from core.llm_client import LLMClient, LLMError
from core.prompt_builder import PromptBuilder
from core.schedule_provider import ScheduleProvider
from core.search_classifier import classify_query
from core.search_client import SearchClient
from core.search_formatter import format_search_context
from core.search_guard import (
    looks_like_hallucinated_fact,
    pick_deflect_line,
)
from core.task_guard import classify_task_request, looks_like_compliance, pick_refusal_line

TASK_KEYWORDS_PATH = os.path.join(ROOT, "config", "task_guard_keywords.yaml")
SEARCH_KEYWORDS_PATH = os.path.join(ROOT, "config", "search_keywords.yaml")
TASK_CASES_PATH = os.path.join(ROOT, "tests", "fixtures", "task_guard_eval_cases.yaml")
SEARCH_CASES_PATH = os.path.join(ROOT, "tests", "fixtures", "search_eval_cases.yaml")
REPORT_PATH = os.path.join(ROOT, "scripts", "eval_report.txt")

_META_TALK = re.compile(
    r"(нашёл|нашла|в интернете|http[s]?://|ссылка|результат поиска)",
    re.IGNORECASE,
)


@dataclass
class CaseResult:
    kind: str
    message: str
    category: str
    guard_hit: str | None
    complied: bool
    fallback_applied: bool
    meta_talk: bool
    final_preview: str


def load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="0 = все кейсы")
    parser.add_argument("--budget", type=int, default=None, help="override бюджета промпта")
    args = parser.parse_args(argv)

    config = load_config()
    character = load_character(config.character_path)
    task_keywords = load_yaml(TASK_KEYWORDS_PATH)
    search_keywords = load_yaml(SEARCH_KEYWORDS_PATH)

    task_cases = [c for c in load_yaml(TASK_CASES_PATH)["cases"] if c["expected"] == "block"]
    search_cases = [c for c in load_yaml(SEARCH_CASES_PATH)["cases"] if c["action"] != "none"]

    client = LLMClient(config.ollama_base_url, config.model_name, think=config.llm_think)
    search_client = SearchClient()
    budget = args.budget or config.prompt_budget_chars
    builder = PromptBuilder(
        character,
        ScheduleProvider(os.path.join(ROOT, "config", "schedule.yaml")),
        StubMemoryProvider(),
        budget_chars=budget,
    )

    runs: list[tuple[str, str, str]] = []  # (kind, message, category)
    for case in task_cases:
        runs.append(("task", case["message"], case["category"]))
    for case in search_cases:
        runs.append(("search", case["message"], case["category"]))

    if args.limit > 0:
        runs = runs[: args.limit]

    results: list[CaseResult] = []
    for i, (kind, msg, category) in enumerate(runs, start=1):
        task_verdict = classify_task_request(msg, task_keywords)
        search_verdict = classify_query(msg, search_keywords)

        if task_verdict.triggered:
            system_prompt = builder.build("Тест", msg, guard_category=task_verdict.category)
        elif search_verdict.action == "search":
            ctx = format_search_context(search_client.search(msg))
            system_prompt = builder.build("Тест", msg, search_context=ctx)
        elif search_verdict.action == "deflect":
            system_prompt = builder.build("Тест", msg, deflect_category=search_verdict.category)
        else:
            system_prompt = builder.build("Тест", msg)

        try:
            raw = client.generate(
                system_prompt,
                [{"role": "user", "content": msg}],
                temperature=config.default_temperature,
                max_tokens=config.max_tokens,
            )
        except LLMError as err:
            print(f"[llm] кейс #{i} упал: {err}", file=sys.stderr)
            continue

        complied = False
        fallback = False
        if task_verdict.triggered and looks_like_compliance(raw):
            complied = True
            fallback = True
            raw = pick_refusal_line(character, task_verdict.category)
        elif search_verdict.action == "deflect" and looks_like_hallucinated_fact(
            raw, search_verdict.category
        ):
            complied = True
            fallback = True
            raw = pick_deflect_line(character, search_verdict.category)

        meta_talk = bool(_META_TALK.search(raw))
        results.append(
            CaseResult(
                kind=kind,
                message=msg,
                category=category,
                guard_hit=task_verdict.category if task_verdict.triggered else search_verdict.category,
                complied=complied,
                fallback_applied=fallback,
                meta_talk=meta_talk,
                final_preview=raw.strip().replace("\n", " ")[:120],
            )
        )
        print(f"[{i}/{len(runs)}] {msg}")
        print(
            f"    guard: {results[-1].guard_hit} | complied: {complied} "
            f"| fallback: {fallback} | meta: {meta_talk} | final: {results[-1].final_preview!r}"
        )

    print("\n=== Сводка ===")
    task = [r for r in results if r.kind == "task"]
    search = [r for r in results if r.kind == "search" and r.category in ("culture", "factual")]
    deflect = [r for r in results if r.kind == "search" and r.category in ("blocked_weather", "blocked_science")]
    if task:
        n, c = len(task), sum(1 for r in task if r.complied)
        print(f"task_guard: {c}/{n} компромиссов на LLM-уровне ({c / n * 100:.0f}%)")
    if deflect:
        n, h = len(deflect), sum(1 for r in deflect if r.complied)
        print(f"deflect: {h}/{n} кейсов с галлюцинированными цифрами ({h / n * 100:.0f}%)")
    if search:
        n, m = len(search), sum(1 for r in search if r.meta_talk)
        print(f"search: {m}/{n} кейсов с проболткой про интернет/URL ({m / n * 100:.0f}%)")

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(f"model: {config.model_name}\n")
        fh.write(f"cases: {len(results)}\n\n")
        for r in results:
            fh.write(
                f"{r.kind.upper()} | {r.message} | category={r.category} | guard={r.guard_hit} "
                f"| complied={r.complied} | fallback={r.fallback_applied} | meta={r.meta_talk} "
                f"| {r.final_preview}\n"
            )
    print(f"Отчёт: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
