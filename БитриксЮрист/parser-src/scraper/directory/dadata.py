"""Выгрузка справочника судов через DaData suggest (max 20 строк за запрос)."""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Optional

import requests

SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/court"
MAX_COUNT = 20
EXPAND_CHARS = "0123456789"
DEFAULT_TYPES = ("RS", "OS", "AJ", "KJ", "VS")
ALL_GENERAL_TYPES = DEFAULT_TYPES + ("MS",)

# Коды субъектов в идентификаторах судов ГАС «Правосудие» — 00..99.
# Часть номеров не совпадает с привычным ОКАТО (02 = Алтай, 03 = Башкортостан).
REGION_PREFIXES = [f"{i:02d}" for i in range(100)]


class DaDataCourtClient:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None, timeout: float = 30.0):
        if not api_key:
            raise ValueError("Нужен DADATA_API_KEY")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.calls = 0

    def _post(self, url: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {self.api_key}",
        }
        last_error: Optional[Exception] = None
        for attempt in range(4):
            try:
                self.calls += 1
                response = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
                if response.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(0.4 * (attempt + 1))
                    last_error = RuntimeError(f"DaData HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                body = response.json() or {}
                return list(body.get("suggestions") or [])
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"DaData недоступен: {last_error}")

    def suggest(self, query: str, court_type: Optional[str] = None, count: int = MAX_COUNT) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"query": query, "count": min(count, MAX_COUNT)}
        if court_type:
            payload["filters"] = [{"court_type": court_type}]
        rows = []
        for item in self._post(SUGGEST_URL, payload):
            data = item.get("data") or {}
            if data.get("code"):
                rows.append(data)
        return rows


def walk_prefix(
    suggest: Callable[[str, Optional[str]], list[dict[str, Any]]],
    prefix: str,
    court_type: str,
    *,
    max_depth: int = 12,
) -> list[dict[str, Any]]:
    """Рекурсивно расширяет префикс кода, пока DaData не перестаёт обрезать выдачу на 20."""
    rows = suggest(prefix, court_type)
    matching = [row for row in rows if str(row.get("code") or "").upper().startswith(prefix.upper())]
    if len(rows) < MAX_COUNT or len(prefix) >= max_depth:
        return matching
    collected: dict[str, dict[str, Any]] = {}
    for char in EXPAND_CHARS:
        for row in walk_prefix(suggest, prefix + char, court_type, max_depth=max_depth):
            collected[row["code"]] = row
    return list(collected.values())


def dump_courts(
    client: DaDataCourtClient,
    court_types: Iterable[str] = DEFAULT_TYPES,
    *,
    pause: float = 0.05,
    progress: Optional[Callable[[str], None]] = None,
) -> list[dict[str, Any]]:
    """Полный обход кодов {region}{type}… для выбранных типов судов."""
    by_code: dict[str, dict[str, Any]] = {}
    types = tuple(court_types) or DEFAULT_TYPES

    def suggest_and_pause(query: str, court_type: Optional[str]) -> list[dict[str, Any]]:
        rows = client.suggest(query, court_type)
        if pause:
            time.sleep(pause)
        return rows

    for court_type in types:
        for region in REGION_PREFIXES:
            prefix = f"{region}{court_type}"
            batch = walk_prefix(suggest_and_pause, prefix, court_type)
            for row in batch:
                by_code[row["code"]] = row
            if progress:
                progress(f"{prefix}: +{len(batch)}, всего {len(by_code)}, запросов {client.calls}")

    # Верховный Суд РФ кодируется как 00VS0000 — на случай если 00VS уже обошли.
    if "VS" in types and "00VS0000" not in by_code:
        for row in client.suggest("00VS", "VS"):
            by_code[row["code"]] = row

    return [by_code[key] for key in sorted(by_code)]
