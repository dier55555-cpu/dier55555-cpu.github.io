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
from .case_card import (
    CaseCard,
    format_case_card,
    format_case_cards,
    looks_like_not_found,
    looks_like_wrong_captcha,
    parse_case_cards,
    parse_search_hits,
)
from .case_number import normalize_case_number
from .forms import SearchFormInfo, parse_search_form

Status = Literal[
    "found", "not_found", "captcha_required", "captcha_failed",
    "unmapped_fields", "blocked", "error", "unavailable",
]

# Stateless GET, как в n8n: без разбора <form>, без капчи.
# Подтверждено discover 20.08.2026 на 6 райсудах Воронежа.
SUDRF_PRODUCTION = {
    "civil_first_instance": {
        "delo_id": 1540005,
        "table": "g1_case",
        "case_number_field": "g1_case__CASE_NUMBERSS",
        "last_name_field": "G1_PARTS__NAMESS",
    },
    "criminal_first_instance": {
        "delo_id": 1540006,
        "table": "u1_case",
        "case_number_field": "u1_case__CASE_NUMBERSS",
        "last_name_field": "U1_DEFENDANT__NAMESS",
    },
}

VORONEZH_SUDRF_COURTS = {
    "sovetsky-vrn": "sovetsky--vrn.sudrf.ru",
    "kominternovsky-vrn": "kominternovsky--vrn.sudrf.ru",
    "zheleznodorozhny-vrn": "zheleznodorozhny--vrn.sudrf.ru",
    "levoberezhny-vrn": "levoberezhny--vrn.sudrf.ru",
    "centralny-vrn": "centralny--vrn.sudrf.ru",
    "lensud-vrn": "lensud--vrn.sudrf.ru",
}


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
            return format_case_cards(self.cases) or self.message
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


