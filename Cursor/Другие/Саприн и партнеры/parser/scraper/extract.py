"""Извлечение ссылок и основного текста страницы."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse

import trafilatura
from bs4 import BeautifulSoup

# Расширения файлов, которые пропускаем при обходе (не текстовые страницы).
SKIP_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".css", ".js",
)


def same_site(url: str, base_netloc: str) -> bool:
    return urlparse(url).netloc == base_netloc


def extract_links(html: str, page_url: str) -> set[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_netloc = urlparse(page_url).netloc
    links: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(page_url, href)
        absolute, _ = urldefrag(absolute)
        if not same_site(absolute, base_netloc):
            continue
        if absolute.lower().endswith(SKIP_EXTENSIONS):
            continue
        links.add(absolute)
    return links


def extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return " ".join(soup.title.string.split())
    h1 = soup.find("h1")
    if h1:
        return " ".join(h1.get_text(" ").split())
    return None


def extract_main_text(html: str, url: str) -> str | None:
    """Достаём основной текст страницы независимо от конкретной вёрстки шаблона.

    trafilatura умеет отличать "мясо" статьи от меню/шапки/подвала без знания
    точной структуры конкретной сборки ГАС «Правосудие» (она отличается от
    суда к суду).
    """
    text = trafilatura.extract(
        html,
        url=url,
        favor_recall=True,
        include_tables=True,
        include_comments=False,
        no_fallback=False,
    )
    if text and len(text.strip()) >= 40:
        return text.strip()

    # Фолбэк, если trafilatura не справилась с нестандартной вёрсткой:
    # берём весь видимый текст body, чистим лишние пробелы/пустые строки.
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    raw_lines = (line.strip() for line in body.get_text("\n").splitlines())
    lines = [line for line in raw_lines if line]
    joined = "\n".join(lines)
    return joined if len(joined) >= 40 else None
