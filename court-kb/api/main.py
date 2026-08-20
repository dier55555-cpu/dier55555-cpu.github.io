"""
HTTP-обёртка над scraper/mcp_server для интеграции через вебхук — например,
из n8n (нода HTTP Request) или напрямую из конструктора агента в НОЕ, если
там проще подключить обычный HTTP endpoint, а не MCP stdio-сервер.

Идея: вся "умная" логика (эвристический разбор формы/капчи/карточки дела,
детект блокировки, извлечение текста) остаётся в Python и покрыта тестами
(см. ../tests). Этот файл — только тонкий HTTP-слой поверх неё, чтобы n8n
или сама НОЕ могли дёрнуть её по сети одним POST-запросом, без необходимости
переписывать эвристики на JS внутри n8n Code-нод.

Запуск:

    export COURT_KB_API_KEY="сложный-случайный-ключ"   # обязателен, если сервис смотрит в интернет
    export COURT_KB_PROXY="http://user:pass@ru-proxy:port"  # если сервер сам НЕ в РФ
    export TWOCAPTCHA_API_KEY="..."                         # если на форме суда есть капча
    uvicorn api.main:app --host 0.0.0.0 --port 8080

Дальше в n8n: HTTP Request node -> POST http://<этот-сервер>:8080/case-lookup,
заголовок X-API-Key, JSON-тело с court_slug/case_number/last_name.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import json

import yaml
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from scraper.case_lookup.search import (
    CaseQuery,
    VORONEZH_SUDRF_COURTS,
    search_case,
    search_case_direct,
)
from scraper.crawl import crawl_court
from scraper.directory.lookup import load_directory, lookup_courts
from scraper.fetch import Fetcher


def _load_courts_config(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {c["slug"]: c for c in data.get("courts", [])}


def _build_fetcher() -> Fetcher:
    from scraper.proxy_pool import proxies_from_env

    proxy_urls = proxies_from_env()
    return Fetcher(
        proxy_urls=proxy_urls,
        delay_range=(0.6, 1.2),
        timeout=30,
        max_retries=2,
    )


def _build_captcha_solver():
    from scraper.case_lookup.captcha import ManualCaptchaSolver, TwoCaptchaSolver

    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if api_key:
        return TwoCaptchaSolver(api_key=api_key)
    if os.environ.get("COURT_KB_MANUAL_CAPTCHA") == "1":
        return ManualCaptchaSolver()
    return None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = Path(os.environ.get("COURT_KB_CORPUS", PROJECT_ROOT / "data" / "corpus.jsonl"))
COURTS_CONFIG_PATH = Path(os.environ.get("COURT_KB_COURTS_CONFIG", PROJECT_ROOT / "courts.yaml"))
DIRECTORY_PATH = Path(os.environ.get("COURT_KB_DIRECTORY", PROJECT_ROOT / "directory" / "courts-ru.json"))

app = FastAPI(
    title="court-kb API",
    description="Слой 1 (поиск по БЗ) и слой 2 (живой поиск дела) для сайтов судов ГАС «Правосудие»",
    version="1.0.0",
)


def _check_api_key(x_api_key: Optional[str]) -> None:
    expected = os.environ.get("COURT_KB_API_KEY")
    if not expected:
        return  # ключ не настроен — считаем, что сервис вызывается из закрытой сети (не рекомендуется для интернета)
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-API-Key")


class KbSearchRequest(BaseModel):
    query: str
    court_slug: Optional[str] = None
    top_k: int = 3


class KbSearchResponse(BaseModel):
    result: str


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


@app.api_route("/courts", methods=["GET", "POST"])
def list_courts(x_api_key: Optional[str] = Header(default=None)) -> dict:
    """Список судов из courts.yaml — агент/n8n используют, чтобы выбрать court_slug."""
    _check_api_key(x_api_key)
    courts_config = _load_courts_config(COURTS_CONFIG_PATH)
    courts = []
    for slug, court in sorted(courts_config.items()):
        case_search = court.get("case_search") or {}
        courts.append({
            "slug": slug,
            "name": court["name"],
            "base_url": court["base_url"],
            "case_search_enabled": bool(case_search.get("enabled")),
            "production_types": list((case_search.get("production_types") or {}).keys()),
        })
    return {"courts": courts}


class CourtResolveRequest(BaseModel):
    query: str
    limit: int = 5


@app.post("/courts/resolve")
def resolve_court(
    payload: CourtResolveRequest,
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    """Локальный справочник: «Ленинский район г. Ставрополь» → сайт суда, без DaData."""
    _check_api_key(x_api_key)
    text = (payload.query or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Нужно указать query")
    cap = payload.limit
    if not DIRECTORY_PATH.exists():
        return {
            "query": text,
            "matches": [],
            "status": "no_directory",
            "result": (
                "Справочник судов ещё не выгружен. "
                "Запустите python -m scraper.directory.dump"
            ),
        }
    records = load_directory(DIRECTORY_PATH)
    matches = lookup_courts(text, records, limit=max(1, min(cap, 20)))
    return {
        "query": text,
        "status": "ok" if matches else "not_found",
        "matches": [
            {
                "code": item.code,
                "name": item.name,
                "court_type": item.court_type,
                "region": item.region,
                "city": item.city,
                "district": item.district,
                "address": item.address,
                "website": item.website,
                "sudrf_domain": item.sudrf_domain,
                "parser_supported": item.parser_supported,
                "base_url": f"https://{item.sudrf_domain}/" if item.sudrf_domain else "",
            }
            for item in matches
        ],
    }


@app.get("/corpus/export")
def corpus_export(x_api_key: Optional[str] = Header(default=None)) -> dict:
    """Выгрузка собранного корпуса (слой 1) для заливки в БЗ агента через n8n."""
    from mcp_server.server import load_corpus

    _check_api_key(x_api_key)
    entries = load_corpus(CORPUS_PATH)
    return {
        "count": len(entries),
        "documents": [
            {
                "court_slug": e.court_slug,
                "court_name": e.court_name,
                "url": e.url,
                "title": e.title,
                "text": e.text,
            }
            for e in entries
        ],
    }


@app.post("/kb/search", response_model=KbSearchResponse)
def kb_search(payload: KbSearchRequest, x_api_key: Optional[str] = Header(default=None)) -> KbSearchResponse:
    """Слой 1: поиск ответа в заранее собранной базе знаний (data/corpus.jsonl)."""
    from mcp_server.server import _tokenize, load_corpus, score

    _check_api_key(x_api_key)
    entries = load_corpus(CORPUS_PATH)
    if not entries:
        return KbSearchResponse(result="База знаний пуста: запустите scraper.crawl с российского IP/прокси.")

    query_tokens = _tokenize(payload.query)
    candidates = [e for e in entries if payload.court_slug is None or e.court_slug == payload.court_slug]
    ranked = sorted(candidates, key=lambda e: score(e, query_tokens), reverse=True)
    ranked = [e for e in ranked if score(e, query_tokens) > 0][: payload.top_k]

    if not ranked:
        return KbSearchResponse(result="По этому вопросу в базе знаний ничего не найдено.")

    chunks = [f"[{e.court_name}] {e.title or ''}\n{e.text[:800]}\nИсточник: {e.url}" for e in ranked]
    return KbSearchResponse(result="\n\n---\n\n".join(chunks))


@app.post("/case-lookup", response_model=CaseLookupResponse)
def case_lookup(payload: CaseLookupRequest, x_api_key: Optional[str] = Header(default=None)) -> CaseLookupResponse:
    """Слой 2: живой поиск дела на сайте суда (модуль sud_delo)."""
    _check_api_key(x_api_key)

    courts_config = _load_courts_config(COURTS_CONFIG_PATH)
    court = courts_config.get(payload.court_slug)
    if court is None:
        raise HTTPException(status_code=404, detail=f"Суд {payload.court_slug!r} не найден в courts.yaml")

    case_search_cfg = court.get("case_search") or {}
    if not case_search_cfg.get("enabled"):
        return CaseLookupResponse(
            status="disabled",
            result=(
                f"Поиск дел для суда {payload.court_slug!r} отключён в courts.yaml. "
                "Запустите scraper.case_lookup.discover с российского IP/прокси и "
                "включите case_search.enabled."
            ),
        )

    delo_id = (case_search_cfg.get("production_types") or {}).get(payload.production_type)
    if delo_id is None:
        raise HTTPException(status_code=400, detail=f"Неизвестный production_type={payload.production_type!r}")

    if not payload.case_number and not payload.last_name:
        raise HTTPException(status_code=400, detail="Нужно указать case_number или last_name")

    fetcher = _build_fetcher()
    solver = _build_captcha_solver()
    query = CaseQuery(case_number=payload.case_number, last_name=payload.last_name)

    result = search_case(
        fetcher,
        base_url=court["base_url"],
        delo_id=delo_id,
        query=query,
        captcha_solver=solver,
        field_overrides=case_search_cfg.get("field_overrides"),
    )
    return CaseLookupResponse(status=result.status, result=result.as_text())


@app.post("/delo", response_model=CaseLookupResponse)
def delo_lookup(payload: CaseLookupRequest, x_api_key: Optional[str] = Header(default=None)) -> CaseLookupResponse:
    """Быстрый слой 2 для вебхука Анны: stateless GET G1/U1 + карточка, пул прокси.

    Тот же контракт, что у n8n `court-agent-yurist`: {status, result}.
    """
    _check_api_key(x_api_key)
    domain = VORONEZH_SUDRF_COURTS.get(payload.court_slug)
    if domain is None:
        allowed = ", ".join(VORONEZH_SUDRF_COURTS)
        return CaseLookupResponse(
            status="error",
            result=f"Неизвестный суд '{payload.court_slug}'. Допустимые: {allowed}.",
        )
    if not payload.case_number and not payload.last_name:
        return CaseLookupResponse(status="error", result="Нужно указать case_number или last_name.")

    from scraper.proxy_pool import proxies_from_env
    import random

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
        CaseQuery(case_number=payload.case_number, last_name=payload.last_name),
        production_type=payload.production_type,
    )
    text = result.as_text() if result.status == "found" else result.message
    return CaseLookupResponse(status=result.status, result=text)


def _run_full_crawl(max_pages: int, max_depth: int) -> None:
    """Обходит все суды из courts.yaml и обновляет data/corpus.jsonl + summary.json.

    Выполняется в фоне (BackgroundTasks), поэтому вызывающий (например, n8n
    по расписанию) сразу получает 202 Accepted и не ждёт минуты обхода.
    """
    fetcher = _build_fetcher()
    courts = yaml.safe_load(COURTS_CONFIG_PATH.read_text(encoding="utf-8"))["courts"]

    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    summaries = []
    with CORPUS_PATH.open("w", encoding="utf-8") as corpus_file:
        for court in courts:
            records, report = crawl_court(
                fetcher, court["slug"], court["name"], court["base_url"], max_pages, max_depth,
            )
            summaries.append(report)
            for rec in records:
                corpus_file.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")

    (CORPUS_PATH.parent / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8",
    )


@app.post("/crawl", status_code=202)
def trigger_crawl(
    background_tasks: BackgroundTasks,
    max_pages: int = 60,
    max_depth: int = 2,
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    """Запускает обход всех судов (слой 1) в фоне — дёргайте по расписанию из
    n8n (Schedule Trigger -> HTTP Request POST /crawl), затем через
    /crawl/status проверяйте результат перед заливкой в БЗ."""
    _check_api_key(x_api_key)
    background_tasks.add_task(_run_full_crawl, max_pages, max_depth)
    return {"status": "started"}


@app.get("/crawl/status")
def crawl_status(x_api_key: Optional[str] = Header(default=None)) -> dict:
    _check_api_key(x_api_key)
    summary_path = CORPUS_PATH.parent / "summary.json"
    if not summary_path.exists():
        return {"status": "no_data", "courts": []}
    return {"status": "ok", "courts": json.loads(summary_path.read_text(encoding="utf-8"))}
