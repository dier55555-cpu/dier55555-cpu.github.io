"""Создаёт служебные UF сделки для Саприн-мониторинга (идемпотентно)."""

from __future__ import annotations

import os
import sys
import time

import requests

WEBHOOK = os.environ.get("BITRIX_WEBHOOK_URL", "").rstrip("/")

FIELDS = [
    ("UF_CRM_SAPRIN_LAST_STATUS", "string", "Саприн: последний результат события"),
    ("UF_CRM_SAPRIN_LAST_CHECK", "string", "Саприн: дата/время последней проверки"),
    ("UF_CRM_SAPRIN_SNAP_HASH", "string", "Саприн: хэш снимка движения дела"),
    ("UF_CRM_SAPRIN_KNOWN_STAGE", "string", "Саприн: последний известный системе этап"),
    ("UF_CRM_SAPRIN_COURT_SITE", "url", "Саприн: сайт суда (нормализованный)"),
    ("UF_CRM_SAPRIN_DECISION_DATE", "string", "Саприн: дата изготовления решения"),
    ("UF_CRM_SAPRIN_DECISION_PUB", "string", "Саприн: дата размещения решения на сайте"),
    ("UF_CRM_SAPRIN_DEADLINE_40D", "string", "Саприн: дедлайн 40 дней"),
    ("UF_CRM_SAPRIN_STAGE_ENTER", "string", "Саприн: дата входа в текущий этап"),
    ("UF_CRM_SAPRIN_APPEAL_RESULT", "string", "Саприн: результат обжалования"),
]


def existing_fields() -> set[str]:
    r = requests.post(f"{WEBHOOK}/crm.deal.userfield.list.json", timeout=60)
    r.raise_for_status()
    return {f["FIELD_NAME"] for f in (r.json().get("result") or [])}


def main() -> int:
    if not WEBHOOK or "YOUR_PORTAL" in WEBHOOK:
        print("BITRIX_WEBHOOK_URL required", file=sys.stderr)
        return 2
    have = existing_fields()
    for field_name, user_type, label in FIELDS:
        # Bitrix auto-prefixes UF_CRM_ for deal fields if we pass FIELD_NAME without? Use exact.
        # crm.deal.userfield.add uses FIELD_NAME without UF_CRM_ prefix sometimes — try full name.
        short = field_name.replace("UF_CRM_", "", 1) if field_name.startswith("UF_CRM_") else field_name
        if field_name in have:
            print(f"exists {field_name}")
            continue
        payload = {
            "fields": {
                "FIELD_NAME": short,
                "USER_TYPE_ID": user_type,
                "EDIT_FORM_LABEL": {"ru": label},
                "LIST_COLUMN_LABEL": {"ru": label},
                "LIST_FILTER_LABEL": {"ru": label},
                "XML_ID": field_name,
                "MANDATORY": "N",
                "SHOW_IN_LIST": "Y",
                "EDIT_IN_LIST": "Y",
                "IS_SEARCHABLE": "N",
            }
        }
        r = requests.post(f"{WEBHOOK}/crm.deal.userfield.add.json", json=payload, timeout=60)
        data = r.json()
        if "error" in data:
            print(f"FAIL {field_name}: {data}")
        else:
            print(f"created id={data.get('result')} -> expect {field_name}")
        time.sleep(0.6)
    have2 = existing_fields()
    for field_name, _, _ in FIELDS:
        print("check", field_name, "OK" if field_name in have2 else "MISSING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
