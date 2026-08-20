"""Тонкий HTTP-сервис слоя 2: только /health и POST /delo.

Ставится на VPS рядом с прокси. n8n Нои не ходит на sudrf сам —
только POST сюда {court_slug, case_number|last_name}.
"""

from __future__ import annotations

import os
import random
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from scraper.case_lookup.search import CaseQuery, VORONEZH_SUDRF_COURTS, search_case_direct
from scraper.fetch import Fetcher
from scraper.proxy_pool import proxies_from_env

app = FastAPI(title="court-kb delo", version="1.0.0")


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

    proxy_urls = proxies_from_env()
    random.shuffle(proxy_urls)
    fetcher = Fetcher(
        proxy_urls=proxy_urls,
        delay_range=(0.0, 0.0),
        timeout=12.0,
        max_retries=2,
    )
    result = search_case_direct(
        fetcher,
        domain,
        CaseQuery(case_number=case_number, last_name=last_name),
        production_type=payload.production_type,
    )
    text = result.as_text() if result.status == "found" else result.message
    return CaseLookupResponse(status=result.status, result=text)
