"""MCP-сервер, отдающий ИИ-агенту информацию о судах, собранную скрапером.

Запуск (stdio, для локальной интеграции / отладки):
    python -m sudrf_scraper.mcp_server

Запуск как удалённый сервер по HTTP (чтобы платформа НОЕ могла подключиться
по URL через MCP-коннектор):
    python -m sudrf_scraper.mcp_server --transport streamable-http --port 8765

Перед запуском нужно хотя бы раз собрать данные командой:
    python -m sudrf_scraper.cli --proxy http://<ru-proxy> -v
"""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

from .config import DEFAULT_DATA_DIR
from .search import CourtKnowledgeBase

mcp = FastMCP("sudrf-courts")
_kb = CourtKnowledgeBase(DEFAULT_DATA_DIR)


@mcp.tool()
def list_courts() -> list[dict]:
    """Список судов, по которым собрана информация: slug, название, url,
    дата последнего сбора данных и найденные контакты."""
    return _kb.list_courts()


@mcp.tool()
def get_court_info(court_slug: str) -> dict:
    """Полная информация по одному суду (контакты + список разделов сайта).

    court_slug: идентификатор суда, см. list_courts().
    """
    dump = _kb.get_court(court_slug)
    if dump is None:
        return {"error": f"Суд с slug='{court_slug}' не найден. Используйте list_courts()."}
    return {
        "court": dump["court"],
        "scraped_at": dump.get("scraped_at"),
        "contacts": dump.get("contacts", {}),
        "sections": sorted({p.get("section", "other") for p in dump.get("pages", [])}),
    }


@mcp.tool()
def search_court_info(query: str, court_slug: str | None = None, limit: int = 5) -> list[dict]:
    """Поиск по собранным страницам судов (реквизиты, приёмные часы, судьи,
    порядок подачи документов и т.д.).

    query: поисковый запрос на русском (например: "реквизиты госпошлины",
        "график приема граждан", "как подать исковое заявление").
    court_slug: ограничить поиск одним судом (см. list_courts()), либо None
        для поиска по всем судам сразу.
    limit: максимум результатов.
    """
    hits = _kb.search(query, court_slug=court_slug, limit=limit)
    return [
        {
            "court": h.court_name,
            "court_slug": h.court_slug,
            "title": h.title,
            "section": h.section,
            "url": h.url,
            "snippet": h.snippet,
        }
        for h in hits
    ]


@mcp.tool()
def reload_knowledge_base() -> dict:
    """Перечитать данные с диска (вызывать после того, как скрапер обновил
    data/*.json по расписанию, чтобы агент увидел свежие данные без перезапуска)."""
    _kb.reload()
    return {"status": "ok", "courts_loaded": len(_kb.list_courts())}


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP-сервер с информацией о судах")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="stdio — для локальных клиентов; streamable-http/sse — для подключения по URL",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
