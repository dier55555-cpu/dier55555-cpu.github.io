"""Тонкий HTTP-сервис слоя 2: только /health и POST /delo.

Ставится на VPS рядом с прокси. n8n Нои не ходит на sudrf сам —
только POST сюда {court_slug, case_number|last_name}.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from scraper.case_lookup.search import CaseQuery, VORONEZH_SUDRF_COURTS, search_case_direct
from scraper.fetch import Fetcher
from scraper.proxy_pool import proxies_from_env

app = FastAPI(title="court-kb delo", version="1.0.0")
log = logging.getLogger("delo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_last_good_proxy: Optional[str] = None


def _ordered_proxies() -> list[str]:
    urls = proxies_from_env()
    random.shuffle(urls)
    if _last_good_proxy and _last_good_proxy in urls:
        urls.remove(_last_good_proxy)
        urls.insert(0, _last_good_proxy)
    return urls


def _proxy_port(url: str) -> str:
    try:
        return str(urlparse(url).port or "?")
    except Exception:
        return "?"


def _check_api_key(x_api_key: Optional[str]) -> None:
    expected = os.environ.get("COURT_KB_API_KEY")
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-API-Key")


class CaseLookupRequest(BaseModel):
    court_slug: str
    case_number: Optional[str] = None
    last_name: Optional[str] = None
    production_type: str = "civil_first_instance"


class CaseLookupResponse(BaseModel):
    status: str
    result: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/delo", response_model=CaseLookupResponse)
def delo_lookup(payload: CaseLookupRequest, x_api_key: Optional[str] = Header(default=None)) -> CaseLookupResponse:
    global _last_good_proxy
    _check_api_key(x_api_key)
    domain = VORONEZH_SUDRF_COURTS.get(payload.court_slug)
    if domain is None:
        allowed = ", ".join(VORONEZH_SUDRF_COURTS)
        return CaseLookupResponse(
            status="error",
            result=f"Неизвестный суд '{payload.court_slug}'. Допустимые: {allowed}.",
        )
    case_number = (payload.case_number or "").strip() or None
    last_name = (payload.last_name or "").strip() or None
    if not case_number and not last_name:
        return CaseLookupResponse(status="error", result="Нужно указать case_number или last_name.")

    proxy_urls = _ordered_proxies()
    fetcher = Fetcher(
        proxy_urls=proxy_urls,
        delay_range=(0.0, 0.0),
        timeout=16.0,
        max_retries=3,
    )
    t0 = time.monotonic()
    result = search_case_direct(
        fetcher,
        domain,
        CaseQuery(case_number=case_number, last_name=last_name),
        production_type=payload.production_type,
    )
    elapsed = time.monotonic() - t0
    used = ""
    if fetcher.proxy_urls:
        used = fetcher.proxy_urls[fetcher._proxy_index % len(fetcher.proxy_urls)]
    if result.status in {"found", "not_found"} and used:
        _last_good_proxy = used
    log.info(
        "delo slug=%s q=%s status=%s port=%s dt=%.2fs",
        payload.court_slug,
        case_number or last_name,
        result.status,
        _proxy_port(used) if used else "-",
        elapsed,
    )
    text = result.as_text() if result.status == "found" else result.message
    return CaseLookupResponse(status=result.status, result=text)
