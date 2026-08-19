"""
Обход сайтов судов и выгрузка структурированной базы знаний.

Пример запуска (с сервера/прокси с российским IP!):

    python -m scraper.crawl --config courts.yaml --out data --max-pages 60 --max-depth 2

Результат на каждый суд:
    data/<slug>/pages.jsonl   — по одной странице в строке (url, title, text, hash, ...)
    data/<slug>/report.json  — сводка обхода (сколько страниц, блокировки, ошибки)
    data/corpus.jsonl         — общий корпус по всем судам (для загрузки в БЗ / индексации)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .extract import extract_links, extract_main_text, extract_title
from .fetch import Fetcher


@dataclass
class PageRecord:
    court_slug: str
    court_name: str
    url: str
    title: str | None
    text: str
    text_hash: str
    fetched_at: str


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def crawl_court(fetcher: Fetcher, slug: str, name: str, base_url: str,
                 max_pages: int, max_depth: int) -> tuple[list[PageRecord], dict]:
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(base_url, 0)]
    records: list[PageRecord] = []
    blocked_urls: list[str] = []
    error_urls: list[tuple[str, str]] = []

    while queue and len(visited) < max_pages:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        result = fetcher.get(url)
        if result.blocked:
            blocked_urls.append(url)
            continue
        if not result.ok or not result.html:
            error_urls.append((url, result.error or f"HTTP {result.status_code}"))
            continue

        text = extract_main_text(result.html, url)
        if text:
            records.append(PageRecord(
                court_slug=slug,
                court_name=name,
                url=url,
                title=extract_title(result.html),
                text=text,
                text_hash=sha256(text),
                fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ))

        if depth < max_depth:
            for link in extract_links(result.html, url):
                if link not in visited:
                    queue.append((link, depth + 1))

    report = {
        "court_slug": slug,
        "court_name": name,
        "base_url": base_url,
        "pages_saved": len(records),
        "pages_blocked": len(blocked_urls),
        "pages_error": len(error_urls),
        "blocked_urls_sample": blocked_urls[:5],
        "error_urls_sample": error_urls[:5],
        "fully_blocked": len(records) == 0 and len(blocked_urls) > 0,
    }
    return records, report


def load_courts(config_path: Path) -> list[dict]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return data["courts"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path("courts.yaml"))
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--max-pages", type=int, default=60, help="максимум страниц на суд")
    parser.add_argument("--max-depth", type=int, default=2, help="глубина обхода от главной страницы")
    parser.add_argument("--min-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=5.0)
    parser.add_argument("--proxy", type=str, default=None,
                         help="HTTP(S)-прокси с российским IP, напр. http://user:pass@host:port")
    parser.add_argument("--only", type=str, default=None, help="обработать только суд с этим slug")
    args = parser.parse_args(argv)

    courts = load_courts(args.config)
    if args.only:
        courts = [c for c in courts if c["slug"] == args.only]
        if not courts:
            print(f"Суд с slug={args.only!r} не найден в {args.config}", file=sys.stderr)
            return 1

    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    fetcher = Fetcher(proxies=proxies, delay_range=(args.min_delay, args.max_delay))

    args.out.mkdir(parents=True, exist_ok=True)
    corpus_path = args.out / "corpus.jsonl"
    all_reports = []

    with corpus_path.open("w", encoding="utf-8") as corpus_file:
        for court in courts:
            slug, name, base_url = court["slug"], court["name"], court["base_url"]
            print(f"[{slug}] обход {base_url} ...", file=sys.stderr)
            records, report = crawl_court(fetcher, slug, name, base_url, args.max_pages, args.max_depth)
            all_reports.append(report)

            court_dir = args.out / slug
            court_dir.mkdir(parents=True, exist_ok=True)
            with (court_dir / "pages.jsonl").open("w", encoding="utf-8") as f:
                for rec in records:
                    line = json.dumps(asdict(rec), ensure_ascii=False)
                    f.write(line + "\n")
                    corpus_file.write(line + "\n")
            (court_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            status = "БЛОКИРОВКА (нужен российский IP/прокси)" if report["fully_blocked"] else "OK"
            print(f"[{slug}] страниц собрано: {report['pages_saved']}, статус: {status}", file=sys.stderr)

    summary_path = args.out / "summary.json"
    summary_path.write_text(json.dumps(all_reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nГотово. Сводка: {summary_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
