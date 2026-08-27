"""
БитриксЮрист — обход воронки Bitrix24.

1) читаем сделку
2) резолвим суд через справочник РФ (/court_lookup) по региону/городу/району/названию
3) ищем дело на сайте суда (POST /delo)
4) пишем статус и комментарий в карточку
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bitrix-yurist")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    return [x.strip() for x in raw.split(",") if x.strip()]


BITRIX_WEBHOOK_URL = _env("BITRIX_WEBHOOK_URL")
CATEGORY_ID = int(_env("BITRIX_CATEGORY_ID") or "0")
WORKING_STAGE_IDS = _env_list("BITRIX_STAGE_IDS")

# Несколько кодов через запятую: берём первое непустое значение.
UF_CASE_NUMBER_FIELDS = _env_list("UF_CASE_NUMBER") or ["UF_CRM_CASE_NUMBER"]
UF_COURT_WEBSITE_FIELDS = _env_list("UF_COURT_WEBSITE") or ["UF_CRM_COURT_WEBSITE"]
UF_CASE_NUMBER = UF_CASE_NUMBER_FIELDS[0]
UF_COURT_WEBSITE = UF_COURT_WEBSITE_FIELDS[0]
UF_COURT_SLUG = _env("UF_COURT_SLUG") or "UF_CRM_COURT_SLUG"
UF_COURT_NAME = _env("UF_COURT_NAME") or "UF_CRM_COURT_NAME"
UF_REGION = _env("UF_REGION") or "UF_CRM_REGION"
UF_CITY = _env("UF_CITY") or "UF_CRM_CITY"
UF_DISTRICT = _env("UF_DISTRICT") or "UF_CRM_DISTRICT"
UF_LAST_STATUS = _env("UF_LAST_STATUS") or "UF_CRM_LAST_STATUS"
UF_LAST_CHECK_AT = _env("UF_LAST_CHECK_AT") or "UF_CRM_LAST_CHECK_AT"
UF_SNAPSHOT_HASH = _env("UF_SNAPSHOT_HASH") or "UF_CRM_SNAPSHOT_HASH"

COURT_KB_API_URL = (_env("COURT_KB_API_URL") or "http://127.0.0.1:8081").rstrip("/")
COURT_KB_API_KEY = _env("COURT_KB_API_KEY")

DRY_RUN = _env("DRY_RUN", "1") not in {"0", "false", "False"}
COMMENT_ONLY_ON_CHANGE = _env("COMMENT_ONLY_ON_CHANGE", "1") not in {"0", "false", "False"}
PAUSE_BETWEEN_DEALS_SEC = float(_env("PAUSE_BETWEEN_DEALS_SEC") or "5")
TZ = ZoneInfo(_env("TZ") or "Europe/Moscow")
RATE_LIMIT_SLEEP = 0.55
SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "data", "snapshots.json")


class BitrixError(Exception):
    pass


@dataclass
class Deal:
    id: int
    title: str
    stage_id: str
    contact_id: Optional[int]
    case_number: Optional[str]
    court_slug: Optional[str]
    court_name: Optional[str]
    region: Optional[str]
    city: Optional[str]
    district: Optional[str]
    court_website: Optional[str]
    snapshot_hash: Optional[str]
    comments: str = ""
    raw: dict = field(default_factory=dict)


def _now_label() -> str:
    return datetime.now(TZ).strftime("%d.%m.%Y %H:%M") + " (МСК)"


def _call(method: str, params: dict) -> dict:
    if not BITRIX_WEBHOOK_URL or "YOUR_PORTAL" in BITRIX_WEBHOOK_URL:
        raise BitrixError("BITRIX_WEBHOOK_URL не задан")
    url = f"{BITRIX_WEBHOOK_URL.rstrip('/')}/{method}.json"
    for attempt in range(5):
        resp = requests.post(url, json=params, timeout=30)
        try:
            data = resp.json()
        except ValueError as exc:
            raise BitrixError(f"{method}: не JSON (HTTP {resp.status_code})") from exc
        if resp.status_code >= 400 and "error" not in data:
            raise BitrixError(f"{method}: HTTP {resp.status_code} {data}")
        if "error" in data:
            if data["error"] == "QUERY_LIMIT_EXCEEDED":
                time.sleep(1.5 * (attempt + 1))
                continue
            raise BitrixError(f"{method} failed: {data['error']} — {data.get('error_description')}")
        return data
    raise BitrixError(f"{method}: retries exhausted")


def _is_filled(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _txt(value: Any) -> Optional[str]:
    if not _is_filled(value):
        return None
    return str(value).strip()


def _extract_case_number(raw: Any) -> Optional[str]:
    """Достаёт номер дела из свободного текста: «ДЕЛО № 2-1248/2026 ~ М-52/2026»."""
    import re

    text = _txt(raw)
    if not text:
        return None
    # Уже чистый номер
    if re.fullmatch(r"\d+-\d+(?:/\d{2,4})?", text):
        return text
    m = re.search(r"(\d+\s*-\s*\d+\s*/\s*\d{2,4})", text)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    m = re.search(r"(\d+\s*-\s*\d+)", text)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    return text


def _website_origin(raw: Any) -> Optional[str]:
    """Из полной ссылки на карточку дела оставляет origin сайта суда."""
    from urllib.parse import urlparse

    text = _txt(raw)
    if not text:
        return None
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    parsed = urlparse(text)
    if not parsed.netloc:
        return text
    return f"{parsed.scheme}://{parsed.netloc}/"


def _first_field(item: dict[str, Any], fields: list[str]) -> Any:
    for code in fields:
        if _is_filled(item.get(code)):
            return item.get(code)
    return None


def pull_deals() -> list[Deal]:
    deals: list[Deal] = []
    filter_: dict[str, Any] = {"CATEGORY_ID": CATEGORY_ID}
    if WORKING_STAGE_IDS:
        filter_["@STAGE_ID"] = WORKING_STAGE_IDS
    start = 0
    while True:
        data = _call("crm.deal.list", {
            "filter": filter_,
            "select": [
                "ID", "TITLE", "STAGE_ID", "CONTACT_ID", "COMMENTS",
                UF_COURT_SLUG, UF_COURT_NAME, UF_REGION,
                UF_CITY, UF_DISTRICT, UF_SNAPSHOT_HASH, "UF_*",
                *UF_CASE_NUMBER_FIELDS, *UF_COURT_WEBSITE_FIELDS,
            ],
            "start": start,
        })
        batch = data.get("result") or []
        if not batch:
            break
        for item in batch:
            case_number = _extract_case_number(_first_field(item, UF_CASE_NUMBER_FIELDS))
            if not case_number:
                continue
            deals.append(Deal(
                id=int(item["ID"]),
                title=item.get("TITLE") or "",
                stage_id=item.get("STAGE_ID") or "",
                contact_id=int(item["CONTACT_ID"]) if item.get("CONTACT_ID") else None,
                case_number=case_number,
                court_slug=_txt(item.get(UF_COURT_SLUG)),
                court_name=_txt(item.get(UF_COURT_NAME)),
                region=_txt(item.get(UF_REGION)),
                city=_txt(item.get(UF_CITY)),
                district=_txt(item.get(UF_DISTRICT)),
                court_website=_website_origin(_first_field(item, UF_COURT_WEBSITE_FIELDS)),
                snapshot_hash=_txt(item.get(UF_SNAPSHOT_HASH)),
                comments=str(item.get("COMMENTS") or ""),
                raw=item,
            ))
        next_start = data.get("next")
        if next_start is None:
            break
        start = next_start
        time.sleep(RATE_LIMIT_SLEEP)
    logger.info("Pulled %d deals with case number", len(deals))
    return deals


def _api_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if COURT_KB_API_KEY:
        headers["X-API-Key"] = COURT_KB_API_KEY
    return headers


def resolve_court_from_kb(deal: Deal) -> dict[str, Any]:
    """Всегда сверяем карточку со справочником судов РФ."""
    # TITLE сделки («Клиент1» / «КЛИЕНТ 2») в запрос не тащим — ломает токен-матчинг.
    # Если уже есть website дела — справочник не обязателен для /delo.
    court_name = deal.court_name or deal.court_slug or ""
    has_geo = any([deal.region, deal.city, deal.district, court_name])
    if not has_geo and deal.court_website:
        return {
            "status": "skipped",
            "result": "гео/название суда пустые — используем website из сделки",
            "court": {"website": deal.court_website, "name": deal.court_name or ""},
        }
    payload = {
        "region": deal.region or "",
        "city": deal.city or "",
        "district": deal.district or "",
        "court_name": court_name,
        "query": "",
        "prefer_magistrate": None,
        "limit": 5,
    }
    # Без geo и без website — нечем искать; TITLE не используем.
    if not any([payload["region"], payload["city"], payload["district"], payload["court_name"]]):
        return {"status": "skipped", "result": "нет региона/города/района/названия суда и website"}
    q = (payload["court_name"] + " " + payload["district"] + " " + payload["city"]).lower()
    if "миров" in q or "участок" in q:
        payload["prefer_magistrate"] = True
    try:
        resp = requests.post(
            f"{COURT_KB_API_URL}/court_lookup",
            json=payload,
            headers=_api_headers(),
            timeout=30,
        )
        body = resp.json()
    except (ValueError, requests.RequestException) as exc:
        return {"status": "error", "result": f"справочник: {exc}"}
    return body if isinstance(body, dict) else {"status": "error", "result": body}


def lookup_delo(deal: Deal, resolved: dict[str, Any]) -> dict[str, Any]:
    court = (resolved or {}).get("court") or {}
    website = deal.court_website or court.get("website") or ""
    domain = court.get("parser_domain") or court.get("sudrf_domain") or ""
    slug = deal.court_slug
    if domain and "--" in domain and domain.endswith(".sudrf.ru"):
        # sovetsky--vrn.sudrf.ru -> sovetsky-vrn
        left = domain.split(".sudrf.ru")[0]
        if left.count("--") == 1:
            slug = left.replace("--", "-")

    payload: dict[str, Any] = {
        "mode": "case",
        "case_number": deal.case_number,
        "last_name": None,
        "production_type": "civil_first_instance",
        "website": website or None,
        "court_slug": slug,
        "region": deal.region,
        "city": deal.city,
        "district": deal.district,
        "court_name": deal.court_name or court.get("name"),
    }
    last: dict[str, Any] = {"status": "error", "result": "парсер не ответил"}
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{COURT_KB_API_URL}/delo",
                json=payload,
                headers=_api_headers(),
                timeout=160,
            )
            body = resp.json()
        except (ValueError, requests.RequestException) as exc:
            last = {"status": "error", "result": f"сеть/JSON: {exc}"}
            time.sleep(2 * (attempt + 1))
            continue
        if not isinstance(body, dict):
            last = {"status": "error", "result": body}
            continue
        last = body
        if body.get("status") in {"found", "not_found", "skipped", "captcha_required"}:
            return body
        logger.warning("Parser attempt %s deal %s: %s", attempt + 1, deal.id, body.get("result"))
        time.sleep(2 * (attempt + 1))
    return last


def card_digest(parsed: dict[str, Any]) -> tuple[str, str]:
    result = parsed.get("result")
    payload = {"result": result}
    status_text = str(result or "")[:500]
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32], status_text


def load_local_hashes() -> dict[str, str]:
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_local_hashes(store: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)


def push_fields(deal_id: int, fields: dict[str, Any]) -> None:
    _call("crm.deal.update", {"id": deal_id, "fields": fields})
    time.sleep(RATE_LIMIT_SLEEP)


def comment_timeline(deal_id: int, text: str) -> None:
    _call("crm.timeline.comment.add", {
        "fields": {"ENTITY_ID": deal_id, "ENTITY_TYPE": "deal", "COMMENT": text},
    })
    time.sleep(RATE_LIMIT_SLEEP)


def format_comment(deal: Deal, parsed: dict[str, Any], changed: bool, checked_at: str, resolved: dict) -> str:
    court = (resolved or {}).get("court") or {}
    lines = [
        "[БитриксЮрист] Обновление дела произведено" if changed else "[БитриксЮрист] Проверка дела выполнена, изменений нет",
        f"Проверено: {checked_at}",
        f"Номер: {deal.case_number}",
        f"Суд (БЗ): {court.get('name') or deal.court_name or deal.court_slug or '—'}",
        f"Сайт: {court.get('website') or deal.court_website or '—'}",
        f"Ответ парсера: {parsed.get('status')}",
    ]
    result = parsed.get("result")
    if result:
        lines.append(str(result)[:1500])
    return "\n".join(lines)


def run_daily_job() -> dict[str, int]:
    stats = {
        "total": 0, "changed": 0, "unchanged": 0, "errors": 0, "skipped": 0, "resolved": 0,
    }
    if not BITRIX_WEBHOOK_URL or "YOUR_PORTAL" in BITRIX_WEBHOOK_URL:
        logger.warning("BITRIX_WEBHOOK_URL не задан — прогон пропущен")
        return stats

    hashes = load_local_hashes()
    deals = pull_deals()
    stats["total"] = len(deals)

    for deal in deals:
        checked_at = _now_label()
        resolved = resolve_court_from_kb(deal)
        if resolved.get("status") == "found":
            stats["resolved"] += 1
            court = resolved["court"]
            if not DRY_RUN:
                push_fields(deal.id, {
                    UF_COURT_WEBSITE: court.get("website") or "",
                    UF_COURT_NAME: court.get("name") or deal.court_name or "",
                    UF_REGION: court.get("region") or deal.region or "",
                    UF_CITY: court.get("city") or deal.city or "",
                    UF_DISTRICT: court.get("district") or deal.district or "",
                })
        elif resolved.get("status") == "skipped":
            logger.info("Deal %s: court KB skipped — %s", deal.id, resolved.get("result"))
        else:
            logger.warning("Deal %s: court KB %s — %s", deal.id, resolved.get("status"), resolved.get("result"))

        try:
            parsed = lookup_delo(deal, resolved)
        except Exception as exc:
            logger.error("Parser failed for deal %s: %s", deal.id, exc)
            stats["errors"] += 1
            continue

        status = parsed.get("status")
        if status != "found":
            if status == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1
                note = (
                    f"[БитриксЮрист] Проверка не удалась\n"
                    f"Проверено: {checked_at}\n"
                    f"Номер: {deal.case_number}\n"
                    f"Суд БЗ: {(resolved.get('court') or {}).get('name') or 'не найден'}\n"
                    f"Причина: {status} — {parsed.get('result')}\n"
                    f"Клиенту формулировку «дело обновлено» не писать."
                )
                if not DRY_RUN:
                    push_fields(deal.id, {
                        UF_LAST_STATUS: f"{status}: {str(parsed.get('result'))[:200]}",
                        UF_LAST_CHECK_AT: checked_at,
                    })
                    comment_timeline(deal.id, note)
            time.sleep(PAUSE_BETWEEN_DEALS_SEC)
            continue

        digest, status_text = card_digest(parsed)
        prev = deal.snapshot_hash or hashes.get(str(deal.id))
        changed = prev != digest
        comment = format_comment(deal, parsed, changed, checked_at, resolved)

        if DRY_RUN:
            logger.info("DRY_RUN deal %s changed=%s", deal.id, changed)
        else:
            push_fields(deal.id, {
                UF_LAST_STATUS: status_text[:250],
                UF_LAST_CHECK_AT: checked_at,
                UF_SNAPSHOT_HASH: digest,
            })
            if changed or not COMMENT_ONLY_ON_CHANGE:
                comment_timeline(deal.id, comment)

        hashes[str(deal.id)] = digest
        stats["changed" if changed else "unchanged"] += 1
        time.sleep(PAUSE_BETWEEN_DEALS_SEC)

    save_local_hashes(hashes)
    logger.info("Job done: %s", stats)
    return stats


if __name__ == "__main__":
    run_daily_job()
