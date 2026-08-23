"""
БитриксЮрист — обход воронки Bitrix24 и запись факта проверки в ленту карточки.

Третий контур: план Cursor + ваш bitrix.py + тот же POST /delo, что у Анны.
Воркфлоу court-agent-yurist и агента Анну этот модуль не меняет.

n8n (новый path bitrix-yurist-daily) -> run_daily_job()
  pull_deals -> lookup_delo (Аннин API) -> diff -> update fields + timeline comment
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

VORONEZH_SLUGS = (
    "sovetsky-vrn",
    "kominternovsky-vrn",
    "zheleznodorozhny-vrn",
    "levoberezhny-vrn",
    "centralny-vrn",
    "lensud-vrn",
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    return [x.strip() for x in raw.split(",") if x.strip()]


BITRIX_WEBHOOK_URL = _env("BITRIX_WEBHOOK_URL")
CATEGORY_ID = int(_env("BITRIX_CATEGORY_ID") or "0")
WORKING_STAGE_IDS = _env_list("BITRIX_STAGE_IDS")
UF_CASE_NUMBER = _env("UF_CASE_NUMBER") or "UF_CRM_CASE_NUMBER"
UF_COURT_SLUG = _env("UF_COURT_SLUG") or "UF_CRM_COURT"
UF_LAST_STATUS = _env("UF_LAST_STATUS") or "UF_CRM_LAST_STATUS"
UF_LAST_CHECK_AT = _env("UF_LAST_CHECK_AT") or "UF_CRM_LAST_CHECK_AT"
UF_SNAPSHOT_HASH = _env("UF_SNAPSHOT_HASH") or "UF_CRM_SNAPSHOT_HASH"

COURT_KB_API_URL = (_env("COURT_KB_API_URL") or "http://127.0.0.1:8080").rstrip("/")
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
    snapshot_hash: Optional[str]
    raw: dict = field(default_factory=dict)


def _now_msk() -> datetime:
    return datetime.now(TZ)


def _now_label() -> str:
    return _now_msk().strftime("%d.%m.%Y %H:%M") + " (МСК)"


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
                wait = 1.5 * (attempt + 1)
                logger.warning("Rate limit, retry in %.1fs", wait)
                time.sleep(wait)
                continue
            raise BitrixError(f"{method} failed: {data['error']} — {data.get('error_description')}")
        return data
    raise BitrixError(f"{method}: retries exhausted on QUERY_LIMIT_EXCEEDED")


def _is_filled(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def normalize_slug(raw: Any) -> Optional[str]:
    text = str(raw or "").strip().lower()
    if not text:
        return None
    for slug in VORONEZH_SLUGS:
        if slug in text:
            return slug
    aliases = {
        "советск": "sovetsky-vrn",
        "sovetsky": "sovetsky-vrn",
        "коминтерн": "kominternovsky-vrn",
        "komintern": "kominternovsky-vrn",
        "железнодорож": "zheleznodorozhny-vrn",
        "zheleznodorozh": "zheleznodorozhny-vrn",
        "левобереж": "levoberezhny-vrn",
        "levoberezh": "levoberezhny-vrn",
        "центральн": "centralny-vrn",
        "centraln": "centralny-vrn",
        "ленинск": "lensud-vrn",
        "leninsk": "lensud-vrn",
        "lensud": "lensud-vrn",
    }
    for needle, slug in aliases.items():
        if needle in text:
            return slug
    return None


def pull_deals() -> list[Deal]:
    """Сделки воронки с непустым номером дела. Пустые значения отсекаем в Python."""
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
                UF_CASE_NUMBER, UF_COURT_SLUG, UF_SNAPSHOT_HASH, "UF_*",
            ],
            "start": start,
        })
        batch = data.get("result") or []
        if not batch:
            break
        for item in batch:
            case_number = item.get(UF_CASE_NUMBER)
            if not _is_filled(case_number):
                continue
            deals.append(Deal(
                id=int(item["ID"]),
                title=item.get("TITLE") or "",
                stage_id=item.get("STAGE_ID") or "",
                contact_id=int(item["CONTACT_ID"]) if item.get("CONTACT_ID") else None,
                case_number=str(case_number).strip(),
                court_slug=normalize_slug(item.get(UF_COURT_SLUG))
                or normalize_slug(item.get("COMMENTS")),
                snapshot_hash=str(item.get(UF_SNAPSHOT_HASH) or "") or None,
                raw=item,
            ))
        next_start = data.get("next")
        if next_start is None:
            break
        start = next_start
        time.sleep(RATE_LIMIT_SLEEP)

    logger.info("Pulled %d deals with case number", len(deals))
    return deals


def lookup_delo(deal: Deal) -> dict[str, Any]:
    """Тот же контракт, что у Анны: POST /delo. Своя копия на :8081, с ретраями."""
    if not deal.court_slug or deal.court_slug not in VORONEZH_SLUGS:
        return {"status": "skipped", "result": "Нет court_slug из пилота (6 судов Воронежа)"}
    headers = {"Content-Type": "application/json"}
    if COURT_KB_API_KEY:
        headers["X-API-Key"] = COURT_KB_API_KEY
    payload = {
        "mode": "case",
        "court_slug": deal.court_slug,
        "case_number": deal.case_number,
        "last_name": None,
        "production_type": "civil_first_instance",
    }
    last: dict[str, Any] = {"status": "error", "result": "парсер не ответил"}
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{COURT_KB_API_URL}/delo",
                json=payload,
                headers=headers,
                timeout=120,
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
        if body.get("status") in {"found", "not_found", "skipped"}:
            return body
        logger.warning("Parser attempt %s for deal %s: %s", attempt + 1, deal.id, body.get("result"))
        time.sleep(2 * (attempt + 1))
    return last


def card_digest(parsed: dict[str, Any]) -> tuple[str, str]:
    result = parsed.get("result")
    if isinstance(result, dict):
        payload = result
        status_text = str(result.get("status") or result.get("result") or json.dumps(result, ensure_ascii=False)[:500])
    else:
        payload = {"result": result}
        status_text = str(result or "")
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


def push_fields(deal_id: int, status_text: str, digest: str, checked_at: str) -> None:
    _call("crm.deal.update", {
        "id": deal_id,
        "fields": {
            UF_LAST_STATUS: status_text[:250],
            UF_LAST_CHECK_AT: checked_at,
            UF_SNAPSHOT_HASH: digest,
        },
    })
    time.sleep(RATE_LIMIT_SLEEP)


def comment_timeline(deal_id: int, text: str) -> None:
    _call("crm.timeline.comment.add", {
        "fields": {
            "ENTITY_ID": deal_id,
            "ENTITY_TYPE": "deal",
            "COMMENT": text,
        },
    })
    time.sleep(RATE_LIMIT_SLEEP)


def format_comment(deal: Deal, parsed: dict[str, Any], changed: bool, checked_at: str) -> str:
    status = parsed.get("status")
    result = parsed.get("result")
    lines = [
        "[БитриксЮрист] Обновление дела произведено" if changed else "[БитриксЮрист] Проверка дела выполнена, изменений нет",
        f"Проверено: {checked_at}",
        f"Номер: {deal.case_number}",
        f"Суд: {deal.court_slug}",
        f"Ответ парсера: {status}",
    ]
    if isinstance(result, dict):
        for key in ("result", "status", "hearing", "next_date", "judge", "url", "card_url"):
            if result.get(key):
                lines.append(f"{key}: {result[key]}")
    elif result:
        lines.append(str(result)[:1500])
    return "\n".join(lines)


def run_daily_job() -> dict[str, int]:
    stats = {"total": 0, "changed": 0, "unchanged": 0, "errors": 0, "skipped": 0}
    if not BITRIX_WEBHOOK_URL or "YOUR_PORTAL" in BITRIX_WEBHOOK_URL:
        logger.warning(
            "BITRIX_WEBHOOK_URL не задан — прогон пропущен (каркас на VPS готов, ждём входящий вебхук)."
        )
        return stats
    hashes = load_local_hashes()
    deals = pull_deals()
    stats["total"] = len(deals)

    for deal in deals:
        try:
            parsed = lookup_delo(deal)
        except Exception as exc:
            logger.error("Parser failed for deal %s: %s", deal.id, exc)
            stats["errors"] += 1
            continue

        status = parsed.get("status")
        if status in {"skipped", "error", "not_found"} or status != "found":
            if status == "skipped":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1
                checked_at = _now_label()
                note = (
                    f"[БитриксЮрист] Проверка не удалась\n"
                    f"Проверено: {checked_at}\n"
                    f"Номер: {deal.case_number}\n"
                    f"Причина: {status} — {parsed.get('result')}\n"
                    f"Клиенту формулировку «дело обновлено» не писать."
                )
                if not DRY_RUN:
                    push_fields(deal.id, f"{status}: {parsed.get('result')}", "", checked_at)
                    comment_timeline(deal.id, note)
            time.sleep(PAUSE_BETWEEN_DEALS_SEC)
            continue

        digest, status_text = card_digest(parsed)
        prev = deal.snapshot_hash or hashes.get(str(deal.id))
        changed = prev != digest
        checked_at = _now_label()
        comment = format_comment(deal, parsed, changed, checked_at)

        if DRY_RUN:
            logger.info("DRY_RUN deal %s changed=%s hash=%s", deal.id, changed, digest)
        else:
            push_fields(deal.id, status_text, digest, checked_at)
            if changed or not COMMENT_ONLY_ON_CHANGE:
                comment_timeline(deal.id, comment)

        hashes[str(deal.id)] = digest
        if changed:
            stats["changed"] += 1
        else:
            stats["unchanged"] += 1
        time.sleep(PAUSE_BETWEEN_DEALS_SEC)

    save_local_hashes(hashes)
    logger.info("Job done: %s", stats)
    return stats


if __name__ == "__main__":
    run_daily_job()
