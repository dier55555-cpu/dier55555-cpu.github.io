"""Саприн и партнеры — мониторинг сделок Bitrix24 → парсер sudrf на VPS.

Отдельный контур (не Анна). Мировые суды не парсим.
Номер дела и ссылка на карточку берутся из UF клиента.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("saprin-bitrix")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    return [x.strip() for x in raw.split(",") if x.strip()]


BITRIX_WEBHOOK_URL = _env("BITRIX_WEBHOOK_URL")
CATEGORY_ID = int(_env("BITRIX_CATEGORY_ID") or "2")
WORKING_STAGE_IDS = _env_list("BITRIX_STAGE_IDS")

# Клиентские поля (уже есть на портале)
UF_CASE_NUMBER = _env("UF_CASE_NUMBER") or "UF_CRM_1741881362933"
UF_COURT_URLS = _env_list("UF_COURT_URLS") or [
    "UF_CRM_1747812731315",
    "UF_CRM_1742479380838",
    "UF_CRM_1739466337400",
    "UF_CRM_1773392832151",
    "UF_CRM_1782973730098",
]

# Служебные (создаём при внедрении)
UF_LAST_STATUS = _env("UF_LAST_STATUS") or "UF_CRM_SAPRIN_LAST_STATUS"
UF_LAST_CHECK_AT = _env("UF_LAST_CHECK_AT") or "UF_CRM_SAPRIN_LAST_CHECK"
UF_SNAPSHOT_HASH = _env("UF_SNAPSHOT_HASH") or "UF_CRM_SAPRIN_SNAP_HASH"
UF_LAST_KNOWN_STAGE = _env("UF_LAST_KNOWN_STAGE") or "UF_CRM_SAPRIN_KNOWN_STAGE"
UF_COURT_WEBSITE = _env("UF_COURT_WEBSITE") or "UF_CRM_SAPRIN_COURT_SITE"

COURT_KB_API_URL = (_env("COURT_KB_API_URL") or "http://127.0.0.1:8081").rstrip("/")
COURT_KB_API_KEY = _env("COURT_KB_API_KEY")

DRY_RUN = _env("DRY_RUN", "1") not in {"0", "false", "False"}
COMMENT_ONLY_ON_CHANGE = _env("COMMENT_ONLY_ON_CHANGE", "1") not in {"0", "false", "False"}
PAUSE_BETWEEN_DEALS_SEC = float(_env("PAUSE_BETWEEN_DEALS_SEC") or "5")
LIMIT_DEALS = int(_env("LIMIT_DEALS") or "0")  # 0 = все
TZ = ZoneInfo(_env("TZ") or "Europe/Moscow")
RATE_LIMIT_SLEEP = 0.55
SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "data", "snapshots.json")

CASE_RE = re.compile(r"(?<![A-Za-zА-Яа-я0-9])([12])-(\d{1,6})/(\d{4})(?![0-9])")
SUDRF_RE = re.compile(r"https?://([a-z0-9.-]+\.sudrf\.ru)", re.I)


class BitrixError(Exception):
    pass


@dataclass
class Deal:
    id: int
    title: str
    stage_id: str
    case_number: Optional[str]
    court_website: Optional[str]
    snapshot_hash: Optional[str]
    last_known_stage: Optional[str]
    raw: dict = field(default_factory=dict)


def _now_label() -> str:
    return datetime.now(TZ).strftime("%d.%m.%Y %H:%M") + " (МСК)"


def extract_case_number(raw: Any) -> Optional[str]:
    """Берём номер вида 2-1248/2026; М-… игнорируем как старт мониторинга."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # предпочитаем номер на 2-
    twos = [m for m in CASE_RE.finditer(text) if m.group(1) == "2"]
    if twos:
        m = twos[0]
        return f"{m.group(1)}-{m.group(2)}/{m.group(3)}"
    ones = list(CASE_RE.finditer(text))
    if ones:
        m = ones[0]
        return f"{m.group(1)}-{m.group(2)}/{m.group(3)}"
    return None


