import os

import yaml

from core.memory.gender_resolver import resolve_gender
from core.memory.store import UserProfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEURISTICS_PATH = os.path.join(ROOT, "config", "gender_heuristics.yaml")
with open(HEURISTICS_PATH, "r", encoding="utf-8") as fh:
    HEURISTICS = yaml.safe_load(fh)


def _profile(gender: str | None = None, gender_source: str | None = None) -> UserProfile:
    return UserProfile(username="x", updated_at="2026-01-01", gender=gender, gender_source=gender_source)


def test_explicit_gender_wins_over_nickname():
    assert resolve_gender("Маша", _profile(gender="male"), HEURISTICS) == ("male", "explicit")
    assert resolve_gender("Вася", _profile(gender="female"), HEURISTICS) == ("female", "explicit")


def test_nickname_in_common_male_names():
    assert resolve_gender("Вася123", None, HEURISTICS) == ("male", "heuristic")


def test_nickname_in_common_female_names_with_digits():
    assert resolve_gender("Маша2007", None, HEURISTICS) == ("female", "heuristic")


def test_family_name_suffix_heuristics():
    assert resolve_gender("Дмитриев", None, HEURISTICS) == ("male", "heuristic")
    assert resolve_gender("Дмитриева", None, HEURISTICS) == ("female", "heuristic")


def test_unknown_nick_returns_none():
    assert resolve_gender("user4821", None, HEURISTICS) == (None, None)


def test_empty_and_symbol_nick():
    assert resolve_gender("", None, HEURISTICS) == (None, None)
    assert resolve_gender("12345", None, HEURISTICS) == (None, None)
