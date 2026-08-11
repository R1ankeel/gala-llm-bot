import os

import pytest

from core.character_loader import build_core_system_prompt, load_character
from core.llm_client import LLMClient, LLMError
from core.response_formatter import format_reply

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTER_PATH = os.path.join(ROOT, "character", "character.yaml")


def test_core_system_prompt_contains_all_fields_verbatim():
    character = load_character(CHARACTER_PATH)
    prompt = build_core_system_prompt(character)

    assert character.name in prompt
    assert character.short_bio in prompt
    for item in character.speech_style:
        assert item in prompt
    for item in character.boundaries:
        assert item in prompt
    for item in character.refusal_style:
        assert item in prompt
    for pair in character.example_dialogues:
        assert pair["user"] in prompt
        assert pair["bot"] in prompt
    for item in character.never_do:
        assert item in prompt


def test_format_reply_does_not_duplicate_nick():
    raw = "Вася, привет как дела\n\nКак настроение?"
    out = format_reply(raw, "Вася")
    assert out.count("Вася") == 1
    assert out == "Вася, привет как дела\nКак настроение?"


def test_format_reply_quoted_nick():
    out = format_reply("«Вася», тут такое дело", "Вася")
    assert out.count("Вася") == 1
    assert out == "Вася, тут такое дело"


def test_format_reply_bold_nick():
    out = format_reply("**Вася:** привет", "Вася")
    assert out.count("Вася") == 1
    assert out == "Вася, привет"


def test_format_reply_empty_string_fallback():
    out = format_reply("", "Вася")
    assert out.startswith("Вася, ")
    assert out != "Вася, "


def test_format_reply_whitespace_only_fallback():
    out = format_reply("   \n  ", "Вася")
    assert out.startswith("Вася, ")


def test_format_reply_wrapped_quotes_removed():
    out = format_reply('"Ну и дела"', "Вася")
    assert out == "Вася, Ну и дела"


def test_llm_generate_raises_when_backend_unavailable():
    client = LLMClient(
        base_url="http://127.0.0.1:1",
        model="test-model",
        max_retries=1,
        timeout=1,
    )
    with pytest.raises(LLMError) as excinfo:
        client.generate("sys", [{"role": "user", "content": "hi"}])
    assert "бэкенд" in str(excinfo.value)
