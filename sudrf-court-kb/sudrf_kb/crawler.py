"""Обход одного сайта суда в пределах его домена (BFS с ограничением глубины)."""

from __future__ import annotations

import dataclasses
import logging
from collections import deque

from .config import CourtConfig, CrawlConfig
from .fetch import BlockedByWafError, PoliteFetcher
from .parse import ParsedPage, parse_page

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class CrawlOutcome:
    court: CourtConfig
    pages: list[ParsedPage]
    errors: list[str]


def is_sensitive_url(url: str, markers: tuple[str, ...]) -> bool:
    lowered = url.lower()
    return any(marker.lower() in lowered for marker in markers)


def crawl_court(
    court: CourtConfig,
    crawl_config: CrawlConfig,
    fetcher: PoliteFetcher | None = None,
    skip_sensitive: bool = True,
) -> CrawlOutcome:
    """Обходит сайт суда, начиная с base_url, в пределах его домена.

    skip_sensitive=True (по умолчанию) не заходит на страницы карточек дел
    (см. sensitive_path_markers в config/courts.yaml) — там может быть
    информация о персональных данных участников процесса, которую не стоит
    автоматически тащить в базу знаний без отдельной проверки (см. README.md).
    """
    fetcher = fetcher or PoliteFetcher(crawl_config)

    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(court.base_url, 0)])
    pages: list[ParsedPage] = []
    errors: list[str] = []

    while queue and len(pages) < crawl_config.max_pages_per_court:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if skip_sensitive and is_sensitive_url(url, crawl_config.sensitive_path_markers):
            logger.info("Пропускаю чувствительную страницу: %s", url)
            continue

        try:
            result = fetcher.fetch_page(url)
        except BlockedByWafError as exc:
            errors.append(str(exc))
            logger.error("%s", exc)
            # Если заблокировал WAF - нет смысла продолжать обход этого суда.
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            logger.warning("Ошибка при получении %s: %s", url, exc)
            continue

        if "text/html" not in result.content_type and result.content_type:
            continue

        parsed = parse_page(result.url, result.html)
        pages.append(parsed)

        if depth < crawl_config.max_depth:
            for link in parsed.links:
                if link not in visited:
                    queue.append((link, depth + 1))

    return CrawlOutcome(court=court, pages=pages, errors=errors)
