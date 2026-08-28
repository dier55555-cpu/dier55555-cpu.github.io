"""Параллельный разбор карточек: N разных судов сразу, один хост — очередь.

VPS 2 CPU / 2 ГБ: узкое место — сеть/прокси до sudrf, не CPU.
Поэтому PARSE_CONCURRENCY=6 — это 6 ожиданий HTTP, не 6 тяжёлых процессов.
"""

from __future__ import annotations

import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Semaphore
from typing import Callable, Iterable, Optional, TypeVar
from urllib.parse import urlparse

T = TypeVar("T")
R = TypeVar("R")


def court_host(website: Optional[str]) -> str:
    if not website:
        return ""
    try:
        return (urlparse(website).hostname or "").lower()
    except Exception:
        return ""


def interleave_by_host(items: Iterable[T], host_of: Callable[[T], str]) -> list[T]:
    """Чередуем суды, чтобы пул сразу взял разные хосты, а не 6 дел одного райсуда."""
    buckets: dict[str, list[T]] = defaultdict(list)
    for item in items:
        buckets[host_of(item)].append(item)
    queues = [q for q in buckets.values() if q]
    out: list[T] = []
    while queues:
        nxt: list[list[T]] = []
        for q in queues:
            out.append(q.pop(0))
            if q:
                nxt.append(q)
        queues = nxt
    return out


class CourtParsePool:
    """До `concurrency` запросов сразу; на один hostname — не больше одного."""

    def __init__(self, concurrency: int, host_pause_sec: float = 0.0):
        self.concurrency = max(1, int(concurrency))
        self.host_pause_sec = max(0.0, float(host_pause_sec))
        self._hosts: dict[str, Semaphore] = {}
        self._mu = Lock()

    def _host_sem(self, host: str) -> Semaphore:
        with self._mu:
            sem = self._hosts.get(host)
            if sem is None:
                sem = Semaphore(1)
                self._hosts[host] = sem
            return sem

    def run(
        self,
        items: list[T],
        host_of: Callable[[T], str],
        fn: Callable[[T], R],
    ) -> list[tuple[T, R, Optional[BaseException]]]:
        ordered = interleave_by_host(items, host_of)
        results: list[tuple[T, R, Optional[BaseException]]] = []

        def _call(item: T) -> tuple[T, R, Optional[BaseException]]:
            host = host_of(item)
            with self._host_sem(host):
                try:
                    value = fn(item)
                    err: Optional[BaseException] = None
                except BaseException as exc:  # noqa: BLE001 — отдаём в job
                    value = None  # type: ignore[assignment]
                    err = exc
                if self.host_pause_sec:
                    time.sleep(self.host_pause_sec)
                return item, value, err

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futs = [pool.submit(_call, item) for item in ordered]
            for fut in as_completed(futs):
                results.append(fut.result())
        return results
