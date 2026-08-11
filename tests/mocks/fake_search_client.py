from core.search_client import SearchResult


class FakeSearchClient:
    """Фейковый SearchClient с предзаданными результатами по ключу query.

    Используется во всех тестах и в CI. Реальные сетевые вызовы к DDGS —
    только в scripts/eval_character.py, никогда в pytest.
    """

    def __init__(self, results_by_query: dict[str, list[SearchResult]] | None = None):
        self.results_by_query = results_by_query or {}
        self.searches: list[str] = []

    def search(self, query: str, max_results: int = 3) -> list[SearchResult]:
        self.searches.append(query)
        return self.results_by_query.get(query, [])


class FailingSearchClient:
    """Симуляция падения сети: исключение внутри реализации."""

    def search(self, query: str, max_results: int = 3) -> list[SearchResult]:
        raise RuntimeError("network down")