def search_case_direct(
    fetcher: Fetcher,
    domain: str,
    query: CaseQuery,
    production_type: str = "civil_first_instance",
) -> CaseSearchResult:
    """Живой поиск как в n8n: один GET формы результатов + GET карточки.

    Не разбирает <form> и не ходит в robots.txt — иначе не укладываемся в
    таймаут шлюза ~30с. Имена полей G1/U1 зафиксированы discover 20.08.2026.
    """
    prod = SUDRF_PRODUCTION.get(production_type) or SUDRF_PRODUCTION["civil_first_instance"]
    case_number = normalize_case_number(query.case_number)
    last_name = (query.last_name or "").strip() or None
    if not case_number and not last_name:
        return CaseSearchResult("error", "Нужно указать case_number или last_name.")

    params = {
        "name": "sud_delo",
        "srv_num": "1",
        "name_op": "r",
        "delo_id": str(prod["delo_id"]),
        "case_type": "0",
        "new": "0",
        "delo_table": prod["table"],
    }
    if case_number:
        params[prod["case_number_field"]] = case_number
    if last_name:
        params[prod["last_name_field"]] = last_name

    search_url = f"https://{domain}/modules.php"
    # Referer как у браузера после открытия формы поиска — меньше ложных отказов WAF.
    if hasattr(fetcher, "session"):
        fetcher.session.headers["Referer"] = (
            f"https://{domain}/modules.php?name=sud_delo&name_op=sf"
            f"&delo_id={prod['delo_id']}&srv_num=1"
        )
    fetch_result = fetcher.request("GET", search_url, params=params, respect_robots=False)
    if fetch_result.blocked:
        return CaseSearchResult("blocked", (
            "Сайт суда заблокировал запрос (нужен российский IP/прокси)."
        ))
    if not fetch_result.ok or not fetch_result.html:
        code = fetch_result.status_code
        if code and code >= 500:
            return CaseSearchResult(
                "error",
                f"Раздел «Судебное делопроизводство» на сайте суда отвечает ошибкой "
                f"HTTP {code}. Это сбой/перегрузка ГАС, не номер дела. Попробуйте позже.",
            )
        return CaseSearchResult(
            "error",
            "Раздел «Судебное делопроизводство» на сайте суда сейчас не отвечает "
            "(таймаут при поиске дела). Обычная главная суда при этом может открываться. "
            "Попробуйте задать вопрос ещё раз чуть позже.",
        )

    html = fetch_result.html
    if looks_like_not_found(html):
        return CaseSearchResult(
            "not_found",
            "По заданным критериям дел не найдено. Проверьте номер дела/фамилию "
            "или обратитесь на сайт суда напрямую (раздел «Судебное делопроизводство»).",
        )

    hits = parse_search_hits(html, fetch_result.url or search_url)
    if not hits:
        # Часто ГАС отдаёт «оболочку» сайта без #tablcont — модуль sud_delo лежит.
        # status=unavailable: не крутить другие прокси — это сбой ГАС у всех, не IP.
        return CaseSearchResult(
            "unavailable",
            "Раздел «Судебное делопроизводство» на сайте суда сейчас не отдаёт "
            "выдачу (открылась оболочка сайта без таблицы дел). Это сбой ГАС "
            "«Правосудие», не номер дела. Попробуйте позже или откройте поиск "
            "на сайте суда вручную.",
        )

    # Полная карточка — второй HTTP. По номеру обычно 1 дело; по фамилии — до 2,
    # чтобы уложиться в бюджет шлюза (~28с) при 2×HTTP на карточку.
    if last_name and not case_number:
        hydrate_limit = min(2, len(hits))
    else:
        hydrate_limit = min(2, max(1, len(hits)))
    cards = _hydrate_case_cards(fetcher, hits, limit=hydrate_limit, respect_robots=False)
    if not cards:
        return CaseSearchResult("not_found", "По заданным критериям дел не найдено.")
    if case_number:
        for card in cards:
            if "ЕЩЁ РЕЗУЛЬТАТЫ" in card.sections:
                continue
            # В выдаче часто «2-1248/2026 ~ М-52/2026» — в карточке отдаём канон.
            card.case_number = case_number
    shown = len([c for c in cards if "ЕЩЁ РЕЗУЛЬТАТЫ" not in c.sections])
    remaining = max(0, len(hits) - shown)
    if remaining:
        cards.append(CaseCard(sections={"ЕЩЁ РЕЗУЛЬТАТЫ": [
            {"сообщение": (
                f"Найдено дел: {len(hits)}. Показаны полные карточки: {shown}. "
                "Уточните номер дела, чтобы открыть конкретное, или повторите запрос."
            )}
        ]}))
    return CaseSearchResult("found", "Найдено", cases=cards)


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
        cards = parse_search_hits(html, fetch_result.url or form.action_url)
        cards = _hydrate_case_cards(fetcher, cards)

    if not cards:
        return CaseSearchResult(
            "error",
            "Страница результатов получена, но структура карточки дела не распознана "
            "(вероятно, у этого суда другая вёрстка — доработайте case_card.py под неё).",
        )
    return CaseSearchResult("found", "Найдено", cases=cards)


def _hydrate_case_cards(
    fetcher: Fetcher,
    hits: list[CaseCard],
    limit: int = 3,
    respect_robots: bool = True,
) -> list[CaseCard]:
    """По одному-трём делам из выдачи подтягиваем полную карточку (движение/стороны).

    При таймауте/ошибке второго запроса возвращаем hit со ссылкой на карточку —
    лучше краткий found, чем 504 у Анны.
    """
    if not hits:
        return []
    detailed: list[CaseCard] = []
    for hit in hits[:limit]:
        if not hit.case_url:
            detailed.append(hit)
            continue
        page = fetcher.get(hit.case_url, respect_robots=respect_robots)
        if page.blocked or not page.ok or not page.html:
            # Hit уже полезен: номер + URL карточки.
            detailed.append(hit)
            continue
        cards = parse_case_cards(page.html)
        if not cards:
            detailed.append(hit)
            continue
        card = cards[0]
        card.case_url = hit.case_url
        card.case_number = hit.case_number or card.case_number
        detailed.append(card)
    if len(hits) > limit:
        extra = CaseCard(sections={"ЕЩЁ РЕЗУЛЬТАТЫ": [
            {"сообщение": f"Показаны первые {limit} из {len(hits)}. Уточните номер дела."}
        ]})
        detailed.append(extra)
    return detailed
