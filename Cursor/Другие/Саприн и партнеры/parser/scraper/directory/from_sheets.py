"""Пересборка courts-ru.json из CSV выгрузок Google Sheets.

Источник:
  - суды РФ:    https://docs.google.com/spreadsheets/d/19sxmrNDDHu0u-g4y3987g5hMMSdFh5VkKKmRRH-v2VU
  - мировые:    https://docs.google.com/spreadsheets/d/109ThgsNtz_pyaLu0RZonEqh0oN1ntS5OCbJAfH_M6HQ

Колонки CSV: РЕГИОН, ГОРОД, РАЙОН, НАЗВАНИЕ, ТИП, ТИП_НАЗВАНИЕ, АДРЕС, САЙТ,
ДОМЕН_SUDRF, ПАРСЕР, КОД

Пример:
  python -m scraper.directory.from_sheets
  python -m scraper.directory.from_sheets --download
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEETS_DIR = ROOT / "directory" / "sheets"
DEFAULT_JSON = ROOT / "directory" / "courts-ru.json"

SUDY_SHEET_ID = "19sxmrNDDHu0u-g4y3987g5hMMSdFh5VkKKmRRH-v2VU"
MIROVYE_SHEET_ID = "109ThgsNtz_pyaLu0RZonEqh0oN1ntS5OCbJAfH_M6HQ"

SUDY_URL = f"https://docs.google.com/spreadsheets/d/{SUDY_SHEET_ID}/export?format=csv"
MIROVYE_URL = f"https://docs.google.com/spreadsheets/d/{MIROVYE_SHEET_ID}/export?format=csv"

TYPE_MAP = {
    "районный_городской": "RS",
    "областной": "OS",
    "мировой": "MS",
    "апелляция": "AJ",
    "кассация": "KJ",
    "верховный": "VS",
    "арбитраж": "AS",
}


def _export_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"


def download_csv(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    dest.write_bytes(data)


def _cell(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name] is not None:
            return str(row[name]).strip()
    return ""


def _region_code(code: str, region: str) -> str:
    if code and len(code) >= 2 and code[:2].isdigit():
        return code[:2]
    m = re.match(r"^(\d{2})", code or "")
    return m.group(1) if m else ""


def _court_type(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in TYPE_MAP:
        return TYPE_MAP[key]
    if "миров" in key:
        return "MS"
    if "област" in key or "краев" in key or "верховн" in key and "субъект" in key:
        return "OS"
    if "район" in key or "город" in key or "межрайон" in key:
        return "RS"
    return key.upper()[:8] or "RS"


def row_to_record(row: dict[str, str]) -> dict:
    code = _cell(row, "КОД", "code")
    name = _cell(row, "НАЗВАНИЕ", "name")
    region = _cell(row, "РЕГИОН", "region")
    city = _cell(row, "ГОРОД", "city")
    district = _cell(row, "РАЙОН", "district")
    address = _cell(row, "АДРЕС", "address")
    website = _cell(row, "САЙТ", "website")
    domain = _cell(row, "ДОМЕН_SUDRF", "sudrf_domain")
    type_raw = _cell(row, "ТИП", "court_type")
    type_name = _cell(row, "ТИП_НАЗВАНИЕ", "court_type_name")
    parser = _cell(row, "ПАРСЕР", "parser_supported").lower()
    parser_supported = parser in {"да", "yes", "true", "1", "y"}

    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website
    if website and not website.endswith("/"):
        website = website + "/"
    if not domain and website:
        domain = re.sub(r"^https?://", "", website).rstrip("/")

    return {
        "code": code,
        "name": name,
        "court_type": _court_type(type_raw),
        "court_type_name": type_name or type_raw,
        "region_code": _region_code(code, region),
        "region": region,
        "city": city,
        "district": district,
        "address": address,
        "website": website,
        "sudrf_domain": domain,
        "parser_supported": parser_supported,
        "inn": "",
    }


def load_csv(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    records = []
    for row in reader:
        rec = row_to_record(row)
        if not rec["name"] and not rec["code"]:
            continue
        records.append(rec)
    return records


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Сборка courts-ru.json из Google Sheets CSV")
    p.add_argument("--sudy", type=Path, default=SHEETS_DIR / "sudy-ru.csv")
    p.add_argument("--mirovye", type=Path, default=SHEETS_DIR / "mirovye-ru.csv")
    p.add_argument("--json", type=Path, default=DEFAULT_JSON)
    p.add_argument(
        "--download",
        action="store_true",
        help="Скачать свежие CSV из Google Sheets перед сборкой",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.download:
        print(f"Скачиваю суды → {args.sudy}", file=sys.stderr)
        download_csv(SUDY_URL, args.sudy)
        print(f"Скачиваю мировые → {args.mirovye}", file=sys.stderr)
        download_csv(MIROVYE_URL, args.mirovye)

    if not args.sudy.exists() or not args.mirovye.exists():
        print("Нет CSV. Укажите пути или запустите с --download", file=sys.stderr)
        return 2

    courts = load_csv(args.sudy) + load_csv(args.mirovye)
    # стабильный порядок: код, затем имя
    courts.sort(key=lambda c: (c.get("code") or "", c.get("name") or ""))

    payload = {
        "source": {
            "sudy_sheet": f"https://docs.google.com/spreadsheets/d/{SUDY_SHEET_ID}",
            "mirovye_sheet": f"https://docs.google.com/spreadsheets/d/{MIROVYE_SHEET_ID}",
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "count": len(courts),
        "courts": courts,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Готово: {len(courts)} записей → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
