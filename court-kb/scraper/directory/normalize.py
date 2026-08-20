"""Разбор карточки суда: адрес → регион/город, название → район, сайт → домен sudrf."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

# Живые сайты ГАС «Правосудие» вида host--region.sudrf.ru. В DaData website
# часто лежит «старый» вид host.region.sudrf.ru (с точками).
_SUDRF_DOTTED = re.compile(
    r"^(?P<host>[a-z0-9-]+)\.(?P<region>[a-z0-9-]+)\.sudrf\.ru$",
    re.IGNORECASE,
)
_SUDRF_LIVE = re.compile(
    r"^[a-z0-9-]+(?:--[a-z0-9-]+)?\.sudrf\.ru$",
    re.IGNORECASE,
)

_POSTAL = re.compile(r"^\d{6}$")
_SETTLEMENT = re.compile(
    r"^(?:г(?:ород)?|пгт|пос(?:ёлок|елок)?|п|с(?:ело)?|ст(?:аница)?|аул|х(?:утор)?|д(?:ер(?:евня)?)?)\.?\s+"
    r"([А-ЯЁ][А-ЯЁа-яё0-9IVXLCDM«»\"'\-\s]*)$",
    re.IGNORECASE,
)
# «д 19» / «зд 5» — это дом, не деревня.
_HOUSE_NAME = re.compile(r"^\d")

_NAME_CITY = re.compile(
    r"\bг(?:орода)?\.?\s+(.+?)$",
    re.IGNORECASE,
)
_DISTRICT = re.compile(
    r"^(.+?)\s+(?:районный|межрайонный)\s+суд\b",
    re.IGNORECASE,
)
_CITY_COURT = re.compile(
    r"^(.+?)\s+городской\s+суд\b",
    re.IGNORECASE,
)

_REGION_IN_ADDRESS = [
    re.compile(r"^(Респ(?:ублика|\.)?\s+.+)$", re.IGNORECASE),
    re.compile(r"^(.+?\s+край)$", re.IGNORECASE),
    re.compile(r"^(.+?\s+обл(?:асть)?)$", re.IGNORECASE),
    re.compile(r"^(.+?\s+АО)$"),
    re.compile(r"^(.+?автономн(?:ый|ая|ого)\s+округ.*)$", re.IGNORECASE),
    re.compile(r"^(Донецкая Народная Республика|Луганская Народная Республика)$", re.IGNORECASE),
]

_FEDERAL_CITIES = {
    "москва": "Москва",
    "москвы": "Москва",
    "санкт-петербург": "Санкт-Петербург",
    "санкт-петербурга": "Санкт-Петербург",
    "севастополь": "Севастополь",
    "севастополя": "Севастополь",
}

# Родительный падеж города в названии суда → именительный.
_CITY_GENITIVE = {
    "москвы": "Москва",
    "санкт-петербурга": "Санкт-Петербург",
    "воронежа": "Воронеж",
    "ставрополя": "Ставрополь",
    "севастополя": "Севастополь",
    "симферополя": "Симферополь",
    "ростова-на-дону": "Ростов-на-Дону",
    "нижнего новгорода": "Нижний Новгород",
    "великого новгорода": "Великий Новгород",
    "набережных челнов": "Набережные Челны",
    "улана-удэ": "Улан-Удэ",
    "южно-сахалинска": "Южно-Сахалинск",
    "ханты-мансийска": "Ханты-Мансийск",
    "горно-алтайска": "Горно-Алтайск",
    "йошкар-олы": "Йошкар-Ола",
    "петропавловска-камчатского": "Петропавловск-Камчатский",
    "ростова на дону": "Ростов-на-Дону",
    "орла": "Орёл",
    "елисты": "Элиста",
    "казани": "Казань",
    "перми": "Пермь",
    "тюмени": "Тюмень",
    "рязани": "Рязань",
    "астрахани": "Астрахань",
    "костромы": "Кострома",
    "вологды": "Вологда",
    "уфы": "Уфа",
    "пензы": "Пенза",
    "тулы": "Тула",
    "курска": "Курск",
    "орска": "Орск",
    "липецка": "Липецк",
    "донецка": "Донецк",
    "луганска": "Луганск",
}


@dataclass(frozen=True)
class CourtRecord:
    code: str
    name: str
    court_type: str
    court_type_name: str
    region_code: str
    region: str
    city: str
    district: str
    address: str
    website: str
    sudrf_domain: str
    parser_supported: bool
    inn: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip(" ,")


def _norm_key(value: str) -> str:
    return _clean(value).lower().replace("ё", "е")


def sudrf_target(website: str) -> tuple[str, bool]:
    """Вернуть (домен для парсера, поддерживается ли G1/U1 на sudrf)."""
    raw = _clean(website)
    if not raw:
        return "", False
    parsed = urlparse(raw if "://" in raw else "http://" + raw)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return "", False
    dotted = _SUDRF_DOTTED.match(host)
    if dotted:
        live = f"{dotted.group('host')}--{dotted.group('region')}.sudrf.ru"
        return live, True
    if _SUDRF_LIVE.match(host):
        return host, True
    return host, False


def city_nominative(raw: str) -> str:
    value = _clean(raw).strip(" .")
    if not value:
        return ""
    key = _norm_key(value)
    if key in _FEDERAL_CITIES:
        return _FEDERAL_CITIES[key]
    if key in _CITY_GENITIVE:
        return _CITY_GENITIVE[key]
    if key.endswith("поля"):
        return value[:-4] + "поль"
    if key.endswith("бурга"):
        return value[:-1]
    if key.endswith("ы"):
        return value[:-1] + "а"
    if key.endswith("и") and not key.endswith(("ский", "цкий", "ной")):
        # Казани / Перми / Тюмени — часто мягкий знак в именительном.
        stem = value[:-1]
        if stem.endswith(("н", "р", "м")):
            return stem + "ь"
        return value
    if key.endswith("а"):
        return value[:-1]
    if key.endswith("я"):
        return value[:-1] + "ь"
    return value


def _expand_region_abbrev(token: str) -> str:
    text = _clean(token)
    text = re.sub(r"^Респ\.?\s+", "Республика ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bобл$", "область", text, flags=re.IGNORECASE)
    text = re.sub(r"\bобл\.$", "область", text, flags=re.IGNORECASE)
    return _clean(text)


def parse_region_from_address(address: str) -> str:
    parts = [_clean(p) for p in _clean(address).split(",") if _clean(p)]
    for part in parts:
        if _POSTAL.match(part):
            continue
        if _SETTLEMENT.match(part):
            continue
        for pattern in _REGION_IN_ADDRESS:
            match = pattern.match(part)
            if match:
                return _expand_region_abbrev(match.group(1))
        key = _norm_key(part)
        if key in {"г москва", "г. москва", "город москва"} or key.startswith("г москва"):
            return "Москва"
        if "санкт-петербург" in key:
            return "Санкт-Петербург"
        if key in {"г севастополь", "г. севастополь"} or key.startswith("г севастополь"):
            return "Севастополь"
    return ""


def parse_region_from_name(name: str) -> str:
    text = _clean(name)
    key = _norm_key(text)
    if re.search(r"города москвы|\bг\.?\s*москвы\b|московский городской суд", key):
        return "Москва"
    if re.search(r"санкт-петербургск", key) and "городск" in key:
        return "Санкт-Петербург"
    if re.search(r"города севастополя|\bг\.?\s*севастополя\b", key):
        return "Севастополь"

    match = re.match(r"(.+?)ский областной суд$", text, re.IGNORECASE)
    if match:
        return match.group(1) + "ская область"
    match = re.match(r"(.+?)ский краевой суд$", text, re.IGNORECASE)
    if match:
        return match.group(1) + "ский край"

    match = re.search(r"Республики\s+(.+)$", text)
    if match:
        return "Республика " + _clean(match.group(1))

    match = re.search(r"([А-ЯЁа-яё-]+)ской области$", text)
    if match:
        return match.group(1) + "ская область"
    match = re.search(r"([А-ЯЁа-яё-]+)ского края$", text)
    if match:
        return match.group(1) + "ский край"
    match = re.search(r"([А-ЯЁа-яё-]+)ого автономного округа(.*)$", text)
    if match:
        tail = _clean(match.group(2)).lstrip("-—– ")
        base = match.group(1) + "ий автономный округ"
        return f"{base} — {tail}" if tail else base
    match = re.search(r"([А-ЯЁа-яё-]+)ой автономной области$", text)
    if match:
        return match.group(1) + "ая автономная область"
    match = re.search(r"(Донецкой Народной Республики)$", text)
    if match:
        return "Донецкая Народная Республика"
    match = re.search(r"(Луганской Народной Республики)$", text)
    if match:
        return "Луганская Народная Республика"
    return ""


def parse_region(name: str, address: str) -> str:
    return parse_region_from_address(address) or parse_region_from_name(name)


def parse_city_from_address(address: str) -> str:
    parts = [_clean(p) for p in _clean(address).split(",") if _clean(p)]
    for part in parts:
        match = _SETTLEMENT.match(part)
        if not match:
            continue
        place = _clean(match.group(1))
        if _HOUSE_NAME.match(place):
            continue
        return place
    return ""


def parse_city_from_name(name: str) -> str:
    text = _clean(name)
    match = _NAME_CITY.search(text)
    if match:
        return city_nominative(match.group(1))
    return ""


def parse_city(name: str, address: str) -> str:
    return parse_city_from_address(address) or parse_city_from_name(name)


def parse_district(name: str) -> str:
    text = _clean(name)
    match = _DISTRICT.match(text)
    if match:
        return _clean(match.group(1))
    return ""


def fill_missing_regions(records: Sequence[CourtRecord]) -> list[CourtRecord]:
    """Добивает пустой регион по коду суда: у райсуда в областном центре в адресе часто только «г Воронеж»."""
    rows = list(records)
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for record in rows:
        if record.region_code and record.region:
            votes[record.region_code][record.region] += 1
    chosen = {
        code: counter.most_common(1)[0][0]
        for code, counter in votes.items()
        if counter
    }
    filled = []
    for record in rows:
        if record.region or record.region_code not in chosen:
            filled.append(record)
        else:
            filled.append(replace(record, region=chosen[record.region_code]))
    return filled


def enrich_court(data: dict[str, Any]) -> CourtRecord:
    code = _clean(data.get("code"))
    name = _clean(data.get("name"))
    address = _clean(data.get("address"))
    website = _clean(data.get("website"))
    domain, supported = sudrf_target(website)
    region_code = code[:2] if len(code) >= 2 and code[:2].isdigit() else ""
    return CourtRecord(
        code=code,
        name=name,
        court_type=_clean(data.get("court_type")),
        court_type_name=_clean(data.get("court_type_name")),
        region_code=region_code,
        region=parse_region(name, address),
        city=parse_city(name, address),
        district=parse_district(name),
        address=address,
        website=website,
        sudrf_domain=domain,
        parser_supported=supported,
        inn=_clean(data.get("inn")),
    )
