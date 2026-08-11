import pytest

from core.route import (
    ACTION_ADDRESSED,
    ACTION_LOG_ONLY,
    parse_addressed_message,
    should_ignore_message,
)

BOT = "Анька"


@pytest.mark.parametrize(
    ("text", "expected_stripped"),
    [
        ("Анька, привет как дела", "привет как дела"),
        ("анька,привет", "привет"),
        ("Анька,  привет", "привет"),  # два пробела — один съеден, остальное strip
    ],
)
def test_addressed_messages(text, expected_stripped):
    decision = parse_addressed_message(text, BOT)
    assert decision.action == ACTION_ADDRESSED
    assert decision.stripped_text == expected_stripped


@pytest.mark.parametrize(
    "text",
    [
        "Аньке привет",  # нет запятой сразу после ника
        "Анька привет",  # нет запятой вообще
        "привет, Анька, как дела",  # ник не в начале
        "  Анька , привет",  # пробел перед запятой — не по формату
        "Анька,,привет",  # двойная запятая — опечатка формата
        "Анька,:привет",  # запятая с двоеточием — опечатка формата
        "Анька,",  # запятая и пустота — отвечать не на что
        "",
        "   ",
        "Привет, Анька",
        "Анька!",  # нет запятой
    ],
)
def test_log_only_messages(text):
    decision = parse_addressed_message(text, BOT)
    assert decision.action == ACTION_LOG_ONLY
    assert decision.stripped_text is None


def test_punctuation_inside_stripped_text_is_fine():
    decision = parse_addressed_message("Анька, привет. Как дела?", BOT)
    assert decision.action == ACTION_ADDRESSED
    assert decision.stripped_text == "привет. Как дела?"


def test_should_ignore_bot_itself():
    assert should_ignore_message("Анька", "Анька", set()) is True
    assert should_ignore_message("Вася", "Анька", set()) is False


def test_should_ignore_user_in_ignored_set():
    assert should_ignore_message("Тролль", "Анька", {"Тролль"}) is True
    assert should_ignore_message("Тролль", "Анька", {"Другой"}) is False
