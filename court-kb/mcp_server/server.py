"""
Демонстрационный MCP-сервер поверх собранной базы знаний по судам.

Идея: агент в НОЕ подключается к этому серверу через MCP и получает
инструмент court_kb_search — "живой" поиск по актуальному корпусу данных
(data/corpus.jsonl), собранному scraper'ом. Это отдельный слой поверх/вместо
статичной загрузки текстов в БЗ платформы: пригодится, если платформа не
даёт программно обновлять БЗ, либо если нужно гарантировать самые свежие
данные без ре-аплоада документов.

ВАЖНО: это MVP на простом текстовом поиске (без эмбеддингов), чтобы не тащить
лишние зависимости. Для продакшена замените search() на векторный поиск
(например, через любую embedding-модель + FAISS/pgvector) — интерфейс тула
для агента при этом не изменится.

Запуск (stdio-транспорт, самый простой вариант для локальной/серверной интеграции):

    python -m mcp_server.server --corpus ../data/corpus.jsonl

Дальше сервер регистрируется в клиенте/платформе как обычный MCP stdio-сервер.
"""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


@dataclass
class KbEntry:
    court_slug: str
    court_name: str
    url: str
    title: Optional[str]
    text: str


def load_corpus(path: Path) -> list[KbEntry]:
    entries: list[KbEntry] = []
    if not path.exists():
        return entries
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            entries.append(KbEntry(
                court_slug=rec["court_slug"],
                court_name=rec["court_name"],
                url=rec["url"],
                title=rec.get("title"),
                text=rec["text"],
            ))
    return entries


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def score(entry: KbEntry, query_tokens: set[str]) -> int:
    text_tokens = _tokenize(entry.text) | _tokenize(entry.title or "")
    return len(query_tokens & text_tokens)


def build_server(corpus_path: Path) -> FastMCP:
    mcp = FastMCP("court-kb")
    entries = load_corpus(corpus_path)

    @mcp.tool()
    def court_kb_search(query: str, court_slug: Optional[str] = None, top_k: int = 3) -> str:
        """Ищет ответ на вопрос пользователя в базе знаний по сайтам судов
        (контакты, режим работы, реквизиты, судебные участки, часто задаваемые
        вопросы и т.п.). Возвращает наиболее релевантные фрагменты с указанием
        суда и ссылки на исходную страницу.

        query: вопрос пользователя на русском языке.
        court_slug: если известен конкретный суд (см. courts.yaml) — сузить поиск.
        top_k: сколько фрагментов вернуть (по умолчанию 3).
        """
        if not entries:
            return ("База знаний пуста: запустите scraper.crawl с российского IP/прокси, "
                    "чтобы наполнить data/corpus.jsonl.")

        query_tokens = _tokenize(query)
        candidates = [e for e in entries if court_slug is None or e.court_slug == court_slug]
        ranked = sorted(candidates, key=lambda e: score(e, query_tokens), reverse=True)
        ranked = [e for e in ranked if score(e, query_tokens) > 0][:top_k]

        if not ranked:
            return "По этому вопросу в базе знаний ничего не найдено."

        chunks = []
        for e in ranked:
            snippet = e.text[:800]
            chunks.append(f"[{e.court_name}] {e.title or ''}\n{snippet}\nИсточник: {e.url}")
        return "\n\n---\n\n".join(chunks)

    @mcp.tool()
    def court_kb_list_courts() -> str:
        """Возвращает список судов, доступных в базе знаний (slug + название)."""
        slugs = {(e.court_slug, e.court_name) for e in entries}
        if not slugs:
            return "База знаний пуста."
        return "\n".join(f"{slug}: {name}" for slug, name in sorted(slugs))

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "corpus.jsonl")
    args = parser.parse_args()

    server = build_server(args.corpus)
    server.run()


if __name__ == "__main__":
    main()
