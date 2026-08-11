import os

import pytest
import yaml

from core.search_classifier import classify_query

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYWORDS_PATH = os.path.join(ROOT, "config", "search_keywords.yaml")
CASES_PATH = os.path.join(ROOT, "tests", "fixtures", "search_eval_cases.yaml")

with open(KEYWORDS_PATH, "r", encoding="utf-8") as fh:
    KEYWORDS = yaml.safe_load(fh)
with open(CASES_PATH, "r", encoding="utf-8") as fh:
    CASES = yaml.safe_load(fh)["cases"]


@pytest.mark.parametrize("case", CASES)
def test_classify_query_matches_fixtures(case):
    verdict = classify_query(case["message"], KEYWORDS)

    if case["action"] in ("search", "deflect", "none"):
        assert verdict.action == case["action"], case["message"]
        if verdict.action != "none":
            assert verdict.category == case["category"], case["message"]
    else:
        assert verdict.action != "search", case["message"]


def test_fixtures_have_minimum_cases():
    assert len(CASES) >= 30


def test_blocked_categories_win_over_search():
    assert classify_query("какая погода сегодня", KEYWORDS).action == "deflect"


def test_case_insensitive_and_dirty_text():
    assert classify_query("  ПОГОДА ЗАВТРА!! ", KEYWORDS).action == "deflect"
    assert classify_query("ПесНя из рекламы", KEYWORDS).action == "search"
    assert classify_query("кто выиграл матч?", KEYWORDS).action == "search"
