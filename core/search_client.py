import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str | None = None


class SearchClient:
    """Обёртка над DDGS. URL хранится только для логов/дебага —
    в промпт не прокидывается."""

    def __init__(self, timeout: float = 5.0, region: str = "ru-ru"):
        self.timeout = timeout
        self.region = region

    def search(self, query: str, max_results: int = 3) -> list[SearchResult]:
        """Возвращает результаты или [] при любой ошибке.

        Сеть, rate limit, пустой ответ — всё превращается в [] без
        исключения наружу. Ретраи не нужны: это не критичный путь,
        при неудаче бот отвечает без свежих данных.
        """
        try:
            raw = self._fetch(query, max_results)
        except Exception as err:  # noqa: BLE001 — наружу не пробрасываем
            logger.warning("Поиск DDGS не удался (%s): %s", type(err).__name__, err)
            return []
        return self._to_results(raw)

    def _fetch(self, query: str, max_results: int) -> list[dict]:
        from ddgs import DDGS

        return DDGS(timeout=self.timeout).text(
            query,
            max_results=max_results,
            region=self.region,
        )

    def _to_results(self, raw: list[dict]) -> list[SearchResult]:
        results = []
        for item in raw or []:
            title = (item.get("title") or "").strip()
            snippet = (item.get("body") or item.get("snippet") or "").strip()
            if not snippet and not title:
                continue
            results.append(
                SearchResult(
                    title=title,
                    snippet=snippet,
                    url=item.get("href"),
                )
            )
        return results
