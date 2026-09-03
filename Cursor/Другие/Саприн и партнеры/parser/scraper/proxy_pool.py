"""Пул HTTP(S)-прокси: несколько URL или несколько портов одного gateway.

Для proxy.market (и похожих sticky-пулов) один логин/пароль на host, а каждый
порт — отдельная sticky-сессия с своим исходящим IP. Если один IP ловит
503/WAF на sudrf.ru, другой порт того же аккаунта часто ещё живой.

COURT_KB_PROXY — один URL или список через запятую/точку с запятой.
COURT_KB_PROXY_PORTS — «10001-10010» или «10001,10002,10006»: подставляет
эти порты в host первого URL из COURT_KB_PROXY.
COURT_KB_PROXY_BACKUP / COURT_KB_PROXY_BACKUP_PORTS — второй аккаунт:
если основной шлюз не открыл дело, тот же запрос идёт на резерв.
"""

from __future__ import annotations

import os
import queue
import threading
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse


def parse_proxy_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    items: list[str] = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        item = chunk.strip()
        if item:
            items.append(item)
    return items


def parse_ports(raw: str | None) -> list[int]:
    if not raw:
        return []
    ports: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        item = chunk.strip()
        if not item:
            continue
        if "-" in item:
            start_s, end_s = item.split("-", 1)
            start, end = int(start_s), int(end_s)
            if end < start or end - start > 50:
                raise ValueError(f"некорректный диапазон портов: {item}")
            ports.extend(range(start, end + 1))
        else:
            ports.append(int(item))
    return ports


def with_port(proxy_url: str, port: int) -> str:
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        raise ValueError(f"некорректный URL прокси: {proxy_url}")
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += ":" + parsed.password
        userinfo += "@"
    netloc = f"{userinfo}{parsed.hostname}:{port}"
    return urlunparse((parsed.scheme or "http", netloc, parsed.path, "", parsed.query, ""))


def expand_ports(base_url: str, ports: list[int]) -> list[str]:
    return [with_port(base_url, port) for port in ports]


def proxies_from_env(
    proxy: str | None = None,
    ports: str | None = None,
) -> list[str]:
    """Собирает список прокси из строки/окружения.

    Если заданы и URL, и порты — каждый URL раскрывается по портам.
    Иначе возвращается список URL как есть (один элемент = без ротации).
    """
    raw_proxy = proxy if proxy is not None else os.environ.get("COURT_KB_PROXY")
    raw_ports = ports if ports is not None else os.environ.get("COURT_KB_PROXY_PORTS")
    urls = parse_proxy_list(raw_proxy)
    port_list = parse_ports(raw_ports)
    if urls and port_list:
        expanded: list[str] = []
        for url in urls:
            expanded.extend(expand_ports(url, port_list))
        return expanded
    return urls


def backup_proxies_from_env() -> list[str]:
    """Второй аккаунт прокси (отдельный login). Пусто, если резерва нет."""
    raw = os.environ.get("COURT_KB_PROXY_BACKUP")
    if not (raw or "").strip():
        return []
    ports = os.environ.get("COURT_KB_PROXY_BACKUP_PORTS") or os.environ.get(
        "COURT_KB_PROXY_PORTS"
    )
    return proxies_from_env(raw, ports)


def is_proxy_failure(error: str) -> bool:
    """Любая сетевая/прокси-ошибка, после которой имеет смысл повторить запрос."""
    text = (error or "").lower()
    markers = (
        "503",
        "504",
        "node has rejected",
        "tunnel connection failed",
        "unable to connect to proxy",
        "proxyerror",
        "connecttimeout",
        "read timed out",
        "readtimeout",
        "proxy connect aborted",
    )
    return any(m in text for m in markers)


def is_dead_proxy(error: str) -> bool:
    """Порт/IP прокси мёртв — надо сменить sticky-порт, а не долбить тот же.

    Read timeout сюда не входит: к sudrf первый CONNECT часто срывается,
    а повтор по той же сессии (keep-alive) уже проходит.
    """
    text = (error or "").lower()
    if "read timed out" in text or "readtimeout" in text:
        return False
    markers = (
        "503",
        "504",
        "node has rejected",
        "tunnel connection failed",
        "unable to connect to proxy",
        "proxy connect aborted",
        "407",
    )
    return any(m in text for m in markers)


class StickyLeasePool:
    """Параллельные /delo не делят sticky-порт: каждый держит свой до конца."""

    def __init__(self) -> None:
        self._q: queue.Queue[str | None] = queue.Queue()
        self._ready = False
        self._lock = threading.Lock()
        self.size = 0

    def reset(self, urls: list[str] | None = None) -> None:
        urls = urls if urls is not None else proxies_from_env()
        with self._lock:
            while True:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
            if not urls:
                self._q.put(None)
                self.size = 0
            else:
                for u in urls:
                    self._q.put(u)
                self.size = len(urls)
            self._ready = True

    def _ensure(self) -> None:
        if not self._ready:
            self.reset()

    @contextmanager
    def lease(self, timeout: float = 45.0):
        self._ensure()
        url = self._q.get(timeout=timeout)
        try:
            yield url
        finally:
            self._q.put(url)


_LEASE = StickyLeasePool()
_LEASE_BACKUP = StickyLeasePool()


def lease_sticky_proxy(timeout: float = 45.0):
    return _LEASE.lease(timeout=timeout)


def lease_sticky_backup_proxy(timeout: float = 45.0):
    urls = backup_proxies_from_env()
    if urls and _LEASE_BACKUP.size != len(urls):
        _LEASE_BACKUP.reset(urls)
    return _LEASE_BACKUP.lease(timeout=timeout)
