"""Локальный поиск суда по свободной фразе: город, район, название."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from .normalize import CourtRecord, _clean, _norm_key, enrich_court

STOPWORDS = {
    "район",
    "района",
    "районный",
    "районного",
    "межрайонный",
    "городской",
    "городского",
    "суд",
    "суда",
    "города",
    "город",
    "г",
    "обл",
    "область",
    "области",
    "край",
    "края",
    "республика",
    "республики",
    "респ",
    "им",
    "имени",
    "рф",
    "российской",
    "федерации",
}

_TOKEN = re.compile(r"[а-яёa-z0-9-]+", re.IGNORECASE)


def tokenize_query(query: str) -> list[str]:
    tokens = []
    for raw in _TOKEN.findall(_norm_key(query)):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        tokens.append(raw)
    return tokens


def _stem(token: str) -> str:
    if len(token) < 5:
        return token
    return token.rstrip("аяыиоеуюйь") or token


def _haystack(record: CourtRecord) -> str:
    return _norm_key(" ".join([
        record.name,
        record.city,
        record.district,
        record.region,
        record.address,
        record.code,
    ]))


def _token_hit(token: str, text: str) -> bool:
    if token in text:
        return True
    stem = _stem(token)
    return len(stem) >= 4 and stem in text


def score_record(record: CourtRecord, tokens: Sequence[str]) -> int:
    if not tokens:
        return 0
    name = _norm_key(record.name)
    city = _norm_key(record.city)
    district = _norm_key(record.district)
    region = _norm_key(record.region)
    blob = _haystack(record)
    score = 0
    hits = 0
    for token in tokens:
        matched = False
        if _token_hit(token, district):
            score += 6
            matched = True
        if _token_hit(token, city):
            score += 6
            matched = True
        if _token_hit(token, name):
            score += 3
            matched = True
        if _token_hit(token, region):
            score += 2
            matched = True
        if not matched and _token_hit(token, blob):
            score += 1
            matched = True
        if matched:
            hits += 1
    if hits < len(tokens):
        # Все значимые слова запроса должны к чему-то прицепиться,
        # иначе «Ленинский Ставрополь» не должен выигрывать у чужого Ленинского.
        return 0
    if record.parser_supported:
        score += 1
    return score


def lookup_courts(
    query: str,
    records: Sequence[CourtRecord],
    *,
    limit: int = 5,
    court_types: Optional[Iterable[str]] = None,
) -> list[CourtRecord]:
    tokens = tokenize_query(query)
    if not tokens:
        return []
    qn = _norm_key(query)
    if court_types is None and "миров" not in qn and "участок" not in qn:
        # Обычный запрос «Ленинский район г. Ставрополь» — районный/областной, не 20 мировых участков.
        court_types = ("RS", "OS", "AJ", "KJ", "VS")
    allowed = {t.upper() for t in court_types} if court_types else None
    ranked: list[tuple[int, CourtRecord]] = []
    for record in records:
        if allowed and record.court_type.upper() not in allowed:
            continue
        points = score_record(record, tokens)
        if points > 0:
            ranked.append((points, record))
    ranked.sort(key=lambda item: (-item[0], item[1].name))
    return [record for _, record in ranked[:limit]]


def records_from_raw(rows: Iterable[dict]) -> list[CourtRecord]:
    records = []
    for row in rows:
        if isinstance(row, CourtRecord):
            records.append(row)
            continue
        if "sudrf_domain" in row and "region" in row and "code" in row:
            records.append(CourtRecord(
                code=_clean(row.get("code")),
                name=_clean(row.get("name")),
                court_type=_clean(row.get("court_type")),
                court_type_name=_clean(row.get("court_type_name")),
                region_code=_clean(row.get("region_code")),
                region=_clean(row.get("region")),
                city=_clean(row.get("city")),
                district=_clean(row.get("district")),
                address=_clean(row.get("address")),
                website=_clean(row.get("website")),
                sudrf_domain=_clean(row.get("sudrf_domain")),
                parser_supported=bool(row.get("parser_supported")),
                inn=_clean(row.get("inn")),
            ))
        else:
            records.append(enrich_court(row))
    return records


def load_directory(path: Union[str, Path]) -> list[CourtRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("courts") if isinstance(payload, dict) else payload
    return records_from_raw(rows or [])
