import pytest

from core.memory.store import MemoryStore


@pytest.fixture
def memory_store(tmp_path):
    return MemoryStore(str(tmp_path / "memory.db"))
