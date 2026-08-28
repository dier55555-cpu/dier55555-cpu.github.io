"""Справочник судов РФ + поиск по региону/городу/району/названию."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from scraper.directory.lookup import load_directory, lookup_courts
from scraper.directory.normalize import CourtRecord, sudrf_target

log = logging.getLogger("court-directory")

DEFAULT_DIR = Path("/opt/saprin/parser/directory/courts-ru.json")


@lru_cache(maxsize=1)
def get_records(path: str = str(DEFAULT_DIR)) -> tuple[CourtRecord, ...]:
    records = load_directory(path)
    log.info("Court directory loaded: %s records from %s", len(records), path)
    return tuple(records)


def record_to_dict(record: CourtRecord) -> dict[str, Any]:
    return {
        "code": record.code,
        "name": record.name,
        "court_type": record.court_type,
        "court_type_name": record.court_type_name,
        "region": record.region,
        "city": record.city,
        "district": record.district,
        "address": record.address,
        "website": record.website,
        "sudrf_domain": record.sudrf_domain,
        "parser_supported": record.parser_supported,
        "is_magistrate": record.court_type.upper() == "MS",
    }


def build_query(
    *,
    region: str = "",
    city: str = "",
    district: str = "",
    court_name: str = "",
    free_text: str = "",
) -> str:
    parts = [p.strip() for p in (court_name, district, city, region, free_text) if p and str(p).strip()]
    return " ".join(parts)


def resolve_court(
    *,
    region: str = "",
    city: str = "",
    district: str = "",
    court_name: str = "",
    free_text: str = "",
    prefer_magistrate: Optional[bool] = None,
    limit: int = 5,
) -> dict[str, Any]:
    query = build_query(
        region=region,
        city=city,
        district=district,
        court_name=court_name,
        free_text=free_text,
    )
    if not query:
        return {"status": "error", "result": "Нужны регион/город/район/название суда или свободный текст.", "matches": []}

    qn = query.lower()
    if prefer_magistrate is True or "миров" in qn or "участок" in qn:
        court_types = ("MS",)
    elif prefer_magistrate is False:
        court_types = ("RS", "OS", "AJ", "KJ", "VS")
    else:
        court_types = None  # lookup_courts сам отрежет MS, если нет слов «мировой/участок»

    matches = lookup_courts(query, get_records(), limit=limit, court_types=court_types)
    if not matches:
        # повтор без фильтра типов
        matches = lookup_courts(query, get_records(), limit=limit, court_types=None)
    if not matches:
        return {"status": "not_found", "result": f"Суд по запросу «{query}» не найден в справочнике.", "matches": [], "query": query}

    best = matches[0]
    domain, supported = sudrf_target(best.website)
    payload = record_to_dict(best)
    payload["parser_domain"] = domain or best.sudrf_domain
    payload["live_case_supported"] = bool(supported) or best.court_type.upper() == "MS"
    return {
        "status": "found",
        "result": f"{best.name} → {best.website}",
        "query": query,
        "court": payload,
        "matches": [record_to_dict(m) for m in matches],
    }
