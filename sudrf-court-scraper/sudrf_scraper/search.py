from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_DATA_DIR


@dataclass
class SearchHit:
    court_slug: str
    court_name: str
    title: str
    url: str
    section: str
    snippet: str
    score: int


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[а-яa-z0-9]+", text.lower())


def _snippet(text: str, query_tokens: list[str], width: int = 240) -> str:
    lowered = text.lower()
    pos = -1
    for token in query_tokens:
        idx = lowered.find(token)
        if idx != -1:
            pos = idx
            break
    if pos == -1:
        return text[:width].strip()
    start = max(0, pos - width // 2)
    end = min(len(text), start + width)
    return text[start:end].strip()


class CourtKnowledgeBase:
    """Простая база знаний в памяти на основе JSON-дампов, собранных
    ``sudrf_scraper.crawler``. Используется как локальный поисковый бэкенд
    для MCP-инструментов (без внешних embeddings/vector DB — по ключевым
    словам, чего достаточно для справочной информации о судах).
    """

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self._courts: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        self._courts = {}
        if not self.data_dir.exists():
            return
        for path in sorted(self.data_dir.glob("*.json")):
            with open(path, "r", encoding="utf-8") as fh:
                dump = json.load(fh)
            self._courts[dump["court"]["slug"]] = dump

    def list_courts(self) -> list[dict]:
        return [
            {
                "slug": slug,
                "name": dump["court"]["name"],
                "url": dump["court"]["url"],
                "scraped_at": dump.get("scraped_at"),
                "contacts": dump.get("contacts", {}),
            }
            for slug, dump in self._courts.items()
        ]

    def get_court(self, slug: str) -> dict | None:
        return self._courts.get(slug)

    def search(self, query: str, court_slug: str | None = None, limit: int = 5) -> list[SearchHit]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        hits: list[SearchHit] = []
        courts = (
            [self._courts[court_slug]] if court_slug and court_slug in self._courts
            else self._courts.values()
        )

        for dump in courts:
            court_name = dump["court"]["name"]
            court_slug_val = dump["court"]["slug"]
            for page in dump.get("pages", []):
                haystack = f"{page['title']}\n{page['text']}".lower()
                score = sum(haystack.count(tok) for tok in query_tokens)
                if score <= 0:
                    continue
                hits.append(
                    SearchHit(
                        court_slug=court_slug_val,
                        court_name=court_name,
                        title=page["title"],
                        url=page["url"],
                        section=page.get("section", "other"),
                        snippet=_snippet(page["text"], query_tokens),
                        score=score,
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]
