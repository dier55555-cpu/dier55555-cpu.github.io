"""
Слой 2: поиск конкретного дела (номер / ФИО / уникальный идентификатор) на
сайте суда через модуль «Судебное делопроизводство» (sud_delo).

Использование (пример):

    from scraper.fetch import Fetcher
    from scraper.case_lookup.search import CaseQuery, search_case
    from scraper.case_lookup.captcha import TwoCaptchaSolver

    fetcher = Fetcher(proxies={"https": "http://user:pass@ru-proxy:port"})
    solver = TwoCaptchaSolver(api_key="...")
    result = search_case(
        fetcher,
        base_url="https://sovetsky--vrn.sudrf.ru/",
        delo_id=1540005,  # гражданские дела, первая инстанция (см. README)
        query=CaseQuery(case_number="2-123/2026"),
        captcha_solver=solver,
    )

ВАЖНО: делоId (тип производства) и точные названия полей формы для этих
конкретных 6 судов Воронежа НЕ подтверждены — подтверждены только по другим
судам (СПб, Башкортостан) через открытые источники. Перед боевым
использованием прогоните `python -m scraper.case_lookup.discover` с
российского IP по каждому суду и сверьте результат (см. README).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional
from urllib.parse import urljoin

from ..fetch import Fetcher
from .captcha import CaptchaSolver
from .case_card import CaseCard, format_case_card, looks_like_not_found, looks_like_wrong_captcha, parse_case_cards
from .forms import SearchFormInfo, parse_search_form

Status = Literal[
    "found", "not_found", "captcha_required", "captcha_failed",
    "unmapped_fields", "blocked", "error",
]


@dataclass
class CaseQuery:
    case_number: Optional[str] = None
    case_uid: Optional[str] = None
    last_name: Optional[str] = None


@dataclass
class CaseSearchResult:
    status: Status
    message: str
    cases: list[CaseCard] = field(default_factory=list)
    discovered_fields: Optional[list[str]] = None  # для диагностики unmapped_fields
    captcha_image_url: Optional[str] = None

    def as_text(self) -> str:
        if self.status == "found":
            return "\n\n---\n\n".join(format_case_card(c) for c in self.cases) or self.message
        return self.message


def _build_search_form_url(base_url: str, delo_id: int) -> str:
    return urljoin(base_url, f"modules.php?name=sud_delo&name_op=sf&delo_id={delo_id}&srv_num=1")


def search_case(
    fetcher: Fetcher,
    base_url: str,
    delo_id: int,
    query: CaseQuery,
    captcha_solver: Optional[CaptchaSolver] = None,
    field_overrides: Optional[dict] = None,
    max_captcha_attempts: int = 2,
) -> CaseSearchResult:
    field_overrides = field_overrides or {}
    form_url = _build_search_form_url(base_url, delo_id)

    fetch_result = fetcher.get(form_url)
    if fetch_result.blocked:
        return CaseSearchResult("blocked", (
            "Сайт суда заблокировал запрос (нужен российский IP/прокси)."
        ))
    if not fetch_result.ok or not fetch_result.html:
        return CaseSearchResult("error", f"Не удалось загрузить форму поиска: {fetch_result.error}")

    try:
        form = parse_search_form(fetch_result.html, form_url)
    except ValueError as exc:
        return CaseSearchResult("error", str(exc))

    params = _fill_params(form, query, field_overrides)
    if params is None:
        discovered = [f"{f.name} <- \"{f.label}\"" for f in form.unmapped_fields()]
        return CaseSearchResult(
            "unmapped_fields",
            "Не удалось сопоставить поля запроса с полями формы автоматически. "
            "Запустите scraper.case_lookup.discover для этого суда и задайте "
            "courts.yaml -> case_search.field_overrides вручную.",
            discovered_fields=discovered,
        )

    if form.captcha is not None:
        if captcha_solver is None:
            return CaseSearchResult(
                "captcha_required",
                "На форме поиска есть капча, но решатель капчи не настроен "
                "(передайте captcha_solver, например TwoCaptchaSolver).",
                captcha_image_url=form.captcha.image_url,
            )
        return _search_with_captcha(fetcher, form, params, query, captcha_solver, max_captcha_attempts)

    return _submit_and_parse(fetcher, form, params)


def _fill_params(form: SearchFormInfo, query: CaseQuery, field_overrides: dict) -> Optional[dict]:
    params = {f.name: f.value for f in form.fields if f.tag == "input" and f.input_type == "hidden" and f.value}

    mapping = {
        "case_number": query.case_number,
        "case_uid": query.case_uid,
        "last_name": query.last_name,
    }
    filled_any = False
    for key, value in mapping.items():
        if value is None:
            continue
        field_name = field_overrides.get(key)
        if field_name is None:
            matched = form.field_by_key(key)
            field_name = matched.name if matched else None
        if field_name is None:
            continue
        params[field_name] = value
        filled_any = True

    return params if filled_any else None


def _search_with_captcha(fetcher, form, params, query, captcha_solver, max_attempts) -> CaseSearchResult:
    last_message = "Не удалось решить капчу"
    for attempt in range(1, max_attempts + 1):
        image_bytes = fetcher.get_bytes(form.captcha.image_url)
        if not image_bytes:
            return CaseSearchResult("error", "Не удалось скачать картинку капчи")

        code = captcha_solver.solve(image_bytes)
        attempt_params = dict(params)
        attempt_params[form.captcha.field_name] = code

        result = _submit_and_parse(fetcher, form, attempt_params)
        if result.status != "captcha_failed":
            return result
        last_message = result.message

    return CaseSearchResult("captcha_failed", last_message)


def _submit_and_parse(fetcher: Fetcher, form: SearchFormInfo, params: dict) -> CaseSearchResult:
    if form.method == "POST":
        fetch_result = fetcher.post(form.action_url, data=params)
    else:
        fetch_result = fetcher.request("GET", form.action_url, params=params)

    if fetch_result.blocked:
        return CaseSearchResult("blocked", "Сайт суда заблокировал запрос при отправке формы.")
    if not fetch_result.ok or not fetch_result.html:
        return CaseSearchResult("error", f"Не удалось отправить форму поиска: {fetch_result.error}")

    html = fetch_result.html
    if form.captcha is not None and looks_like_wrong_captcha(html):
        return CaseSearchResult("captcha_failed", "Капча решена неверно, требуется повторная попытка.")
    if looks_like_not_found(html):
        return CaseSearchResult("not_found", "По заданным критериям дел не найдено.")

    cards = parse_case_cards(html)
    if not cards:
        return CaseSearchResult(
            "error",
            "Страница результатов получена, но структура карточки дела не распознана "
            "(вероятно, у этого суда другая вёрстка — доработайте case_card.py под неё).",
        )
    return CaseSearchResult("found", "Найдено", cases=cards)
