"""Вежливый HTTP-клиент для обхода сайтов *.sudrf.ru.

ВАЖНО: эти сайты блокируют запросы не из российских IP-адресов на уровне
инфраструктуры (см. README.md). Никакие заголовки/ретраи это не обойдут —
запускайте краулер с российского VPS/прокси.
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from .config import CrawlConfig

logger = logging.getLogger(__name__)


class BlockedByWafError(RuntimeError):
    """Похоже, запрос заблокирован WAF (типичный признак geo-блока sudrf.ru)."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    html: str
    content_type: str


_WAF_BLOCK_MARKERS = (
    "заблокирован по соображениям безопасности",
    "Ваш ip:",
)


def _fix_response_encoding(response: requests.Response) -> None:
    """requests угадывает кодировку HTML по заголовку Content-Type и, если
    там нет charset, откатывается на ISO-8859-1 (по HTTP-умолчанию), что
    даёт «кракозябры» для русскоязычных страниц без явного charset в
    заголовке. Подстраховываемся через apparent_encoding (chardet), которое
    смотрит на реальные байты/meta-теги страницы.
    """
    content_type = response.headers.get("Content-Type", "")
    if "charset" not in content_type.lower():
        response.encoding = response.apparent_encoding


class PoliteFetcher:
    """HTTP-клиент: rate-limit по домену, ретраи, проверка robots.txt."""

    def __init__(self, crawl_config: CrawlConfig):
        self._config = crawl_config
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": crawl_config.user_agent,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
            }
        )
        self._last_request_at: dict[str, float] = {}
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _throttle(self, domain: str) -> None:
        last = self._last_request_at.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            wait = self._config.request_delay_seconds - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_request_at[domain] = time.monotonic()

    def _robots_allows(self, url: str) -> bool:
        if not self._config.respect_robots_txt:
            return True
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots_cache.get(domain)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(domain + "/robots.txt")
            try:
                parser.read()
            except Exception:  # noqa: BLE001 - robots.txt может быть недоступен
                logger.warning("Не удалось прочитать robots.txt для %s, продолжаем", domain)
                parser = None
            self._robots_cache[domain] = parser
        if parser is None:
            return True
        return parser.can_fetch(self._config.user_agent, url)

    def fetch_page(self, url: str, max_retries: int = 3) -> FetchResult:
        """Скачивает страницу, соблюдая robots.txt и задержку между запросами.

        Если ответ похож на страницу geo-блока sudrf.ru, поднимает
        BlockedByWafError с понятным сообщением, а не молча отдаёт мусор.
        """
        if not self._robots_allows(url):
            raise PermissionError(f"robots.txt запрещает обход {url}")

        domain = urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            self._throttle(domain)
            try:
                response = self._session.get(
                    url, timeout=self._config.timeout_seconds, allow_redirects=True
                )
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("Попытка %s/%s для %s: %s", attempt, max_retries, url, exc)
                time.sleep(min(2**attempt, 20))
                continue

            _fix_response_encoding(response)

            body_preview = response.text[:2000] if response.text else ""
            if any(marker in body_preview for marker in _WAF_BLOCK_MARKERS):
                raise BlockedByWafError(
                    f"{url}: похоже на блокировку WAF по геолокации IP. "
                    "Запускайте краулер с российского сервера (см. README.md)."
                )

            return FetchResult(
                url=response.url,
                status_code=response.status_code,
                html=response.text,
                content_type=response.headers.get("Content-Type", ""),
            )

        raise ConnectionError(f"Не удалось получить {url} за {max_retries} попыток: {last_error}")
