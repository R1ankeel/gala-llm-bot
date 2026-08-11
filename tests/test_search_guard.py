import os

import pytest
import yaml

from core.character_loader import load_character
from core.config import Config
from core.search_client import SearchClient, SearchResult
from core.search_formatter import format_search_context
from core.search_guard import (
    build_deflect_instruction,
    looks_like_hallucinated_fact,
    pick_deflect_line,
)

import cli
from tests.mocks.fake_search_client import FakeSearchClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTER_PATH = os.path.join(ROOT, "character", "character.yaml")
TASK_KEYWORDS_PATH = os.path.join(ROOT, "config", "task_guard_keywords.yaml")
SEARCH_KEYWORDS_PATH = os.path.join(ROOT, "config", "search_keywords.yaml")

with open(TASK_KEYWORDS_PATH, "r", encoding="utf-8") as fh:
    TASK_KEYWORDS = yaml.safe_load(fh)
with open(SEARCH_KEYWORDS_PATH, "r", encoding="utf-8") as fh:
    SEARCH_KEYWORDS = yaml.safe_load(fh)


def _config() -> Config:
    return Config(
        ollama_base_url="http://localhost:11434",
        model_name="test-model",
        default_temperature=0.8,
        max_tokens=300,
        character_path=CHARACTER_PATH,
        prompt_budget_chars=6000,
        llm_think=False,
    )


class RecordingClient:
    def __init__(self, reply: str):
        self.reply = reply
        self.seen_prompts: list[str] = []

    def generate(self, system_prompt, messages, temperature=None, max_tokens=None):
        self.seen_prompts.append(system_prompt)
        return self.reply


@pytest.fixture
def character():
    return load_character(CHARACTER_PATH)


def test_hallucinated_weather_positive():
    assert looks_like_hallucinated_fact("Завтра будет +18°C и без осадков", "blocked_weather")
    assert looks_like_hallucinated_fact("Дождь 5 мм, влажность 80%", "blocked_weather")


def test_hallucinated_weather_negative():
    assert not looks_like_hallucinated_fact("Да ну её, эту погоду, сам глянь.", "blocked_weather")
    assert not looks_like_hallucinated_fact("", "blocked_weather")


def test_hallucinated_science_positive():
    long_answer = (
        "Гравитация искривляет пространство-время, фотоны движутся по "
        "геодезическим линиям, а частицы вещества взаимодействуют через "
        "электромагнитное поле. Атомы удерживаются ядерными силами, электроны "
        "вращаются вокруг ядра, и всё это подчиняется законам термодинамики и "
        "квантовой механики. Чтобы объяснить всё точно, нужно много времени, "
        "формул и спокойствия, которых у ночного продавца не бывает по "
        "определению, так что лучше не вдаваться в детали."
    )
    assert len(long_answer) > 300
    assert looks_like_hallucinated_fact(long_answer, "blocked_science")


def test_hallucinated_science_negative():
    assert not looks_like_hallucinated_fact("Это не ко мне, я в лареке сижу.", "blocked_science")


def test_format_search_context_none_when_empty():
    assert format_search_context([]) is None
    assert format_search_context([SearchResult(title="t", snippet="   ")]) is None


def test_format_search_context_no_url_and_truncation():
    results = [
        SearchResult(title="t1", snippet="короткий факт", url="http://example.com/1"),
        SearchResult(title="t2", snippet="a " * 500, url="http://example.com/2"),
    ]
    out = format_search_context(results, max_chars=100)

    assert out is not None
    assert "http://" not in out
    assert len(out) <= 100
    assert "Найдено по теме" in out


def test_pick_deflect_line_from_character(character):
    for _ in range(20):
        assert pick_deflect_line(character, "blocked_weather") in character.deflect_style


def test_pick_deflect_line_never_empty():
    fake = type("Fake", (), {"deflect_style": []})()
    assert pick_deflect_line(fake, "blocked_weather")


def test_build_deflect_instruction_contains_examples(character):
    instruction = build_deflect_instruction(character, "blocked_weather")
    assert "погоде" in instruction
    assert "НЕ называй конкретные цифры" in instruction
    for line in character.deflect_style:
        assert line in instruction


def test_pipeline_search_adds_context_and_instruction(character, memory_store):
    fake = FakeSearchClient(
        {"какая песня в рекламе того кота": [
            SearchResult(title="t", snippet="Это трек группы X, вышел в 2019", url="http://x")
        ]}
    )
    rec = RecordingClient("А, да, эта штука. Знала ещё со школы.")
    reply = cli.run_once(
        _config(), character, "Вася", "какая песня в рекламе того кота",
        TASK_KEYWORDS, SEARCH_KEYWORDS, client=rec, search_client=fake,
        store=memory_store,
    )

    assert fake.searches == ["какая песня в рекламе того кота"]
    prompt = rec.seen_prompts[0]
    assert "Найдено по теме" in prompt
    assert "трек группы X" in prompt
    assert "http://x" not in prompt
    assert "не говори, что искал" in prompt.lower()
    assert reply == "Вася, А, да, эта штука. Знала ещё со школы."


def test_pipeline_search_not_called_for_deflect(character, memory_store):
    fake = FakeSearchClient({})
    rec = RecordingClient("А я почём знаю.")
    cli.run_once(
        _config(), character, "Вася", "какая погода завтра",
        TASK_KEYWORDS, SEARCH_KEYWORDS, client=rec, search_client=fake,
        store=memory_store,
    )

    assert fake.searches == []
    prompt = rec.seen_prompts[0]
    assert "Уклонись в своей манере" in prompt


def test_pipeline_deflect_replaces_hallucinated_reply(character, memory_store):
    rec = RecordingClient("Завтра будет +18°C, без осадков, влажность 60%.")
    reply = cli.run_once(
        _config(), character, "Вася", "какая погода завтра",
        TASK_KEYWORDS, SEARCH_KEYWORDS, client=rec,
        store=memory_store,
    )

    assert reply.count("Вася") == 1
    assert reply[len("Вася, "):] in character.deflect_style


def test_search_client_swallows_network_errors(monkeypatch):
    client = SearchClient()

    def boom(query, max_results):
        raise ConnectionError("network down")

    monkeypatch.setattr(client, "_fetch", boom)
    assert client.search("тест") == []


def test_pipeline_ok_when_search_network_fails(character, monkeypatch, memory_store):
    client = SearchClient()

    def boom(query, max_results):
        raise ConnectionError("network down")

    monkeypatch.setattr(client, "_fetch", boom)
    rec = RecordingClient("Ничё не знаю про это.")
    reply = cli.run_once(
        _config(), character, "Вася", "кто выиграл вчера матч",
        TASK_KEYWORDS, SEARCH_KEYWORDS, client=rec, search_client=client,
        store=memory_store,
    )

    assert reply == "Вася, Ничё не знаю про это."
    assert "Найдено по теме" not in rec.seen_prompts[0]


def test_pipeline_task_guard_wins_over_search(character, memory_store):
    fake = FakeSearchClient({})
    rec = RecordingClient("Слушай, это не ко мне.")
    cli.run_once(
        _config(), character, "Вася", "объясни подробно как работает двигатель",
        TASK_KEYWORDS, SEARCH_KEYWORDS, client=rec, search_client=fake,
        store=memory_store,
    )

    assert fake.searches == []
    prompt = rec.seen_prompts[0]
    assert "Ты ЭТОГО НЕ ДЕЛАЕШЬ никогда" in prompt
    assert "Найдено по теме" not in prompt