def extract_court_website(raw_deal: dict) -> Optional[str]:
    for uf in UF_COURT_URLS:
        val = raw_deal.get(uf)
        if not val:
            continue
        text = str(val).strip()
        m = SUDRF_RE.search(text)
        if m:
            return f"https://{m.group(1).lower()}/"
        if "sudrf.ru" in text.lower():
            try:
                p = urlparse(text if "://" in text else f"https://{text}")
                if p.hostname and p.hostname.endswith("sudrf.ru"):
                    return f"https://{p.hostname.lower()}/"
            except Exception:
                continue
    # нормализованное служебное поле
    site = raw_deal.get(UF_COURT_WEBSITE)
    if site and "sudrf.ru" in str(site).lower():
        m = SUDRF_RE.search(str(site))
        if m:
            return f"https://{m.group(1).lower()}/"
    return None


def _call(method: str, params: dict) -> dict:
    if not BITRIX_WEBHOOK_URL or "YOUR_PORTAL" in BITRIX_WEBHOOK_URL:
        raise BitrixError("BITRIX_WEBHOOK_URL не задан")
    url = f"{BITRIX_WEBHOOK_URL.rstrip('/')}/{method}.json"
    for attempt in range(5):
        resp = requests.post(url, json=params, timeout=45)
        try:
            data = resp.json()
        except ValueError as exc:
            raise BitrixError(f"{method}: не JSON (HTTP {resp.status_code})") from exc
        if "error" in data:
            if data["error"] == "QUERY_LIMIT_EXCEEDED":
                time.sleep(1.5 * (attempt + 1))
                continue
            raise BitrixError(f"{method} failed: {data['error']} — {data.get('error_description')}")
        return data
    raise BitrixError(f"{method}: retries exhausted")


def pull_deals() -> list[Deal]:
    deals: list[Deal] = []
    filter_: dict[str, Any] = {"CATEGORY_ID": CATEGORY_ID}
    if WORKING_STAGE_IDS:
        filter_["@STAGE_ID"] = WORKING_STAGE_IDS
    select = [
        "ID", "TITLE", "STAGE_ID",
        UF_CASE_NUMBER, UF_SNAPSHOT_HASH, UF_LAST_KNOWN_STAGE, UF_COURT_WEBSITE,
        *UF_COURT_URLS,
    ]
    start = 0
    while True:
        data = _call("crm.deal.list", {
            "filter": filter_,
            "select": select,
            "start": start,
        })
        batch = data.get("result") or []
        if not batch:
            break
        for item in batch:
            case_number = extract_case_number(item.get(UF_CASE_NUMBER))
            if not case_number or not case_number.startswith("2-"):
                continue
            website = extract_court_website(item)
            deals.append(Deal(
                id=int(item["ID"]),
                title=item.get("TITLE") or "",
                stage_id=item.get("STAGE_ID") or "",
                case_number=case_number,
                court_website=website,
                snapshot_hash=(str(item.get(UF_SNAPSHOT_HASH)).strip() if item.get(UF_SNAPSHOT_HASH) else None),
                last_known_stage=(str(item.get(UF_LAST_KNOWN_STAGE)).strip() if item.get(UF_LAST_KNOWN_STAGE) else None),
                raw=item,
            ))
            if LIMIT_DEALS and len(deals) >= LIMIT_DEALS:
                logger.info("LIMIT_DEALS=%s reached", LIMIT_DEALS)
                return deals
        next_start = data.get("next")
        if next_start is None:
            break
        start = next_start
        time.sleep(RATE_LIMIT_SLEEP)
    logger.info("Pulled %d deals with 2- case number", len(deals))
    return deals


def _api_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if COURT_KB_API_KEY:
        headers["X-API-Key"] = COURT_KB_API_KEY
    return headers


