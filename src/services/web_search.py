import asyncio
import logging
from dataclasses import dataclass

from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def _sync_search(query: str, max_results: int) -> list[dict]:
    """Synchronous DuckDuckGo search (runs in thread pool)."""
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def search_web(query: str, max_results: int = 5) -> list[SearchResult]:
    """
    Search the web using DuckDuckGo.

    Args:
        query: Search query string
        max_results: Maximum number of results to return

    Returns:
        List of SearchResult objects
    """
    try:
        results = await asyncio.to_thread(_sync_search, query, max_results)

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
            )
            for r in results
        ]

    except Exception as e:
        logger.error(f"Web search error: {e}", exc_info=True)
        return []


def format_search_results(results: list[SearchResult]) -> str:
    """Format search results into a prompt-friendly string."""
    if not results:
        return "Результаты поиска не найдены."

    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"{i}. [{r.title}]({r.url})\n{r.snippet}")

    return "\n\n".join(parts)
