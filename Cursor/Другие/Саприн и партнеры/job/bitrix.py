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

from court_pool import CourtParsePool, court_host
from triggers import (
    AUTOMATED_STAGES,
    STAGE_DDU_NAME,
    build_appeal_from_text,
    build_appeal_movement_from_sections,
    build_movement_from_card_sections,
    build_movement_from_text,
    can_auto_move,
    decide_next_stage,
    detect_tabs,
    parse_ru_date,
    set_stage_ddu,
)
from calendar_alerts import post_stage_alert, probe_calendar
from triggers import StageAlert

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
UF_DECISION_DATE = _env("UF_DECISION_DATE") or "UF_CRM_SAPRIN_DECISION_DATE"
UF_DECISION_PUBLISHED = _env("UF_DECISION_PUBLISHED") or "UF_CRM_SAPRIN_DECISION_PUB"
UF_DEADLINE_40D = _env("UF_DEADLINE_40D") or "UF_CRM_SAPRIN_DEADLINE_40D"
UF_STAGE_ENTER = _env("UF_STAGE_ENTER") or "UF_CRM_SAPRIN_STAGE_ENTER"
UF_APPEAL_RESULT = _env("UF_APPEAL_RESULT") or "UF_CRM_SAPRIN_APPEAL_RESULT"
APPLY_STAGE_MOVES = _env("APPLY_STAGE_MOVES", "1") not in {"0", "false", "False"}

COURT_KB_API_URL = (_env("COURT_KB_API_URL") or "http://127.0.0.1:8081").rstrip("/")
COURT_KB_API_KEY = _env("COURT_KB_API_KEY")

DRY_RUN = _env("DRY_RUN", "1") not in {"0", "false", "False"}
COMMENT_ONLY_ON_CHANGE = _env("COMMENT_ONLY_ON_CHANGE", "1") not in {"0", "false", "False"}
PAUSE_BETWEEN_DEALS_SEC = float(_env("PAUSE_BETWEEN_DEALS_SEC") or "5")
# Сколько РАЗНЫХ судов дергать сразу (I/O). Один hostname — всегда очередь.
PARSE_CONCURRENCY = int(_env("PARSE_CONCURRENCY") or "6")
PARSE_HOST_PAUSE_SEC = float(_env("PARSE_HOST_PAUSE_SEC") or "0.8")
LIMIT_DEALS = int(_env("LIMIT_DEALS") or "0")  # 0 = все
TZ = ZoneInfo(_env("TZ") or "Europe/Moscow")
RATE_LIMIT_SLEEP = 0.55
SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "data", "snapshots.json")

CASE_RE = re.compile(r"(?<![A-Za-zА-Яа-я0-9])([12])-(\d{1,6})/(\d{4})(?![0-9])")
SUDRF_RE = re.compile(r"https?://([a-z0-9.-]+\.sudrf\.ru)", re.I)

