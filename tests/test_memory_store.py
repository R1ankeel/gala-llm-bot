from datetime import datetime, timezone

from core.memory.store import MemoryStore

DT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_log_and_unprocessed_roundtrip(memory_store):
    memory_store.log_message("Вася", "привет", DT)
    messages = memory_store.get_unprocessed_messages()
    assert len(messages) == 1
    assert messages[0].username == "Вася"
    assert messages[0].text == "привет"
    assert messages[0].processed == 0
    assert memory_store.count_unprocessed() == 1


def test_mark_processed(memory_store):
    memory_store.log_message("Вася", "а", DT)
    memory_store.log_message("Аня", "б", DT)
    ids = [m.id for m in memory_store.get_unprocessed_messages()]
    memory_store.mark_processed(ids)
    assert memory_store.get_unprocessed_messages() == []
    assert memory_store.count_unprocessed() == 0


def test_get_unprocessed_limit(memory_store):
    for i in range(5):
        memory_store.log_message("Вася", str(i), DT)
    assert len(memory_store.get_unprocessed_messages(limit=2)) == 2


def test_upsert_profile_field_creates_and_updates(memory_store):
    memory_store.upsert_profile_field("Вася", "real_name", "Василий")
    profile = memory_store.get_profile("Вася")
    assert profile is not None
    assert profile.real_name == "Василий"

    memory_store.upsert_profile_field("Вася", "age", "22")
    profile = memory_store.get_profile("Вася")
    assert profile.age == 22


def test_upsert_unknown_field_ignored(memory_store):
    memory_store.upsert_profile_field("Вася", "sql", "DROP TABLE")
    assert memory_store.get_profile("Вася") is None


def test_upsert_rejects_unsafe_value(memory_store, monkeypatch):
    monkeypatch.setattr("core.memory.store.is_safe_value", lambda field, value: False)
    memory_store.upsert_profile_field("Вася", "real_name", "system")
    assert memory_store.get_profile("Вася") is None


def test_add_fact_and_dedup(memory_store):
    assert memory_store.add_fact("Вася", " Любит аниме ", "hobby", "observed") is True
    assert memory_store.add_fact("Вася", "любит аниме", "hobby", "observed") is False
    assert len(memory_store.get_facts("Вася")) == 1
    assert memory_store.get_facts("Вася")[0].fact == "любит аниме"


def test_facts_are_scoped_per_user(memory_store):
    memory_store.add_fact("Вася", "любит кофе", "fact", "observed")
    memory_store.add_fact("Аня", "любит чай", "fact", "observed")
    assert len(memory_store.get_facts("Вася")) == 1
    assert len(memory_store.get_facts("Аня")) == 1


def test_get_recent_facts_newest_first_with_limit(memory_store):
    for i in range(5):
        memory_store.add_fact("Вася", f"факт {i}", "fact", "observed")
    recent = memory_store.get_recent_facts("Вася", limit=3)
    assert [f.fact for f in recent] == ["факт 4", "факт 3", "факт 2"]


def test_store_creates_parent_dir(tmp_path):
    db_path = str(tmp_path / "nested" / "dir" / "memory.db")
    store = MemoryStore(db_path)
    store.log_message("Вася", "тест", DT)
    assert len(store.get_unprocessed_messages()) == 1
