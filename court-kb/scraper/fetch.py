"""
Низкоуровневый HTTP-слой для обхода сайтов судов (шаблон ГАС «Правосудие»).

Важно: эти сайты блокируют запросы с иностранных (не-РФ) IP на уровне WAF —
это подтверждено вручную (см. README, раздел "Проверка блокировки"). Поэтому
запускать этот скрипт нужно с сервера/прокси с российским IP. Отсюда (из
облачного окружения агента) сайты недоступны — вы увидите статус "blocked"
в отчёте.
"""

from __future__ import annotations

import random
import re
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

_META_CHARSET_RE = re.compile(rb'charset=["\']?([a-zA-Z0-9_-]+)', re.IGNORECASE)


def _decode_body(content: bytes, header_encoding: Optional[str]) -> str:
    """Многие сайты судов не отдают charset в заголовке Content-Type, из-за чего
    requests по умолчанию скатывается в latin-1 и текст превращается в кракозябры.
    Приоритет: charset из <meta>, затем из заголовка, затем utf-8 с заменой ошибок.
    """
    match = _META_CHARSET_RE.search(content[:2048])
    for candidate in (match.group(1).decode("ascii") if match else None, header_encoding, "utf-8"):
        if not candidate:
            continue
        try:
            return content.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")

# Типовой текст блокировочной страницы ГАС «Правосудие» при запросе с
# не-российского/подозрительного IP. Если он встречается в ответе - значит
# контент не дошёл до нас, а перед нами страница блокировки WAF.
BLOCK_MARKERS = (
    "заблокирован по соображениям безопасности",
    "Судебный департамент при Верховном Суде Российской Федерации",
    "Данный запрос некорректен",
)

# Замените contact-url на реальный адрес/страницу с контактами клиента —
# это принятая практика для идентификации бота, но сама строка должна быть
# ASCII (иначе HTTP-заголовок будет невалиден).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "court-kb-bot/1.0 (+https://example.com/bot-contact)"
)

# Подтверждено экспериментально: с обычным набором заголовков requests (только
# User-Agent) сайты ГАС «Правосудие» даже с российского резидентного IP
# отвечают "Данный запрос некорректен, просьба изменить параметры запроса (B)"
# — WAF ждёт заголовки, типичные для настоящего браузера. Без них запрос
# считается подозрительным и блокируется отдельно от гео-проверки.
BROWSER_LIKE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class FetchResult:
    url: str
    ok: bool
    blocked: bool
    status_code: Optional[int]
    html: Optional[str]
    error: Optional[str] = None


@dataclass
class Fetcher:
    """Обёртка над requests.Session с ретраями, паузами и детектом блокировки.

    proxies: например {"https": "http://user:pass@ru-proxy-host:port"} —
    сюда передаётся российский прокси/VPS, без него сайты недоступны.
    delay_range: пауза между запросами (сек), чтобы не грузить гос. сайт.
    """

    proxies: Optional[dict] = None
    delay_range: tuple[float, float] = (2.0, 5.0)
    timeout: float = 20.0
    max_retries: int = 3
    user_agent: str = DEFAULT_USER_AGENT
    session: requests.Session = field(default_factory=requests.Session)
    _robots_cache: dict = field(default_factory=dict)

    def _sleep(self) -> None:
        time.sleep(random.uniform(*self.delay_range))

    def allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_cache.get(origin)
        if rp is None:
            rp = robotparser.RobotFileParser()
            robots_url = urljoin(origin, "/robots.txt")
            try:
                resp = self.session.get(
                    robots_url,
                    headers={"User-Agent": self.user_agent, **BROWSER_LIKE_HEADERS},
                    proxies=self.proxies,
                    timeout=self.timeout,
                )
                robots_text = _decode_body(resp.content, resp.encoding)
                if resp.status_code == 200 and not self._looks_blocked(robots_text):
                    rp.parse(robots_text.splitlines())
                else:
                    # robots.txt недоступен/заблокирован — по умолчанию не блокируем,
                    # но это стоит перепроверить руками при запуске с боевого IP.
                    rp.parse([])
            except requests.RequestException:
                rp.parse([])
            self._robots_cache[origin] = rp
        return rp.can_fetch(self.user_agent, url)

    @staticmethod
    def _looks_blocked(html: str) -> bool:
        return any(marker in html for marker in BLOCK_MARKERS)

    def get(self, url: str, respect_robots: bool = True) -> FetchResult:
        return self.request("GET", url, respect_robots=respect_robots)

    def post(self, url: str, data: dict, respect_robots: bool = True) -> FetchResult:
        return self.request("POST", url, data=data, respect_robots=respect_robots)

    def request(self, method: str, url: str, params: Optional[dict] = None,
                data: Optional[dict] = None, respect_robots: bool = True) -> FetchResult:
        if respect_robots and not self.allowed_by_robots(url):
            return FetchResult(url, ok=False, blocked=False, status_code=None,
                                html=None, error="disallowed by robots.txt")

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers={"User-Agent": self.user_agent, **BROWSER_LIKE_HEADERS},
                    proxies=self.proxies,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                network_block_markers = (
                    "Connection reset by peer",
                    "RemoteDisconnected",
                    "ConnectTimeoutError",
                    "Connection to",  # requests' "Connection to <host> timed out" message
                )
                if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError)) and any(
                    marker in last_error for marker in network_block_markers
                ):
                    # Похоже на блокировку на уровне TCP/сети (SYN просто не долетает,
                    # либо соединение рвётся) — тот же эффект, что и HTML-страница с
                    # объяснением, но без неё. Подтверждено даже с российских
                    # хостинг-провайдеров (не только с иностранных IP) — см. README.
                    return FetchResult(url, ok=False, blocked=True, status_code=None,
                                        html=None, error=f"network-level block? ({last_error})")
                self._sleep()
                continue

            html = _decode_body(resp.content, resp.encoding)

            if self._looks_blocked(html):
                return FetchResult(url, ok=False, blocked=True, status_code=resp.status_code,
                                    html=html, error="WAF block page (geo/IP)")

            if resp.status_code >= 500 and attempt < self.max_retries:
                last_error = f"HTTP {resp.status_code}"
                self._sleep()
                continue

            self._sleep()
            return FetchResult(url, ok=resp.status_code == 200, blocked=False,
                                status_code=resp.status_code, html=html)

        return FetchResult(url, ok=False, blocked=False, status_code=None,
                            html=None, error=last_error or "unknown error")

    def get_bytes(self, url: str) -> Optional[bytes]:
        """Скачивает бинарный ресурс (например, картинку капчи) без декодирования в текст."""
        try:
            resp = self.session.get(
                url,
                headers={"User-Agent": self.user_agent, **BROWSER_LIKE_HEADERS},
                proxies=self.proxies,
                timeout=self.timeout,
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        return resp.content
