#!/usr/bin/env python3
"""Проверка телефонов и шаблона уведомления (по умолчанию без отправки).

  /opt/saprin/venv/bin/python /opt/saprin/job/probe_notify.py
  /opt/saprin/venv/bin/python /opt/saprin/job/probe_notify.py --send --deal 1276
"""

from __future__ import annotations

import argparse
import os
import sys

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(env_path):
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import bitrix
from client_notify import (
    channels_wanted,
    extract_case_page_url,
    fetch_contact_phones,
    fetch_lawyer_phone,
    format_client_message,
    mask_phone,
    notify_enabled,
    notify_stage_ids,
    notify_stage_move,
    resolve_client_phone,
)
from triggers import STAGE_DECISION


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deal", type=int, default=0)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    print("CLIENT_NOTIFY", notify_enabled())
    print("stages", sorted(notify_stage_ids()))
    print("channels", channels_wanted())

    deals = bitrix.pull_deals()
    deal = None
    if args.deal:
        deal = next((d for d in deals if d.id == args.deal), None)
    if deal is None:
        deal = next((d for d in deals if d.stage_id == STAGE_DECISION and d.contact_id), None)
    if deal is None and deals:
        deal = deals[0]
    if deal is None:
        print("no deals")
        return 2

    phones = fetch_contact_phones(bitrix._call, deal.contact_id)
    phone = resolve_client_phone(title=deal.title, contact_phones=phones)
    lawyer = fetch_lawyer_phone(bitrix._call, deal.assigned_by_id)
    url = extract_case_page_url(deal.raw, bitrix.UF_COURT_URLS) or (deal.court_website or "")
    text = format_client_message(
        to_stage=STAGE_DECISION,
        case_number=deal.case_number or "",
        case_url=url,
        lawyer_phone=lawyer,
    )
    print("deal", deal.id, deal.case_number, deal.stage_id)
    print("phone", mask_phone(phone) if phone else "NONE")
    print("lawyer", mask_phone(lawyer) if lawyer else "NONE")
    print("url", url or "NONE")
    print("--- text ---")
    print(text)
    if not args.send:
        print("ok (без отправки; добавьте --send после GREEN_API_* )")
        return 0
    os.environ["CLIENT_NOTIFY"] = "1"
    res = notify_stage_move(
        call=bitrix._call,
        deal_id=deal.id,
        title=deal.title,
        case_number=deal.case_number,
        to_stage=STAGE_DECISION,
        contact_id=deal.contact_id,
        assigned_by_id=deal.assigned_by_id,
        case_url=url,
        dry_run=False,
        comment_timeline=bitrix.comment_timeline,
    )
    print("sent", res.sent, "skipped", res.skipped, "channels", res.channels)
    return 0 if res.sent or res.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