# Нет URL и нет сохранённого сайта — не перебираем суды области.
SKIP_NO_COURT_MARKER = "нет_сайта_суда"
MSG_NO_COURT = (
    "Нет сайта суда и нет данных, по какому райсуду искать. "
    "Укажите ссылку на дело или название суда."
)


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
    last_status: Optional[str] = None
    decision_date: Optional[str] = None
    decision_published: Optional[str] = None
    deadline_40d: Optional[str] = None
    stage_enter: Optional[str] = None
    appeal_result: Optional[str] = None
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
        UF_LAST_STATUS, UF_LAST_CHECK_AT,
        UF_DECISION_DATE, UF_DECISION_PUBLISHED, UF_DEADLINE_40D, UF_STAGE_ENTER, UF_APPEAL_RESULT,
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
            def _uf(name: str) -> Optional[str]:
                v = item.get(name)
                return str(v).strip() if v not in (None, "", False, [], {}) else None

            deals.append(Deal(
                id=int(item["ID"]),
                title=item.get("TITLE") or "",
                stage_id=item.get("STAGE_ID") or "",
                case_number=case_number,
                court_website=website,
                snapshot_hash=_uf(UF_SNAPSHOT_HASH),
                last_known_stage=_uf(UF_LAST_KNOWN_STAGE),
                last_status=_uf(UF_LAST_STATUS),
                decision_date=_uf(UF_DECISION_DATE),
                decision_published=_uf(UF_DECISION_PUBLISHED),
                deadline_40d=_uf(UF_DEADLINE_40D),
                stage_enter=_uf(UF_STAGE_ENTER),
                appeal_result=_uf(UF_APPEAL_RESULT),
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
        # Не перебираем все райсуды области — без сайта/названия суда стоп + комментарий.
        return {
            "status": "skipped",
            "reason": SKIP_NO_COURT_MARKER,
            "result": MSG_NO_COURT,
        }
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


def move_stage(deal_id: int, stage_id: str) -> None:
    _call("crm.deal.update", {"id": deal_id, "fields": {"STAGE_ID": stage_id}})
    time.sleep(RATE_LIMIT_SLEEP)


def apply_trigger_fields(decision_fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    mapping = {
        "decision_date": UF_DECISION_DATE,
        "decision_published_at": UF_DECISION_PUBLISHED,
        "deadline_40d": UF_DEADLINE_40D,
        "appeal_result": UF_APPEAL_RESULT,
    }
    for key, uf in mapping.items():
        if decision_fields.get(key):
            out[uf] = decision_fields[key]
    return out


def resolve_stage_ddu() -> Optional[str]:
    """Ищет STAGE_ID «ДДУ 2025 год» в воронке CATEGORY_ID."""
    env_id = _env("STAGE_DDU")
    if env_id:
        set_stage_ddu(env_id)
        return env_id
    try:
        data = _call("crm.dealcategory.stage.list", {"id": CATEGORY_ID})
    except BitrixError as exc:
        logger.error("stage.list failed: %s", exc)
        return None
    stages = data.get("result") or []
    needle = STAGE_DDU_NAME.lower()
    for st in stages:
        name = str(st.get("NAME") or st.get("STATUS_ID") or "")
        if needle in name.lower() or ("дду" in name.lower() and "2025" in name):
            sid = str(st.get("STATUS_ID") or "")
            if sid:
                set_stage_ddu(sid)
                logger.info("Resolved STAGE_DDU=%s (%s)", sid, name)
                return sid
    logger.warning("Этап «%s» не найден в category %s", STAGE_DDU_NAME, CATEGORY_ID)
    return None


def run_triggers(deal: Deal, parsed: dict[str, Any]) -> dict[str, Any]:
    """Возвращает decision dict для логов/записи."""
    sections = parsed.get("sections") or {}
    rows = build_movement_from_card_sections(sections)
    if not rows:
        rows = build_movement_from_text(str(parsed.get("result") or ""))
    appeal_rows = build_appeal_movement_from_sections(sections)
    if not appeal_rows:
        appeal_rows = build_appeal_from_text(str(parsed.get("result") or ""))
    merged_sections = dict(sections)
    for name in parsed.get("section_names") or []:
        merged_sections.setdefault(str(name), [])
    tabs = detect_tabs(str(parsed.get("result") or ""), merged_sections)

    decision = decide_next_stage(
        current_stage=deal.stage_id,
        rows=rows,
        tabs=tabs,
        appeal_rows=appeal_rows,
        decision_final_date=parse_ru_date(deal.decision_date or ""),
        decision_published_at=parse_ru_date(deal.decision_published or ""),
        stage_enter_date=parse_ru_date(deal.stage_enter or ""),
        appeal_result=deal.appeal_result,
    )
    return {
        "action": decision.action,
        "to_stage": decision.to_stage,
        "reason": decision.reason,
        "comment": decision.comment,
        "fields": decision.fields,
        "movement_rows": len(rows),
        "appeal_rows": len(appeal_rows),
        "alerts": [
            {
                "kind": a.kind,
                "current_stage": a.current_stage,
                "expected_stage": a.expected_stage,
                "detail": a.detail,
            }
            for a in (decision.alerts or [])
        ],
    }


def emit_alerts(deal: Deal, alerts: list[dict[str, Any]] | list[StageAlert]) -> None:
    for raw in alerts or []:
        if isinstance(raw, StageAlert):
            alert = raw
        else:
            alert = StageAlert(
                kind=str(raw.get("kind") or "?"),
                current_stage=str(raw.get("current_stage") or deal.stage_id),
                expected_stage=raw.get("expected_stage"),
                detail=str(raw.get("detail") or ""),
            )
        try:
            post_stage_alert(
                call=_call,
                webhook_url=BITRIX_WEBHOOK_URL,
                deal_id=deal.id,
                case_number=deal.case_number or "",
                alert=alert,
                dry_run=DRY_RUN,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("calendar alert failed deal=%s: %s", deal.id, exc)


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


def detect_manual_stage_move(deal: Deal) -> Optional[tuple[str, StageAlert]]:
    """§2 ТЗ: сверка STAGE_ID со служебным полем → комментарий + alert C."""
    if not deal.last_known_stage:
        return None
    if deal.last_known_stage == deal.stage_id:
        return None
    note = (
        "[Саприн] Зафиксировано ручное изменение этапа воронки сотрудником. "
        f"Было: {deal.last_known_stage}, стало: {deal.stage_id}. "
        "Мониторинг продолжен по правилам нового этапа."
    )
    alert = StageAlert(
        kind="C",
        current_stage=deal.stage_id,
        expected_stage=deal.last_known_stage,
        detail=f"ручной/внешний скачок: {deal.last_known_stage} → {deal.stage_id}",
    )
    return note, alert


def run_daily_job() -> dict[str, int]:
    stats = {
        "total": 0, "changed": 0, "unchanged": 0, "errors": 0, "skipped": 0,
        "manual": 0, "moved": 0, "trigger_stop": 0, "alerts": 0,
    }
    if not BITRIX_WEBHOOK_URL or "YOUR_PORTAL" in BITRIX_WEBHOOK_URL:
        logger.warning("BITRIX_WEBHOOK_URL не задан — прогон пропущен")
        return stats

    ddu = resolve_stage_ddu()
    logger.info("STAGE_DDU=%s", ddu or "NOT FOUND")
    try:
        cal = probe_calendar(_call)
        logger.info("Calendar probe: %s", cal)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Calendar probe failed: %s", exc)

    hashes = load_local_hashes()
    deals = pull_deals()
    stats["total"] = len(deals)

    to_parse = [d for d in deals if d.stage_id in AUTOMATED_STAGES]
    parsed_by_id: dict[int, tuple[Optional[dict[str, Any]], Optional[BaseException]]] = {}
    workers = max(1, PARSE_CONCURRENCY)
    logger.info(
        "Parse %s deals, concurrency=%s (разные суды параллельно, один хост — очередь)",
        len(to_parse), workers,
    )
    if to_parse:
        pool = CourtParsePool(workers, host_pause_sec=PARSE_HOST_PAUSE_SEC)
        for deal, parsed, err in pool.run(to_parse, lambda d: court_host(d.court_website), lookup_delo):
            parsed_by_id[deal.id] = (parsed, err)

    for deal in deals:
        checked_at = _now_label()
        today_iso = datetime.now(TZ).date().isoformat()
        manual = detect_manual_stage_move(deal)
        if manual:
            manual_note, manual_alert = manual
            stats["manual"] += 1
            logger.info("Deal %s manual stage move", deal.id)
            emit_alerts(deal, [manual_alert])
            stats["alerts"] += 1
            if not DRY_RUN:
                comment_timeline(deal.id, manual_note)
                push_fields(deal.id, {
                    UF_LAST_KNOWN_STAGE: deal.stage_id,
                    UF_STAGE_ENTER: today_iso,
                })

        if deal.stage_id not in AUTOMATED_STAGES:
            stats["skipped"] += 1
            logger.info("Deal %s stage %s not automated — skip parse", deal.id, deal.stage_id)
            continue

        parsed, parse_exc = parsed_by_id.get(deal.id, (None, RuntimeError("no parse result")))
        if parse_exc or not parsed:
            logger.error("Parser failed for deal %s: %s", deal.id, parse_exc or "empty")
            stats["errors"] += 1
            continue

        status = parsed.get("status")
        if status != "found":
            if status == "skipped":
                stats["skipped"] += 1
                reason = str(parsed.get("reason") or "")
                msg = str(parsed.get("result") or "")
                logger.info("Deal %s skipped: %s", deal.id, msg)
                if reason == SKIP_NO_COURT_MARKER:
                    already = SKIP_NO_COURT_MARKER in (deal.last_status or "")
                    status_mark = f"{SKIP_NO_COURT_MARKER}: {MSG_NO_COURT}"[:250]
                    if DRY_RUN:
                        logger.info(
                            "DRY_RUN deal %s no-court comment=%s",
                            deal.id, "skip-already" if already else "would-post",
                        )
                    else:
                        push_fields(deal.id, {
                            UF_LAST_STATUS: status_mark,
                            UF_LAST_CHECK_AT: checked_at,
                            UF_LAST_KNOWN_STAGE: deal.stage_id,
                        })
                        if not already:
                            comment_timeline(
                                deal.id,
                                f"[Саприн] {MSG_NO_COURT}\n"
                                f"Номер дела: {deal.case_number or '—'}\n"
                                f"Проверено: {checked_at}",
                            )
                elif msg:
                    if not DRY_RUN:
                        push_fields(deal.id, {
                            UF_LAST_STATUS: f"skipped: {msg}"[:250],
                            UF_LAST_CHECK_AT: checked_at,
                            UF_LAST_KNOWN_STAGE: deal.stage_id,
                        })
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
            continue

        digest, status_text = card_digest(parsed)
        prev = deal.snapshot_hash or hashes.get(str(deal.id))
        changed = prev != digest
        comment = format_comment(deal, parsed, changed, checked_at)

        trig = run_triggers(deal, parsed)
        logger.info(
            "Deal %s trigger action=%s to=%s reason=%s rows=%s appeal_rows=%s alerts=%s",
            deal.id, trig["action"], trig.get("to_stage"), trig.get("reason"),
            trig.get("movement_rows"), trig.get("appeal_rows"), len(trig.get("alerts") or []),
        )

        if trig.get("alerts"):
            emit_alerts(deal, trig["alerts"])
            stats["alerts"] += len(trig["alerts"])

        if DRY_RUN:
            logger.info(
                "DRY_RUN deal %s %s changed=%s trigger=%s to=%s",
                deal.id, deal.case_number, changed, trig["action"], trig.get("to_stage"),
            )
        else:
            fields = {
                UF_LAST_STATUS: status_text[:250],
                UF_LAST_CHECK_AT: checked_at,
                UF_SNAPSHOT_HASH: digest,
                UF_LAST_KNOWN_STAGE: deal.stage_id,
                UF_COURT_WEBSITE: deal.court_website or "",
            }
            fields.update(apply_trigger_fields(trig.get("fields") or {}))
            if not deal.stage_enter:
                fields[UF_STAGE_ENTER] = today_iso

            if trig["action"] == "move" and trig.get("to_stage") and APPLY_STAGE_MOVES:
                to_stage = trig["to_stage"]
                if can_auto_move(deal.stage_id, to_stage):
                    move_stage(deal.id, to_stage)
                    fields[UF_LAST_KNOWN_STAGE] = to_stage
                    fields[UF_STAGE_ENTER] = today_iso
                    stats["moved"] += 1
                    comment = (
                        f"[Саприн] Автопереход этапа\n"
                        f"{deal.stage_id} → {to_stage}\n"
                        f"Причина: {trig.get('reason')}\n"
                        f"{trig.get('comment') or ''}\n\n"
                        f"{comment}"
                    )
                else:
                    logger.warning("Deal %s refuse non-allowed move %s→%s", deal.id, deal.stage_id, to_stage)
            elif trig["action"] == "stop_manual":
                stats["trigger_stop"] += 1
                comment = f"[Саприн] {trig.get('comment')}\n\n{comment}"

            push_fields(deal.id, fields)
            if changed or not COMMENT_ONLY_ON_CHANGE or trig["action"] in {"move", "stop_manual"}:
                comment_timeline(deal.id, comment)

        hashes[str(deal.id)] = digest
        stats["changed" if changed else "unchanged"] += 1

    save_local_hashes(hashes)
    logger.info("Job done: %s", stats)
    return stats


if __name__ == "__main__":
    run_daily_job()
