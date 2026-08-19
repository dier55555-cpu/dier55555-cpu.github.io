"""Fetch and normalize pages of ГАС «Правосудие» court sites (sudrf.ru).

sudrf blocks many datacenter and non-RU IPs. Run this from a Russian
residential/VPS address. The extractor still works on saved HTML.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

BLOCKED_MARKERS = (
    "заблокирован по соображениям безопасности",
    "This request is blocked",
    "Access Denied",
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._chunks: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            return
        href = dict(attrs).get("href")
        if tag == "a" and href:
            self.links.append(href)
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "br"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        joined = " ".join(self._chunks)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None
    blocked: bool
    html: str
    text: str
    links: list[str] = field(default_factory=list)
    error: str | None = None


def is_blocked(html: str) -> bool:
    lowered = html.lower()
    return any(marker.lower() in lowered for marker in BLOCKED_MARKERS)


def extract_text(html: str) -> tuple[str, list[str]]:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text(), parser.links


def fetch_url(url: str, timeout: int = 25) -> FetchResult:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = getattr(resp, "status", 200)
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        text, links = extract_text(body) if body else ("", [])
        return FetchResult(
            url=url,
            ok=False,
            status=exc.code,
            blocked=is_blocked(body),
            html=body,
            text=text,
            links=links,
            error=str(exc),
        )
    except (URLError, TimeoutError, OSError) as exc:
        return FetchResult(
            url=url,
            ok=False,
            status=None,
            blocked=False,
            html="",
            text="",
            links=[],
            error=str(exc),
        )

    text, links = extract_text(html)
    blocked = is_blocked(html)
    return FetchResult(
        url=url,
        ok=not blocked,
        status=status,
        blocked=blocked,
        html=html,
        text=text,
        links=links,
        error="blocked_by_sudrf" if blocked else None,
    )


def useful_links(base_url: str, links: Iterable[str]) -> list[str]:
    keywords = (
        "info_court",
        "sud_delo",
        "territor",
        "подсуд",
        "контакт",
        "raspisan",
        "график",
        "прием",
        "people",
        "press",
    )
    out: list[str] = []
    seen: set[str] = set()
    for href in links:
        low = href.lower()
        if not any(k in low for k in keywords):
            continue
        if href.startswith("http"):
            abs_url = href
        elif href.startswith("/"):
            abs_url = base_url.rstrip("/") + href
        else:
            abs_url = base_url.rstrip("/") + "/" + href
        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)
    return out


def load_courts(config_path: Path) -> list[dict]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return data["courts"]


def scrape_court(court: dict) -> dict:
    pages: dict[str, dict] = {}
    urls = [court["official_url"], *court.get("pages", {}).values()]
    seen: set[str] = set()
    extra: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        result = fetch_url(url)
        pages[url] = asdict(result)
        extra.extend(useful_links(court["official_url"], result.links))
    for url in extra[:12]:
        if url in seen:
            continue
        seen.add(url)
        pages[url] = asdict(fetch_url(url))
    return {"court": court, "pages": pages}


def to_markdown(scrape: dict) -> str:
    court = scrape["court"]
    lines = [
        f"# {court['name']}",
        "",
        f"- Район: {court['district']}",
        f"- Официальный сайт: {court['official_url']}",
        f"- Поиск дел: {court['pages']['cases']}",
        "",
        "Источник — официальный сайт суда. Если страница недоступна, не выдумывать данные.",
        "",
    ]
    for url, page in scrape["pages"].items():
        lines.append(f"## {url}")
        if page.get("blocked"):
            lines.append("Страница заблокирована для текущего IP (фильтр ГАС «Правосудие»).")
        elif not page.get("ok"):
            lines.append(f"Ошибка загрузки: {page.get('error') or page.get('status')}")
        else:
            text = page.get("text") or ""
            lines.append(text[:12000])
        lines.append("")
    return "\n".join(lines) + "\n"


def write_knowledge(scrapes: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    index_lines = ["# Районные суды г. Воронежа", ""]
    for scrape in scrapes:
        court = scrape["court"]
        md_name = f"{court['id']}.md"
        (out_dir / md_name).write_text(to_markdown(scrape), encoding="utf-8")
        index_lines.append(f"- [{court['name']}]({md_name}) — {court['district']} район")
    (out_dir / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    (out_dir / "raw.json").write_text(
        json.dumps(scrapes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
