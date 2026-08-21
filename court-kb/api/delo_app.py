"""Тонкий HTTP-сервис слоя 2: /health, POST /delo (карточка), POST /spravka (справка с сайта).

n8n Нои не ходит на sudrf сам — только POST сюда.
Карточка дела: {court_slug, case_number|last_name} — пока 6 райсудов Воронежа.
Справка (режим/контакты/…): {website, topic} — любой официальный сайт суда из БЗ.
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
from scraper.court_info import fetch_court_info, normalize_topic, website_to_origin
from scraper.fetch import Fetcher
from scraper.proxy_pool import proxies_from_env

app = FastAPI(title="court-kb delo", version="1.1.0")
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


def _make_fetcher() -> Fetcher:
    return Fetcher(
        proxy_urls=_ordered_proxies(),
        delay_range=(0.0, 0.0),
        timeout=16.0,
        max_retries=3,
    )


def _remember_proxy(fetcher: Fetcher, ok: bool) -> str:
    global _last_good_proxy
    used = ""
    if fetcher.proxy_urls:
        used = fetcher.proxy_urls[fetcher._proxy_index % len(fetcher.proxy_urls)]
    if ok and used:
        _last_good_proxy = used
    return used


class CaseLookupRequest(BaseModel):
    court_slug: Optional[str] = None
    case_number: Optional[str] = None
    last_name: Optional[str] = None
    production_type: str = "civil_first_instance"
    # Справка с сайта (тот же вебхук «Дело» может прислать website+topic).
    website: Optional[str] = None
    topic: Optional[str] = None
    mode: Optional[str] = None  # case | info


class CaseLookupResponse(BaseModel):
    status: str
    result: str


class SpravkaRequest(BaseModel):
    website: str
    topic: str = "hours"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/spravka", response_model=CaseLookupResponse)
def spravka_lookup(payload: SpravkaRequest, x_api_key: Optional[str] = Header(default=None)) -> CaseLookupResponse:
    global _last_good_proxy
    _check_api_key(x_api_key)
    website = (payload.website or "").strip()
    if not website_to_origin(website):
        return CaseLookupResponse(
            status="error",
            result="Нужна ссылка на официальный сайт суда (поле САЙТ из справочника).",
        )
    topic = normalize_topic(payload.topic)
    fetcher = _make_fetcher()
    t0 = time.monotonic()
    result = fetch_court_info(fetcher, website, topic=topic)
    used = _remember_proxy(fetcher, result.status == "found")
    log.info(
        "spravka topic=%s site=%s status=%s port=%s dt=%.2fs",
        topic,
        website_to_origin(website),
        result.status,
        _proxy_port(used) if used else "-",
        time.monotonic() - t0,
    )
    text = result.as_text() if result.status == "found" else result.message
    return CaseLookupResponse(status=result.status, result=text)


@app.post("/delo", response_model=CaseLookupResponse)
def delo_lookup(payload: CaseLookupRequest, x_api_key: Optional[str] = Header(default=None)) -> CaseLookupResponse:
    """Единая точка для действия «Дело»: карточка ИЛИ справка с сайта."""
    _check_api_key(x_api_key)

    website = (payload.website or "").strip() or None
    topic = (payload.topic or "").strip() or None
    case_number = (payload.case_number or "").strip() or None
    last_name = (payload.last_name or "").strip() or None
    mode = (payload.mode or "").strip().lower()

    wants_info = mode in {"info", "spravka", "site"} or (
        website and not case_number and not last_name
    ) or (website and topic and topic.lower() not in {"case", "дело", ""})

    if wants_info and website:
        return spravka_lookup(SpravkaRequest(website=website, topic=topic or "hours"), x_api_key)

    domain = VORONEZH_SUDRF_COURTS.get(payload.court_slug or "")
    if domain is None:
        if website:
            # Суд не из 6 Воронежа, но есть сайт — отдаём справку, не карточку.
            return spravka_lookup(
                SpravkaRequest(website=website, topic=topic or "hours"),
                x_api_key,
            )
        allowed = ", ".join(VORONEZH_SUDRF_COURTS)
        return CaseLookupResponse(
            status="error",
            result=(
                f"Живая карточка дела сейчас только для: {allowed}. "
                "Для режима работы/контактов передайте website (САЙТ из БЗ) и topic."
            ),
        )
    if not case_number and not last_name:
        return CaseLookupResponse(status="error", result="Нужно указать case_number или last_name.")

    fetcher = _make_fetcher()
    t0 = time.monotonic()
    result = search_case_direct(
        fetcher,
        domain,
        CaseQuery(case_number=case_number, last_name=last_name),
        production_type=payload.production_type,
    )
    used = _remember_proxy(fetcher, result.status in {"found", "not_found"})
    log.info(
        "delo slug=%s q=%s status=%s port=%s dt=%.2fs",
        payload.court_slug,
        case_number or last_name,
        result.status,
        _proxy_port(used) if used else "-",
        time.monotonic() - t0,
    )
    text = result.as_text() if result.status == "found" else result.message
    return CaseLookupResponse(status=result.status, result=text)
