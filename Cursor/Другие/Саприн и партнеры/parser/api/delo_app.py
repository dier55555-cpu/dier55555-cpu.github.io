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

from scraper.case_lookup.search import (
    CaseQuery,
    CaseSearchResult,
    VORONEZH_SUDRF_COURTS,
    search_case_direct,
)
from scraper.case_lookup.case_number import validate_case_number
from scraper.court_info import fetch_court_info, normalize_topic, website_to_origin
from scraper.fetch import Fetcher
from scraper.proxy_pool import proxies_from_env

app = FastAPI(title="court-kb delo", version="1.1.0")
log = logging.getLogger("delo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_last_good_proxy: Optional[str] = None
_LAST_GOOD_PROXY_PATH = "/opt/saprin/parser/.last_good_proxy"
# Кэш справок (website+topic), чтобы повтор Анны не долбил sudrf и не ловил TCP-ban.
_spravka_cache: dict[tuple[str, str], tuple[float, object]] = {}
_SPRAVKA_CACHE_TTL_SEC = 1800.0


def _load_last_good_proxy() -> None:
    global _last_good_proxy
    try:
        with open(_LAST_GOOD_PROXY_PATH, encoding="utf-8") as f:
            raw = f.read().strip()
        if raw.startswith("http"):
            _last_good_proxy = raw
    except OSError:
        pass


def _save_last_good_proxy(url: str) -> None:
    global _last_good_proxy
    _last_good_proxy = url
    try:
        with open(_LAST_GOOD_PROXY_PATH, "w", encoding="utf-8") as f:
            f.write(url)
    except OSError:
        pass


_load_last_good_proxy()


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


def _make_fetcher(*, info: bool = False) -> Fetcher:
    if info:
        return Fetcher(
            proxy_urls=[],
            delay_range=(0.0, 0.0),
            timeout=5.0,
            max_retries=1,
        )
    return Fetcher(
        proxy_urls=_ordered_proxies(),
        delay_range=(0.0, 0.0),
        timeout=16.0,
        max_retries=3,
    )


def _spravka_with_fallback(website: str, topic: str):
    """direct → до 2 sticky-прокси. Кэш 30 мин. Таймаут канала ≥ реального RTT sudrf (~3–8с)."""
    global _last_good_proxy
    origin = website_to_origin(website) or website.strip()
    cache_key = (origin.rstrip("/"), topic)
    now = time.monotonic()
    hit = _spravka_cache.get(cache_key)
    if hit and now - hit[0] < _SPRAVKA_CACHE_TTL_SEC:
        return hit[1], None, "cache"

    channels: list[Optional[str]] = [None]  # None = прямой IP VPS
    channels.extend(_ordered_proxies()[:2])

    last_result = None
    last_fetcher: Optional[Fetcher] = None
    used = ""
    # sudrf часто отвечает за 3–8с; слишком короткий timeout даёт ложный error.
    channel_timeout = 12.0
    for channel in channels:
        if channel is None:
            fetcher = Fetcher(proxy_urls=[], delay_range=(0.0, 0.0), timeout=channel_timeout, max_retries=1)
        else:
            fetcher = Fetcher(proxy_urls=[channel], delay_range=(0.0, 0.0), timeout=channel_timeout, max_retries=1)
        result = fetch_court_info(fetcher, website, topic=topic)
        last_result, last_fetcher = result, fetcher
        if result.status == "found":
            if channel:
                _save_last_good_proxy(channel)
                used = channel
            _spravka_cache[cache_key] = (now, result)
            return result, fetcher, used
        if result.status == "not_found":
            _spravka_cache[cache_key] = (now, result)
            return result, fetcher, used if channel else ""
    assert last_result is not None
    return last_result, last_fetcher, used


def _remember_proxy(fetcher: Optional[Fetcher], ok: bool) -> str:
    used = ""
    if fetcher is None:
        return used
    if fetcher.proxy_urls:
        used = fetcher.proxy_urls[fetcher._proxy_index % len(fetcher.proxy_urls)]
    if ok and used:
        _save_last_good_proxy(used)
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
    # Резолв суда из справочника РФ (БитриксЮрист).
    region: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    court_name: Optional[str] = None
    query: Optional[str] = None
    prefer_magistrate: Optional[bool] = None


class CaseLookupResponse(BaseModel):
    status: str
    result: str


class SpravkaRequest(BaseModel):
    website: str
    topic: str = "hours"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


from api.court_directory import resolve_court
from scraper.directory.normalize import sudrf_target


class CourtLookupRequest(BaseModel):
    region: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    court_name: Optional[str] = None
    query: Optional[str] = None
    prefer_magistrate: Optional[bool] = None
    limit: int = 5


def _domain_from_website(website: str) -> tuple[str, bool, bool]:
    domain, supported = sudrf_target(website)
    host = (domain or "").lower()
    return domain, supported, host.endswith(".msudrf.ru")


def _looks_unavailable(html: str) -> bool:
    low = (html or "").lower()
    return "временно недоступна" in low or "приносим свои извинения" in low


@app.post("/court_lookup")
def court_lookup(payload: CourtLookupRequest, x_api_key: Optional[str] = Header(default=None)) -> dict:
    _check_api_key(x_api_key)
    return resolve_court(
        region=payload.region or "",
        city=payload.city or "",
        district=payload.district or "",
        court_name=payload.court_name or "",
        free_text=payload.query or "",
        prefer_magistrate=payload.prefer_magistrate,
        limit=max(1, min(payload.limit or 5, 10)),
    )



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
    t0 = time.monotonic()
    result, fetcher, used = _spravka_with_fallback(website, topic)
    if used == "cache":
        port = "cache"
    elif used:
        port = _proxy_port(used)
    elif fetcher is not None and not fetcher.proxy_urls:
        port = "direct"
    else:
        port = _proxy_port(_remember_proxy(fetcher, result.status == "found")) if fetcher else "-"
    log.info(
        "spravka topic=%s site=%s status=%s port=%s dt=%.2fs",
        topic,
        website_to_origin(website),
        result.status,
        port,
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
    case_number = None
    case_number_raw = (payload.case_number or "").strip() or None
    if case_number_raw:
        parsed = validate_case_number(case_number_raw)
        if not parsed.ok:
            return CaseLookupResponse(
                status="error",
                result=parsed.error
                or "Некорректный номер дела. Нужен вид 2-1248/2026 (без «ДЕЛО №» и без ~ М-…).",
            )
        case_number = parsed.normalized
    last_name = (payload.last_name or "").strip() or None
    mode = (payload.mode or "").strip().lower()

    wants_info = mode in {"info", "spravka", "site"} or (
        website and not case_number and not last_name
    ) or (website and topic and topic.lower() not in {"case", "дело", ""})

    if wants_info and website:
        return spravka_lookup(SpravkaRequest(website=website, topic=topic or "hours"), x_api_key)

    # 1) явный website  2) справочник РФ  3) slug пилота Воронежа
    resolved_meta = ""
    domain = None
    if website:
        domain, _supported, _is_ms = _domain_from_website(website)
        if not domain:
            return CaseLookupResponse(status="error", result="Некорректный website суда.")
        resolved_meta = f"website={domain}"
    else:
        kb = resolve_court(
            region=payload.region or "",
            city=payload.city or "",
            district=payload.district or "",
            court_name=payload.court_name or "",
            free_text=payload.query or "",
            prefer_magistrate=payload.prefer_magistrate,
            limit=3,
        )
        if kb.get("status") == "found":
            court = kb.get("court") or {}
            website = court.get("website") or ""
            domain = court.get("parser_domain") or court.get("sudrf_domain") or ""
            resolved_meta = f"kb={court.get('code')}:{domain}"
        if not domain:
            domain = VORONEZH_SUDRF_COURTS.get(payload.court_slug or "")
            if domain:
                resolved_meta = f"slug={payload.court_slug}"
        if not domain:
            if website:
                return spravka_lookup(
                    SpravkaRequest(website=website, topic=topic or "hours"),
                    x_api_key,
                )
            return CaseLookupResponse(
                status="error",
                result=(
                    "Не удалось определить сайт суда. Укажите website или "
                    "region/city/district/court_name для поиска в справочнике РФ, "
                    "либо court_slug одного из воронежских райсудов."
                ),
            )
    if not case_number and not last_name:
        return CaseLookupResponse(status="error", result="Нужно указать case_number или last_name.")

    t0 = time.monotonic()
    result, used = _case_with_channels(
        domain,
        CaseQuery(case_number=case_number, last_name=last_name),
        production_type=payload.production_type,
    )
    # Если сайт вернул заглушку/капчу — говорим явно (не «таймаут прокси»).
    if result.status == "found" and result.cases:
        pass
    elif result.message and _looks_unavailable(result.message):
        result = CaseSearchResult("error", result.message)
    log.info(
        "delo slug=%s meta=%s q=%s raw_q=%s status=%s port=%s dt=%.2fs",
        payload.court_slug,
        resolved_meta,
        case_number or last_name,
        case_number_raw or "",
        result.status,
        _proxy_port(used) if used else "direct",
        time.monotonic() - t0,
    )
    out = result.as_text() if result.status == "found" else result.message
    if result.status not in {"found", "not_found"} and used:
        # после ошибки поиска проверим сырой HTML на капчу/заглушку одним коротким GET
        pass
    return CaseLookupResponse(status=result.status, result=out)


def _case_with_channels(domain: str, query: CaseQuery, production_type: str):
    """Карточка: last_good + остальные sticky, затем direct.

    Модуль sud_delo на ГАС часто подвисает (обычные страницы суда при этом живы).
    Короткий connect-timeout, быстрый перебор портов. Бюджет ≤50с под n8n 55с.
    Нужны до 2 HTTP (поиск + гидрация карточки) на успешном канале.
    """
    channels: list[Optional[str]] = list(_ordered_proxies()[:8])
    # Прямой IP VPS — запасной канал: главная суда с него открывается.
    channels.append(None)
    last_result = None
    used = ""
    t_budget = time.monotonic() + 50.0
    for channel in channels:
        if time.monotonic() >= t_budget:
            break
        remaining = max(5.0, t_budget - time.monotonic())
        # (connect, read): не ждать 20с на мёртвом туннеле.
        read_timeout = min(18.0, remaining)
        timeout = (4.0, read_timeout)
        if channel is None:
            fetcher = Fetcher(
                proxy_urls=[],
                delay_range=(0.0, 0.0),
                timeout=timeout,
                max_retries=1,
            )
            used_label = ""
        else:
            fetcher = Fetcher(
                proxy_urls=[channel],
                delay_range=(0.0, 0.0),
                timeout=timeout,
                max_retries=1,
            )
            used_label = channel
        result = search_case_direct(
            fetcher,
            domain,
            query,
            production_type=production_type,
        )
        last_result = result
        used = used_label
        if result.status in {"found", "not_found"}:
            if result.status == "found" and channel:
                _save_last_good_proxy(channel)
            return result, used
    if last_result is None:
        return (
            CaseSearchResult(
                "error",
                "Раздел «Судебное делопроизводство» на сайте суда сейчас не отвечает "
                "(поиск дел / карточка). Обычные страницы суда могут открываться. "
                "Попробуйте позже или откройте карточку вручную на сайте суда.",
            ),
            used,
        )
    return last_result, used
