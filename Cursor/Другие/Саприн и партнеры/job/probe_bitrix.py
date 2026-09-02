#!/usr/bin/env python3
"""Проверка портала: STAGE_DDU + календарь компании (без записи этапов)."""

from __future__ import annotations

import json
import os
import sys

# load .env if present
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
from calendar_alerts import probe_calendar


def main() -> int:
    if not bitrix.BITRIX_WEBHOOK_URL or "YOUR_PORTAL" in bitrix.BITRIX_WEBHOOK_URL:
        print("BITRIX_WEBHOOK_URL missing", file=sys.stderr)
        return 2
    ddu = bitrix.resolve_stage_ddu()
    print("STAGE_DDU:", ddu)
    # list all stages for verification
    data = bitrix._call("crm.dealcategory.stage.list", {"id": bitrix.CATEGORY_ID})
    print("Stages in category", bitrix.CATEGORY_ID)
    for st in data.get("result") or []:
        print(f"  {st.get('STATUS_ID')}: {st.get('NAME')}")
    cal = probe_calendar(bitrix._call)
    print("Calendar probe:", json.dumps(cal, ensure_ascii=False))
    return 0 if ddu and cal.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
