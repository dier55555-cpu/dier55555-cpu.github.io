from __future__ import annotations

import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from .config import Court
from .fetch import fetch, polite_sleep
from .parse import Page, extract_contacts, parse_page

logger = logging.getLogger(__name__)

# Ссылки, которые почти всегда не содержат полезного для БЗ контента
# (личный кабинет, подача документов онлайн, поиск, авторизация и т.п.)
SKIP_URL_SUBSTRINGS = (
    "/login", "/auth", "search", "?PAGEN", "captcha", ".pdf", ".doc", ".xls",
    ".jpg", ".jpeg", ".png", ".zip", ".rar",
)


@dataclass
class CourtDump:
    court: Court
    scraped_at: str
    pages: list[Page] = field(default_factory=list)
    contacts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "court": asdict(self.court),
            "scraped_at": self.scraped_at,
            "contacts": self.contacts,
            "pages": [asdict(p) for p in self.pages],
        }


def _should_skip(url: str) -> bool:
    lowered = url.lower()
    return any(s in lowered for s in SKIP_URL_SUBSTRINGS)


def crawl_court(
    court: Court,
    session: requests.Session,
    max_pages: int = 60,
    max_depth: int = 3,
    delay: float = 1.0,
) -> CourtDump:
    """Обходит сайт суда в ширину, начиная с главной страницы, и собирает
    текстовое содержимое страниц того же домена.
    """
    base_netloc = urlparse(court.url).netloc
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(court.url, 0)])
    pages: list[Page] = []
    all_text_for_contacts: list[str] = []

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        if _should_skip(url):
            continue

        resp = fetch(session, url)
        if resp is None:
            continue

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            continue

        page = parse_page(url, resp.text)
        pages.append(page)
        all_text_for_contacts.append(page.text)
        logger.info("[%s] %s -> %s (%d символов)", court.slug, page.section, url, len(page.text))

        if urlparse(court.url).netloc == base_netloc:
            for link in page.links:
                if link not in visited and urlparse(link).netloc == base_netloc:
                    queue.append((link, depth + 1))

        polite_sleep(delay)

    contacts = extract_contacts("\n".join(all_text_for_contacts))

    return CourtDump(
        court=court,
        scraped_at=datetime.now(timezone.utc).isoformat(),
        pages=pages,
        contacts=contacts,
    )