def lookup_delo(deal: Deal) -> dict[str, Any]:
    if not deal.court_website:
        return {"status": "skipped", "result": "нет ссылки на сайт суда (sudrf) в карточке"}
    if "msudrf.ru" in deal.court_website.lower():
        return {"status": "skipped", "result": "мировые суды исключены из объёма"}

    payload = {
        "mode": "case",
        "case_number": deal.case_number,
        "website": deal.court_website,
        "production_type": "civil_first_instance",
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
        if body.get("status") in {"found", "not_found", "skipped", "captcha_required", "blocked"}:
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
    # не падаем, если служебное поле ещё не создано
    try:
        _call("crm.deal.update", {"id": deal_id, "fields": fields})
    except BitrixError as exc:
        logger.error("deal.update %s failed: %s", deal_id, exc)
    time.sleep(RATE_LIMIT_SLEEP)


def comment_timeline(deal_id: int, text: str) -> None:
    _call("crm.timeline.comment.add", {
        "fields": {"ENTITY_ID": deal_id, "ENTITY_TYPE": "deal", "COMMENT": text},
    })
    time.sleep(RATE_LIMIT_SLEEP)


def format_comment(deal: Deal, parsed: dict[str, Any], changed: bool, checked_at: str) -> str:
    lines = [
        "[Саприн] Обновление дела произведено" if changed else "[Саприн] Проверка дела выполнена, изменений нет",
        f"Проверено: {checked_at}",
        f"Номер: {deal.case_number}",
        f"Сайт: {deal.court_website or '—'}",
        f"Ответ парсера: {parsed.get('status')}",
    ]
    result = parsed.get("result")
    if result:
        lines.append(str(result)[:1500])
    return "\n".join(lines)


def detect_manual_stage_move(deal: Deal) -> Optional[str]:
    """§2 ТЗ: сверка STAGE_ID со служебным полем."""
    if not deal.last_known_stage:
        return None
    if deal.last_known_stage == deal.stage_id:
        return None
    return (
        "[Саприн] Зафиксировано ручное изменение этапа воронки сотрудником. "
        f"Было: {deal.last_known_stage}, стало: {deal.stage_id}. "
        "Мониторинг продолжен по правилам нового этапа."
    )


def run_daily_job() -> dict[str, int]:
    stats = {
        "total": 0, "changed": 0, "unchanged": 0, "errors": 0, "skipped": 0, "manual": 0,
    }
    if not BITRIX_WEBHOOK_URL or "YOUR_PORTAL" in BITRIX_WEBHOOK_URL:
        logger.warning("BITRIX_WEBHOOK_URL не задан — прогон пропущен")
        return stats

    hashes = load_local_hashes()
    deals = pull_deals()
    stats["total"] = len(deals)

    for deal in deals:
        checked_at = _now_label()
        manual_note = detect_manual_stage_move(deal)
        if manual_note:
            stats["manual"] += 1
            logger.info("Deal %s manual stage move", deal.id)
            if not DRY_RUN:
                comment_timeline(deal.id, manual_note)
                push_fields(deal.id, {UF_LAST_KNOWN_STAGE: deal.stage_id})

        try:
            parsed = lookup_delo(deal)
        except Exception as exc:
            logger.error("Parser failed for deal %s: %s", deal.id, exc)
            stats["errors"] += 1
            continue

        status = parsed.get("status")
        if status != "found":
            if status == "skipped":
                stats["skipped"] += 1
                logger.info("Deal %s skipped: %s", deal.id, parsed.get("result"))
            else:
                stats["errors"] += 1
                note = (
                    f"[Саприн] Проверка не удалась\n"
                    f"Проверено: {checked_at}\n"
                    f"Номер: {deal.case_number}\n"
                    f"Сайт: {deal.court_website or '—'}\n"
                    f"Причина: {status} — {parsed.get('result')}"
                )
                logger.warning("Deal %s: %s", deal.id, note.replace("\n", " | "))
                if not DRY_RUN:
                    push_fields(deal.id, {
                        UF_LAST_STATUS: f"{status}: {str(parsed.get('result'))[:200]}",
                        UF_LAST_CHECK_AT: checked_at,
                        UF_LAST_KNOWN_STAGE: deal.stage_id,
                    })
                    comment_timeline(deal.id, note)
            time.sleep(PAUSE_BETWEEN_DEALS_SEC)
            continue

        digest, status_text = card_digest(parsed)
        prev = deal.snapshot_hash or hashes.get(str(deal.id))
        changed = prev != digest
        comment = format_comment(deal, parsed, changed, checked_at)

        if DRY_RUN:
            logger.info(
                "DRY_RUN deal %s %s changed=%s status_len=%s",
                deal.id, deal.case_number, changed, len(status_text),
            )
        else:
            fields = {
                UF_LAST_STATUS: status_text[:250],
                UF_LAST_CHECK_AT: checked_at,
                UF_SNAPSHOT_HASH: digest,
                UF_LAST_KNOWN_STAGE: deal.stage_id,
                UF_COURT_WEBSITE: deal.court_website or "",
            }
            push_fields(deal.id, fields)
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
