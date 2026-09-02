"""Разовые уведомления об ошибочном этапе в календарь Bitrix24.

Стратегия «все видят»:
1) событие в company_calendar (если секция доступна);
2) participants = все активные пользователи портала (attendees).
Повтор на ту же сделку+kind не создаём (data/stage_alerts.json).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from triggers import StageAlert, format_calendar_alert_name, stage_title

logger = logging.getLogger("saprin-calendar")

TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Moscow")
ALERTS_PATH = os.path.join(os.path.dirname(__file__), "data", "stage_alerts.json")


def _load_sent() -> dict[str, str]:
    try:
        with open(ALERTS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sent(store: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(ALERTS_PATH), exist_ok=True)
    with open(ALERTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)


def alert_key(deal_id: int, kind: str, expected: Optional[str]) -> str:
    return f"{deal_id}:{kind}:{expected or '-'}"


def portal_deal_url(webhook_url: str, deal_id: int) -> str:
    # https://portal.bitrix24.ru/rest/... → https://portal.bitrix24.ru/crm/deal/details/ID/
    base = webhook_url.split("/rest/")[0].rstrip("/")
    return f"{base}/crm/deal/details/{deal_id}/"


def list_active_user_ids(call: Callable[[str, dict], dict]) -> list[int]:
    ids: list[int] = []
    start = 0
    while True:
        data = call("user.get", {
            "filter": {"ACTIVE": True},
            "start": start,
        })
        batch = data.get("result") or []
        if not batch:
            break
        for u in batch:
            try:
                ids.append(int(u["ID"]))
            except (KeyError, TypeError, ValueError):
                continue
        next_start = data.get("next")
        if next_start is None:
            break
        start = int(next_start)
        time.sleep(0.35)
    return ids


def find_company_calendar_section(call: Callable[[str, dict], dict]) -> Optional[int]:
    """Ищем секцию календаря компании; иначе None → пишем в user-календарь webhook-user."""
    try:
        data = call("calendar.section.get", {
            "type": "company_calendar",
            "ownerId": 0,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("calendar.section.get company failed: %s", exc)
        return None
    sections = data.get("result") or []
    if not sections:
        return None
    # Берём первую доступную секцию
    try:
        return int(sections[0]["ID"])
    except (KeyError, TypeError, ValueError):
        return None


def post_stage_alert(
    *,
    call: Callable[[str, dict], dict],
    webhook_url: str,
    deal_id: int,
    case_number: str,
    alert: StageAlert,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Создаёт одноразовое событие. Возвращает статус для логов."""
    key = alert_key(deal_id, alert.kind, alert.expected_stage)
    sent = _load_sent()
    if key in sent:
        return {"status": "skip_duplicate", "key": key, "event_id": sent[key]}

    deal_url = portal_deal_url(webhook_url, deal_id)
    name = format_calendar_alert_name(
        case_number=case_number,
        current_stage=alert.current_stage,
        expected_stage=alert.expected_stage,
        deal_url=deal_url,
    )
    now = datetime.now(TZ)
    day = now.date().isoformat()
    description = (
        f"{name}\n"
        f"Тип ошибки: {alert.kind}\n"
        f"Сейчас: {stage_title(alert.current_stage)}\n"
        f"Должно: {stage_title(alert.expected_stage) if alert.expected_stage else '—'}\n"
        f"{alert.detail}\n"
        f"Сделка: {deal_url}"
    )

    payload_info = {
        "status": "would_create" if dry_run else "creating",
        "key": key,
        "name": name,
        "deal_id": deal_id,
        "kind": alert.kind,
    }
    if dry_run:
        logger.info("DRY_RUN calendar alert: %s", name)
        return payload_info

    attendees = list_active_user_ids(call)
    section = find_company_calendar_section(call)
    cal_type = "company_calendar"
    owner_id: Any = 0
    if section is None:
        # fallback: календарь пользователя вебхука
        cal_type = "user"
        me = call("user.current", {})
        owner_id = int((me.get("result") or {}).get("ID") or 1)
        sec_data = call("calendar.section.get", {"type": "user", "ownerId": owner_id})
        secs = sec_data.get("result") or []
        if not secs:
            raise RuntimeError("Нет секции календаря для события")
        section = int(secs[0]["ID"])

    fields: dict[str, Any] = {
        "type": cal_type,
        "ownerId": owner_id,
        "section": section,
        "name": name[:255],
        "description": description[:4000],
        "from": f"{day}T09:00:00",
        "to": f"{day}T09:30:00",
        "skip_time": "N",
        "timezone_from": "Europe/Moscow",
        "timezone_to": "Europe/Moscow",
        "accessibility": "free",
        "importance": "high",
        "is_meeting": "Y" if attendees else "N",
        "private_event": "N",
        "remind": [{"type": "min", "count": 0}],
        "attendees": attendees[:200],  # защита от гигантских порталов
        "meeting": {
            "notify": True,
            "reinvite": False,
            "allow_invite": False,
            "hide_guests": False,
        },
        "crm_fields": [f"D_{deal_id}"],
    }
    data = call("calendar.event.add", fields)
    event_id = str(data.get("result") or "")
    if not event_id:
        raise RuntimeError(f"calendar.event.add empty result: {data}")
    sent[key] = event_id
    _save_sent(sent)
    logger.info("Calendar alert created event_id=%s deal=%s kind=%s", event_id, deal_id, alert.kind)
    return {"status": "created", "key": key, "event_id": event_id, "name": name, "attendees": len(attendees)}


def probe_calendar(call: Callable[[str, dict], dict]) -> dict[str, Any]:
    """Проверка без создания события: секции + число активных пользователей."""
    out: dict[str, Any] = {"company_section": None, "users": 0, "ok": False, "error": None}
    try:
        out["company_section"] = find_company_calendar_section(call)
        out["users"] = len(list_active_user_ids(call))
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out
