"""MCP-сервер, отдающий агенту (например, в НОЯ) собранную базу знаний
по судам и позволяющий по запросу обновить один суд.

Запуск:
    python -m sudrf_kb.cli serve-mcp --transport stdio
    python -m sudrf_kb.cli serve-mcp --transport sse --host 0.0.0.0 --port 8765

Требует, чтобы `python -m sudrf_kb.cli crawl --all` и `build-kb` были
выполнены хотя бы раз (иначе список судов будет пуст) - см. README.md.
Этот сервер сам по себе НЕ обходит все сайты при каждом запуске: он
читает уже собранный кэш data/raw/*.json и данные data/*.json, поэтому
может работать быстро и без постоянного давления на сайты судов.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from .config import AppConfig, load_config
from .crawler import crawl_court
from .fetch import PoliteFetcher
from .kb_builder import load_crawl_outcomes, save_crawl_outcome

logger = logging.getLogger(__name__)

mcp = FastMCP("sudrf-court-kb")

_config: AppConfig = load_config()


def _get_courts_index() -> dict[str, dict]:
    return {court["court_id"]: court for court in load_crawl_outcomes(_config.data_dir)}


@mcp.tool()
def list_courts() -> list[dict]:
    """Список судов, доступных в базе знаний, с их court_id, названием и сайтом."""
    return [
        {
            "court_id": court.court_id,
            "name": court.name,
            "base_url": court.base_url,
            "city": court.city,
        }
        for court in _config.courts
    ]


@mcp.tool()
def get_court_info(court_id: str) -> dict:
    """Возвращает собранную информацию по одному суду: контакты, реквизиты,
    график приёма, структуру, новости и т.д., сгруппированные по категориям.

    Аргументы:
        court_id: идентификатор суда из list_courts (например, "sovetsky").
    """
    index = _get_courts_index()
    court = index.get(court_id)
    if court is None:
        return {
            "error": f"Суд '{court_id}' не найден. Доступные: {list(index.keys())}"
        }

    by_category: dict[str, list[dict]] = {}
    for page in court["pages"]:
        by_category.setdefault(page["category"], []).append(
            {"title": page["title"], "url": page["url"], "text": page["text"]}
        )

    return {
        "court_id": court["court_id"],
        "name": court["name"],
        "base_url": court["base_url"],
        "categories": by_category,
    }


@mcp.tool()
def search_courts(query: str, court_id: str | None = None, limit: int = 5) -> list[dict]:
    """Ищет по собранной базе знаний судов простым текстовым поиском (без
    учёта регистра) и возвращает наиболее релевантные фрагменты.

    Аргументы:
        query: поисковая фраза, например "график приёма" или "реквизиты пошлины".
        court_id: если указан, искать только в этом суде; иначе - по всем.
        limit: максимум результатов.
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return []

    index = _get_courts_index()
    candidates = [index[court_id]] if court_id and court_id in index else index.values()

    results: list[dict] = []
    for court in candidates:
        for page in court["pages"]:
            haystack = f"{page['title']}\n{page['text']}".lower()
            if query_lower in haystack:
                snippet_pos = haystack.find(query_lower)
                start = max(0, snippet_pos - 150)
                end = min(len(page["text"]), snippet_pos + 150)
                results.append(
                    {
                        "court_id": court["court_id"],
                        "court_name": court["name"],
                        "page_title": page["title"],
                        "url": page["url"],
                        "snippet": page["text"][start:end],
                    }
                )

    return results[:limit]


@mcp.tool()
def refresh_court(court_id: str) -> dict:
    """Принудительно повторно обходит сайт одного суда прямо сейчас и
    обновляет кэш базы знаний для него. Делает живой сетевой запрос к
    сайту суда - используйте только когда это реально нужно (например,
    после жалобы, что данные устарели), не для каждого сообщения агента.

    Работает ТОЛЬКО если процесс запущен с российского IP (см. README.md).
    """
    court = _config.get_court(court_id)
    fetcher = PoliteFetcher(_config.crawl)
    outcome = crawl_court(court, _config.crawl, fetcher=fetcher)
    save_crawl_outcome(outcome, _config.data_dir)
    return {
        "court_id": court_id,
        "pages_collected": len(outcome.pages),
        "errors": outcome.errors,
    }


def run(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765) -> None:
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport=transport)
