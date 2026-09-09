"""Уведомления доверителю в MAX и Telegram по телефону из Bitrix.

Каналы: Green-API (MAX v3 + Telegram) или один HTTP-webhook.
По умолчанию шлём только при входе в «Вынесено решение» (CLIENT_NOTIFY_STAGES).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests

from triggers import STAGE_DECISION, STAGE_TITLE, stage_title

logger = logging.getLogger("saprin-notify")

NOTIFY_PATH = os.path.join(os.path.dirname(__file__), "data", "client_notify.json")
PHONE_RE = re.compile(r"(?:\+7|8|7)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}")
SUDRF_PAGE_RE = re.compile(r"https?://[a-z0-9.-]+\.sudrf\.ru/[^\s\"'<>]+", re.I)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def notify_enabled() -> bool:
    return _env("CLIENT_NOTIFY", "0") not in {"0", "false", "False", ""}


def notify_stage_ids() -> set[str]:
    raw = _env("CLIENT_NOTIFY_STAGES")
    if raw:
        return {x.strip() for x in raw.split(",") if x.strip()}
    return {STAGE_DECISION}


def channels_wanted() -> list[str]:
    raw = _env("CLIENT_NOTIFY_CHANNELS", "max,telegram")
    out = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name in {"max", "telegram", "tg"}:
            out.append("telegram" if name == "tg" else name)
    return out or ["max", "telegram"]


def normalize_phone(raw: Any) -> Optional[str]:
    """Российский номер → 7XXXXXXXXXX."""
    if raw is None:
        return None
    digits = re.sub(r"\D+", "", str(raw))
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return digits
    return None


def phones_from_text(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in PHONE_RE.finditer(text or ""):
        n = normalize_phone(m.group(0))
        if n and n not in seen:
            seen.add(n)
            found.append(n)
    return found


def phones_from_bitrix_phone_field(value: Any) -> list[str]:
    rows: list[Any]
    if value is None:
        rows = []
    elif isinstance(value, list):
        rows = value
    else:
        rows = [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in rows:
        raw = item.get("VALUE") if isinstance(item, dict) else item
        n = normalize_phone(raw)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return "***"
    return phone[:4] + "***" + phone[-2:]


def extract_case_page_url(raw_deal: dict, uf_names: list[str], parsed: Optional[dict] = None) -> str:
    if parsed:
        for key in ("case_url", "url", "card_url"):
            val = str(parsed.get(key) or "").strip()
            if "sudrf.ru" in val.lower():
                return val
    best = ""
    for uf in uf_names:
        text = str(raw_deal.get(uf) or "")
        for m in SUDRF_PAGE_RE.finditer(text):
            url = m.group(0).rstrip(").,;")
            if len(url) > len(best):
                best = url
    return best


def format_lawyer_clause(lawyer_phone: Optional[str]) -> str:
    if lawyer_phone:
        pretty = f"+{lawyer_phone}"
        return f" Также можете позвонить юристу, ведущему ваше дело: {pretty}."
    return " Также можете позвонить юристу, ведущему ваше дело."


def format_client_message(
    *,
    to_stage: str,
    case_number: str,
    case_url: str,
    lawyer_phone: Optional[str] = None,
) -> str:
    case = case_number or "—"
    link = case_url.strip() if case_url else ""
    lawyer = format_lawyer_clause(lawyer_phone)
    if to_stage == STAGE_DECISION:
        body = (
            f"Сообщаем вам, что по вашему делу {case} судом вынесено решение. "
            "Для ознакомления можете перейти по ссылке"
        )
    else:
        title = STAGE_TITLE.get(to_stage) or stage_title(to_stage)
        body = (
            f"Сообщаем вам, что по вашему делу {case} произошли изменения: «{title}». "
            "Для ознакомления можете перейти по ссылке"
        )
    if link:
        return f"{body}:\n{link}\n{lawyer.strip()}"
    return (
        f"{body} на карточку дела на сайте суда "
        f"(ссылка в сделке не указана).\n{lawyer.strip()}"
    )


@dataclass
class ChannelResult:
    channel: str
    ok: bool
    detail: str = ""


@dataclass
class NotifyResult:
    sent: bool
    skipped: str = ""
    phone: str = ""
    text: str = ""
    channels: list[ChannelResult] = field(default_factory=list)


def _load_sent() -> dict[str, str]:
    try:
        with open(NOTIFY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sent(store: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(NOTIFY_PATH), exist_ok=True)
    with open(NOTIFY_PATH, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)


def notify_key(deal_id: int, to_stage: str) -> str:
    return f"{deal_id}:{to_stage}"


def already_sent(deal_id: int, to_stage: str) -> bool:
    return notify_key(deal_id, to_stage) in _load_sent()


def mark_sent(deal_id: int, to_stage: str) -> None:
    store = _load_sent()
    store[notify_key(deal_id, to_stage)] = "sent"
    _save_sent(store)


def green_chat_id(phone: str) -> str:
    return f"{phone}@c.us"


def green_send_url(api_url: str, instance_id: str, token: str) -> str:
    base = api_url.rstrip("/")
    if "{id}" in base or "{token}" in base:
        return base.format(id=instance_id, token=token)
    parsed = urlparse(base)
    if parsed.path.rstrip("/").endswith(token):
        return base
    return f"{base}/waInstance{instance_id}/sendMessage/{token}"


def send_green_api(
    *,
    api_url: str,
    instance_id: str,
    token: str,
    phone: str,
    text: str,
    timeout: float = 30,
) -> tuple[bool, str]:
    if not api_url or not instance_id or not token:
        return False, "not_configured"
    endpoint = green_send_url(api_url, instance_id, token)
    try:
        resp = requests.post(
            endpoint,
            json={"chatId": green_chat_id(phone), "message": text},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"network:{exc}"
    if resp.status_code >= 400:
        return False, f"http_{resp.status_code}:{resp.text[:180]}"
    try:
        body = resp.json()
    except ValueError:
        return False, f"not_json:{resp.text[:120]}"
    mid = body.get("idMessage") or body.get("id") or body.get("message_id")
    if mid:
        return True, str(mid)
    if body.get("error"):
        return False, str(body.get("error"))
    return True, str(body)[:120]


def send_webhook(url: str, payload: dict[str, Any], timeout: float = 30) -> tuple[bool, str]:
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"network:{exc}"
    if resp.status_code >= 400:
        return False, f"http_{resp.status_code}:{resp.text[:180]}"
    return True, f"http_{resp.status_code}"


def _channel_creds(channel: str) -> tuple[str, str, str]:
    if channel == "max":
        return (
            _env("GREEN_API_MAX_URL") or _env("GREEN_API_URL"),
            _env("GREEN_API_MAX_ID") or _env("GREEN_API_ID_INSTANCE"),
            _env("GREEN_API_MAX_TOKEN") or _env("GREEN_API_API_TOKEN"),
        )
    return (
        _env("GREEN_API_TG_URL") or _env("GREEN_API_URL"),
        _env("GREEN_API_TG_ID") or _env("GREEN_API_ID_INSTANCE"),
        _env("GREEN_API_TG_TOKEN") or _env("GREEN_API_API_TOKEN"),
    )


def dispatch(
    *,
    phone: str,
    text: str,
    deal_id: int,
    case_number: str,
    to_stage: str,
) -> list[ChannelResult]:
    webhook = _env("CLIENT_NOTIFY_WEBHOOK_URL")
    if webhook:
        ok, detail = send_webhook(webhook, {
            "phone": phone,
            "text": text,
            "channels": channels_wanted(),
            "deal_id": deal_id,
            "case_number": case_number,
            "stage_id": to_stage,
        })
        return [ChannelResult("webhook", ok, detail)]

    results: list[ChannelResult] = []
    for channel in channels_wanted():
        api_url, inst, token = _channel_creds(channel)
        if not (api_url and inst and token):
            results.append(ChannelResult(channel, False, "not_configured"))
            continue
        ok, detail = send_green_api(
            api_url=api_url, instance_id=inst, token=token, phone=phone, text=text,
        )
        results.append(ChannelResult(channel, ok, detail))
    return results


def resolve_client_phone(
    *,
    title: str,
    contact_phones: list[str],
) -> Optional[str]:
    if contact_phones:
        return contact_phones[0]
    from_title = phones_from_text(title)
    return from_title[0] if from_title else None


def fetch_contact_phones(call: Callable[[str, dict], dict], contact_id: Optional[int]) -> list[str]:
    if not contact_id:
        return []
    data = call("crm.contact.get", {"id": int(contact_id)})
    res = data.get("result") or {}
    return phones_from_bitrix_phone_field(res.get("PHONE"))


def fetch_lawyer_phone(call: Callable[[str, dict], dict], user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    data = call("user.get", {"ID": int(user_id)})
    rows = data.get("result") or []
    user = rows[0] if rows else {}
    for key in ("PERSONAL_MOBILE", "PERSONAL_PHONE", "WORK_PHONE", "UF_PHONE_INNER"):
        n = normalize_phone(user.get(key))
        if n and len(n) == 11:
            return n
    return None


def notify_stage_move(
    *,
    call: Callable[[str, dict], dict],
    deal_id: int,
    title: str,
    case_number: Optional[str],
    to_stage: str,
    contact_id: Optional[int],
    assigned_by_id: Optional[int],
    case_url: str,
    dry_run: bool,
    comment_timeline: Optional[Callable[[int, str], None]] = None,
) -> NotifyResult:
    if not notify_enabled():
        return NotifyResult(False, skipped="disabled")
    if to_stage not in notify_stage_ids():
        return NotifyResult(False, skipped="stage_not_in_list")
    if already_sent(deal_id, to_stage):
        return NotifyResult(False, skipped="already_sent")

    contact_phones = fetch_contact_phones(call, contact_id)
    phone = resolve_client_phone(title=title, contact_phones=contact_phones)
    if not phone:
        return NotifyResult(False, skipped="no_phone")

    lawyer = fetch_lawyer_phone(call, assigned_by_id)
    text = format_client_message(
        to_stage=to_stage,
        case_number=case_number or "",
        case_url=case_url,
        lawyer_phone=lawyer,
    )
    result = NotifyResult(False, phone=phone, text=text)
    if dry_run:
        result.skipped = "dry_run"
        logger.info(
            "DRY_RUN notify deal=%s phone=%s stage=%s",
            deal_id, mask_phone(phone), to_stage,
        )
        return result

    channels = dispatch(
        phone=phone,
        text=text,
        deal_id=deal_id,
        case_number=case_number or "",
        to_stage=to_stage,
    )
    result.channels = channels
    result.sent = any(c.ok for c in channels)
    if not result.sent and channels and all(c.detail == "not_configured" for c in channels):
        result.skipped = "not_configured"
        logger.warning("notify deal=%s: каналы не настроены (GREEN_API_* или WEBHOOK)", deal_id)
        return result
    if result.sent:
        mark_sent(deal_id, to_stage)
    summary = ", ".join(f"{c.channel}={'ok' if c.ok else c.detail}" for c in channels) or "no_channels"
    logger.info(
        "notify deal=%s phone=%s sent=%s %s",
        deal_id, mask_phone(phone), result.sent, summary,
    )
    if comment_timeline:
        lines = [
            "[Саприн] Уведомление клиенту (MAX/Telegram)",
            f"Телефон: {mask_phone(phone)}",
            f"Этап: {stage_title(to_stage)}",
            f"Результат: {summary}",
        ]
        comment_timeline(deal_id, "\n".join(lines))
    return result
