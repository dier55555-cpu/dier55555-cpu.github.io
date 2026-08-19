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
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from mcp.server.fastmcp import FastMCP

from scraper.case_lookup.captcha import ManualCaptchaSolver, TwoCaptchaSolver
from scraper.case_lookup.search import CaseQuery, search_case
from scraper.fetch import Fetcher

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


def _load_courts_config(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {c["slug"]: c for c in data.get("courts", [])}


def _build_fetcher() -> Fetcher:
    proxy = os.environ.get("COURT_KB_PROXY")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    return Fetcher(proxies=proxies)


def _build_captcha_solver():
    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if api_key:
        return TwoCaptchaSolver(api_key=api_key)
    if os.environ.get("COURT_KB_MANUAL_CAPTCHA") == "1":
        return ManualCaptchaSolver()
    return None


def build_server(corpus_path: Path, courts_config_path: Optional[Path] = None) -> FastMCP:
    mcp = FastMCP("court-kb")
    entries = load_corpus(corpus_path)
    courts_config_path = courts_config_path or (corpus_path.parent.parent / "courts.yaml")
    courts_config = _load_courts_config(courts_config_path)

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

    @mcp.tool()
    def court_case_lookup(
        court_slug: str,
        case_number: Optional[str] = None,
        last_name: Optional[str] = None,
        production_type: str = "civil_first_instance",
    ) -> str:
        """Слой 2: ищет конкретное дело на сайте суда (модуль «Судебное
        делопроизводство») по номеру дела и/или фамилии участника и
        возвращает данные по делу и движение дела. В отличие от
        court_kb_search, это ЖИВОЙ запрос к сайту суда на момент вызова, а не
        поиск по заранее собранной базе.

        court_slug: slug суда из courts.yaml (например, "sovetsky-vrn").
        case_number: номер дела/материала, например "2-123/2026".
        last_name: фамилия истца/ответчика (если номер дела неизвестен).
        production_type: тип производства из courts.yaml -> case_search.production_types
            (по умолчанию "civil_first_instance").

        Требует переменные окружения: COURT_KB_PROXY (российский HTTP(S)-прокси,
        без него сайт суда заблокирует запрос) и, если на сайте есть капча,
        TWOCAPTCHA_API_KEY (или COURT_KB_MANUAL_CAPTCHA=1 для ручного ввода
        капчи в консоли сервера — не подходит для автоответа агента).
        """
        court = courts_config.get(court_slug)
        if court is None:
            return f"Суд {court_slug!r} не найден в courts.yaml."

        case_search_cfg = court.get("case_search") or {}
        if not case_search_cfg.get("enabled"):
            return (
                f"Поиск дел для суда {court_slug!r} отключён в courts.yaml "
                "(case_search.enabled: false). Сначала запустите "
                "scraper.case_lookup.discover с российского IP/прокси, чтобы "
                "проверить поля формы и капчу, затем включите case_search.enabled."
            )

        delo_id = (case_search_cfg.get("production_types") or {}).get(production_type)
        if delo_id is None:
            known = ", ".join((case_search_cfg.get("production_types") or {}).keys())
            return f"Неизвестный production_type={production_type!r}. Доступные: {known or 'нет настроенных'}."

        if not case_number and not last_name:
            return "Нужно указать хотя бы case_number или last_name."

        fetcher = _build_fetcher()
        solver = _build_captcha_solver()
        query = CaseQuery(case_number=case_number, last_name=last_name)

        result = search_case(
            fetcher,
            base_url=court["base_url"],
            delo_id=delo_id,
            query=query,
            captcha_solver=solver,
            field_overrides=case_search_cfg.get("field_overrides"),
        )
        return result.as_text()

    return mcp


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=project_root / "data" / "corpus.jsonl")
    parser.add_argument("--courts-config", type=Path, default=project_root / "courts.yaml")
    args = parser.parse_args()

    server = build_server(args.corpus, args.courts_config)
    server.run()


if __name__ == "__main__":
    main()
