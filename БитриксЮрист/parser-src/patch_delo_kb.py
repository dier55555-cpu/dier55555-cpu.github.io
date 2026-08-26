"""Расширение delo API: справочник судов + поиск дела по website (в т.ч. msudrf)."""

from __future__ import annotations

from pathlib import Path


DELO_APPEND = r'''

# --- БитриксЮрист: справочник судов + поиск по website ---
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
        limit=max(1, min(payload.limit, 10)),
    )


def _domain_from_website(website: str) -> tuple[str, bool, bool]:
    """(domain, is_sudrf_template, is_magistrate)."""
    domain, supported = sudrf_target(website)
    host = (domain or "").lower()
    is_ms = host.endswith(".msudrf.ru")
    return domain, supported, is_ms


def _looks_unavailable(html: str) -> bool:
    low = (html or "").lower()
    return "временно недоступна" in low or "приносим свои извинения" in low


def _looks_captcha_gate(html: str) -> bool:
    low = (html or "").lower()
    return ("дополнительную проверку" in low and "captcha" in low) or (
        "проверочный код" in low and "продолжить" in low
    )


# Расширяем модель запроса полями для резолва из Битрикс/БЗ.
CaseLookupRequest.model_rebuild()
'''


def patch_delo_app(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "/court_lookup" in text and "region: Optional[str]" in text:
        print("delo_app already has court_lookup fields?")
    # extend CaseLookupRequest fields
    old_model = '''class CaseLookupRequest(BaseModel):
    court_slug: Optional[str] = None
    case_number: Optional[str] = None
    last_name: Optional[str] = None
    production_type: str = "civil_first_instance"
    # Справка с сайта (тот же вебхук «Дело» может прислать website+topic).
    website: Optional[str] = None
    topic: Optional[str] = None
    mode: Optional[str] = None  # case | info
'''
    new_model = '''class CaseLookupRequest(BaseModel):
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
'''
    if old_model not in text:
        if "court_name: Optional[str]" not in text:
            raise SystemExit("CaseLookupRequest block not found for patch")
    else:
        text = text.replace(old_model, new_model, 1)

    # Replace domain resolution block in delo_lookup to allow website / KB resolve
    old_domain = '''    domain = VORONEZH_SUDRF_COURTS.get(payload.court_slug or "")
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
'''
    new_domain = '''    # 1) явный website  2) справочник РФ  3) slug пилота Воронежа
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
'''
    if old_domain not in text:
        if "_domain_from_website" not in text:
            raise SystemExit("domain resolution block not found")
    else:
        text = text.replace(old_domain, new_domain, 1)

    # Improve logging line to include resolved_meta if present - optional
    old_log = '''    log.info(
        "delo slug=%s q=%s raw_q=%s status=%s port=%s dt=%.2fs",
        payload.court_slug,
        case_number or last_name,
        case_number_raw or "",
        result.status,
        _proxy_port(used) if used else "direct",
        time.monotonic() - t0,
    )
    text = result.as_text() if result.status == "found" else result.message
    return CaseLookupResponse(status=result.status, result=text)
'''
    new_log = '''    # Если сайт вернул заглушку/капчу — говорим явно (не «таймаут прокси»).
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
'''
    if old_log in text:
        text = text.replace(old_log, new_log, 1)

    # Detect unavailable page inside search_case_direct path via wrapping - patch search.py instead
    if "from api.court_directory import resolve_court" not in text:
        # insert imports and helpers + court_lookup route before end or after health
        marker = '@app.get("/health")\ndef health() -> dict:\n    return {"status": "ok"}\n'
        inject = '''@app.get("/health")
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

'''
        if marker not in text:
            raise SystemExit("health marker not found")
        text = text.replace(marker, inject, 1)

    path.write_text(text, encoding="utf-8")
    print("delo_app patched")


def patch_search_unavailable(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "временно недоступна" in text and "UNAVAILABLE_MARKERS" in text:
        print("search.py already has unavailable markers")
        return
    old = '''    html = fetch_result.html
    if looks_like_not_found(html):
'''
    new = '''    html = fetch_result.html
    low = (html or "").lower()
    if "временно недоступна" in low or "приносим свои извинения" in low:
        return CaseSearchResult(
            "error",
            "Информация временно недоступна на сайте суда. Попробуйте позже или обратитесь в суд напрямую.",
        )
    if ("дополнительную проверку" in low and "captcha" in low) or (
        "для продолжения необходимо пройти" in low
    ):
        return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу (типично для мировых судей). Нужен ключ 2captcha или ручной обход.",
        )
    if looks_like_not_found(html):
'''
    if old not in text:
        raise SystemExit("search.html block not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("search.py patched for unavailable/captcha pages")


if __name__ == "__main__":
    patch_delo_app(Path("/opt/bitrix-delo/api/delo_app.py"))
    patch_search_unavailable(Path("/opt/bitrix-delo/scraper/case_lookup/search.py"))
