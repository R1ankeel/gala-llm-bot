from datetime import datetime, timezone

from core.llm_client import LLMError
from core.memory.facts_extractor import FactsExtractor
from tests.mocks.fake_llm_client import FakeLLMClient


def _log(store, username, text):
    store.log_message(username, text, datetime.now(timezone.utc))


def _extractor(store, llm, character_name="Гера"):
    extractor = FactsExtractor(store, llm, character_name=character_name)
    extractor.min_interval_seconds = 0
    return extractor


def test_extraction_cycle_stores_facts(tmp_path, memory_store):
    _log(memory_store, "Аня", "обожаю рисовать")
    llm = FakeLLMClient({"Аня": '[{"fact":"любит рисовать","category":"hobby"}]'})
    extractor = _extractor(memory_store, llm)

    assert extractor.run_extraction_cycle() == 1

    facts = memory_store.get_facts("Аня")
    assert len(facts) == 1
    assert facts[0].fact == "любит рисовать"
    assert facts[0].category == "hobby"
    assert memory_store.count_unprocessed() == 0


def test_invalid_json_does_not_crash(tmp_path, memory_store):
    _log(memory_store, "Вася", "привет")
    llm = FakeLLMClient({"Вася": "не знаю что вернуть"})
    extractor = _extractor(memory_store, llm)

    assert extractor.run_extraction_cycle() == 1
    assert memory_store.get_facts("Вася") == []


def test_dedup_across_cycles(tmp_path, memory_store):
    _log(memory_store, "Вася", "люблю аниме")
    llm = FakeLLMClient({"Вася": '[{"fact":"любит аниме","category":"hobby"}]'})
    extractor = _extractor(memory_store, llm)
    extractor.run_extraction_cycle()

    _log(memory_store, "Вася", "ещё раз про аниме")
    extractor2 = _extractor(memory_store, llm)
    extractor2.run_extraction_cycle()

    assert len(memory_store.get_facts("Вася")) == 1


def test_empty_queue_returns_zero(memory_store):
    extractor = _extractor(memory_store, FakeLLMClient())
    assert extractor.run_extraction_cycle() == 0


def test_llm_error_does_not_crash(tmp_path, memory_store):
    _log(memory_store, "Вася", "привет")
    llm = FakeLLMClient(error=LLMError("network down"))
    extractor = _extractor(memory_store, llm)

    assert extractor.run_extraction_cycle() == 1
    assert memory_store.get_facts("Вася") == []


def test_bot_addressed_messages_excluded(tmp_path, memory_store):
    _log(memory_store, "Вася", "Гера, привет как дела")
    _log(memory_store, "Вася", "мне нравится аниме")
    llm = FakeLLMClient({"Вася": '[{"fact":"любит аниме","category":"hobby"}]'})
    extractor = _extractor(memory_store, llm)

    extractor.run_extraction_cycle()

    assert len(llm.calls) == 1
    user_content = llm.calls[0]["messages"][0]["content"]
    assert "Гера, привет как дела" not in user_content
    assert "мне нравится аниме" in user_content
    assert memory_store.count_unprocessed() == 0


def test_sarcasm_and_too_short_facts_filtered(tmp_path, memory_store):
    _log(memory_store, "Вася", "мой брат крутой программист")
    _log(memory_store, "Вася", "ахахахах ну ты даешь")
    llm = FakeLLMClient(
        {
            "Вася": (
                '[{"fact":"любит кофе","category":"hobby"},'
                '{"fact":"лол шутка","category":"trait"},'
                '{"fact":"ну","category":"fact"}]'
            )
        }
    )
    extractor = _extractor(memory_store, llm)
    extractor.run_extraction_cycle()

    facts = memory_store.get_facts("Вася")
    assert [f.fact for f in facts] == ["любит кофе"]
