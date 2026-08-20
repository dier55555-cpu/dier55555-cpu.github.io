"""Выгрузка всех судов России из DaData в JSON + Excel.

    export DADATA_API_KEY=...
    python -m scraper.directory.dump
    python -m scraper.directory.dump --types RS,OS,AJ,KJ,VS,MS
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .dadata import ALL_GENERAL_TYPES, DEFAULT_TYPES, DaDataCourtClient, dump_courts
from .export import sorted_records, write_json, write_xlsx
from .normalize import enrich_court, fill_missing_regions

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = ROOT / "directory" / "courts-ru.json"
DEFAULT_XLSX = ROOT / "data" / "courts-ru.xlsx"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Дамп судов России из DaData suggest/court")
    parser.add_argument("--api-key", default=os.environ.get("DADATA_API_KEY", ""), help="API-ключ DaData")
    parser.add_argument(
        "--types",
        default=",".join(DEFAULT_TYPES),
        help=f"Типы через запятую. По умолчанию {','.join(DEFAULT_TYPES)}. "
             f"Мировые: добавьте MS. Все общие: {','.join(ALL_GENERAL_TYPES)}",
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--pause", type=float, default=0.05, help="Пауза между запросами к DaData, сек")
    parser.add_argument("--from-raw", type=Path, help="Пересобрать JSON/Excel из сырого дампа без DaData")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    types = tuple(part.strip().upper() for part in args.types.split(",") if part.strip())

    def progress(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    dadata_calls = 0
    if args.from_raw:
        raw = json.loads(args.from_raw.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "courts" in raw:
            raw = raw["courts"]
        progress(f"Читаю сырой дамп: {len(raw)} записей из {args.from_raw}")
    else:
        if not args.api_key:
            print("Задайте DADATA_API_KEY или --api-key", file=sys.stderr)
            return 2
        client = DaDataCourtClient(args.api_key)
        raw = dump_courts(client, types, pause=args.pause, progress=progress)
        dadata_calls = client.calls
        raw_path = args.json.with_name("courts-ru.raw.json")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        progress(f"Сырой дамп: {len(raw)} записей → {raw_path}")

    records = sorted_records(fill_missing_regions([enrich_court(row) for row in raw]))
    extra = {
        "dadata_calls": dadata_calls,
        "types": sorted({record.court_type for record in records if record.court_type}),
    }
    write_json(args.json, records, extra=extra)
    write_xlsx(args.xlsx, records)
    print(
        f"Готово: {len(records)} судов, {dadata_calls} запросов DaData\n"
        f"JSON: {args.json}\n"
        f"Excel: {args.xlsx}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
