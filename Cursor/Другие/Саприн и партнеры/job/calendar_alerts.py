"""Разовые уведомления об ошибочном этапе.

Предпочтительно: calendar.event.add (company_calendar + все сотрудники).
Если у webhook только scope crm (как сейчас на Саприн) — fallback:
crm.activity.add (дело) + комментарий в таймлайн. Чтобы слать именно
в «Календарь» всем, нужно расширить права webhook: calendar + user.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
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
    base = webhook_url.split("/rest/")[0].rstrip("/")
    return f"{base}/crm/deal/details/{deal_id}/"


def webhook_scopes(call: Callable[[str, dict], dict]) -> set[str]:
    try:
        data = call("scope", {})
        result = data.get("result") or []
        if isinstance(result, list):
            return {str(x) for x in result}
    except Exception as exc:  # noqa: BLE001
        logger.warning("scope failed: %s", exc)
    return set()


def list_active_user_ids(call: Callable[[str, dict], dict]) -> list[int]:
    ids: list[int] = []
    start = 0
    while True:
        data = call("user.get", {"filter": {"ACTIVE": True}, "start": start})
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
    try:
        data = call("calendar.section.get", {"type": "company_calendar", "ownerId": 0})
    except Exception as exc:  # noqa: BLE001
        logger.warning("calendar.section.get company failed: %s", exc)
        return None
    sections = data.get("result") or []
    if not sections:
        return None
    try:
        return int(sections[0]["ID"])
    except (KeyError, TypeError, ValueError):
        return None


def _post_crm_activity_fallback(
    *,
    call: Callable[[str, dict], dict],
    deal_id: int,
    name: str,
    description: str,
) -> str:
    """Дело CRM: дело + комментарий — видно тем, у кого есть доступ к сделке."""
    deal = (call("crm.deal.get", {"id": deal_id}).get("result") or {})
    responsible = int(deal.get("ASSIGNED_BY_ID") or 1)
    now = datetime.now(TZ)
    deadline = now.strftime("%Y-%m-%dT18:00:00%z")
    # Bitrix often wants +03:00 style
    if len(deadline) >= 5 and deadline[-5] in "+-" and ":" not in deadline[-5:]:
        deadline = deadline[:-2] + ":" + deadline[-2:]
    act = call("crm.activity.add", {
        "fields": {
            "OWNER_TYPE_ID": 2,  # deal
            "OWNER_ID": deal_id,
            "TYPE_ID": 2,  # task/todo-like
            "SUBJECT": name[:250],
            "DESCRIPTION": description[:4000],
            "DESCRIPTION_TYPE": 1,
            "COMPLETED": "N",
            "RESPONSIBLE_ID": responsible,
            "PRIORITY": 2,
            "START_TIME": now.strftime("%Y-%m-%dT09:00:00"),
            "END_TIME": now.strftime("%Y-%m-%dT09:30:00"),
            "DEADLINE": now.strftime("%Y-%m-%dT18:00:00"),
            "NOTIFY_TYPE": 1,
            "NOTIFY_VALUE": 0,
        }
    })
    act_id = str(act.get("result") or "")
    try:
        call("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": deal_id,
                "ENTITY_TYPE": "deal",
                "COMMENT": f"[Саприн][алерт этапа]\n{name}\n{description[:1500]}",
            }
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("timeline comment for alert failed: %s", exc)
    if not act_id:
        raise RuntimeError(f"crm.activity.add empty: {act}")
    return f"activity:{act_id}"


def post_stage_alert(
    *,
    call: Callable[[str, dict], dict],
    webhook_url: str,
    deal_id: int,
    case_number: str,
    alert: StageAlert,
    dry_run: bool = True,
) -> dict[str, Any]:
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

    payload_info: dict[str, Any] = {
        "status": "would_create" if dry_run else "creating",
        "key": key,
        "name": name,
        "deal_id": deal_id,
        "kind": alert.kind,
    }
    if dry_run:
        scopes = webhook_scopes(call)
        payload_info["scopes"] = sorted(scopes)
        payload_info["channel"] = (
            "calendar" if ("calendar" in scopes and "user" in scopes) else "crm_activity_fallback"
        )
        logger.info("DRY_RUN stage alert via %s: %s", payload_info["channel"], name)
        return payload_info

    scopes = webhook_scopes(call)
    use_calendar = "calendar" in scopes and "user" in scopes

    if use_calendar:
        attendees = list_active_user_ids(call)
        section = find_company_calendar_section(call)
        cal_type = "company_calendar"
        owner_id: Any = 0
        if section is None:
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
            "attendees": attendees[:200],
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
        channel = "calendar"
    else:
        logger.warning(
            "Webhook scopes=%s — календарь недоступен, пишем crm.activity (нужны права calendar+user)",
            sorted(scopes),
        )
        event_id = _post_crm_activity_fallback(
            call=call, deal_id=deal_id, name=name, description=description,
        )
        channel = "crm_activity_fallback"

    sent[key] = event_id
    _save_sent(sent)
    logger.info("Stage alert %s id=%s deal=%s kind=%s", channel, event_id, deal_id, alert.kind)
    return {
        "status": "created",
        "channel": channel,
        "key": key,
        "event_id": event_id,
        "name": name,
    }


def probe_calendar(call: Callable[[str, dict], dict]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "scopes": [],
        "company_section": None,
        "users": 0,
        "ok": False,
        "channel": None,
        "error": None,
    }
    try:
        scopes = sorted(webhook_scopes(call))
        out["scopes"] = scopes
        if "calendar" in scopes and "user" in scopes:
            out["company_section"] = find_company_calendar_section(call)
            out["users"] = len(list_active_user_ids(call))
            out["channel"] = "calendar"
            out["ok"] = True
        elif "crm" in scopes:
            out["channel"] = "crm_activity_fallback"
            out["ok"] = True
            out["error"] = (
                "Webhook только crm: события пойдут как дело CRM + комментарий. "
                "Для календаря всем сотрудникам добавьте права calendar и user."
            )
        else:
            out["error"] = f"Недостаточно прав webhook: {scopes}"
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out
