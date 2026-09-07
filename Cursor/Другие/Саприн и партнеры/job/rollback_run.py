#!/usr/bin/env python3
"""Откат переносов из отчёта weekly/daily.

По умолчанию только показывает (--dry-run). Бой: --apply.

Вернёт сделку только если STAGE_ID в CRM всё ещё равен to_stage из jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# load VPS / local .env
_ENV = Path("/opt/saprin/job/.env")
if not _ENV.is_file():
    _ENV = Path(__file__).resolve().parent / ".env"
if _ENV.is_file():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import bitrix
from run_report import DEFAULT_ROOT, runs_dir
from triggers import stage_title


def _load_moves(kind: str, stamp: str, root: Path) -> list[dict]:
    path = runs_dir(kind, root) / f"{stamp}-moves.jsonl"
    if not path.is_file():
        raise SystemExit(f"нет файла {path}")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _latest_stamp(kind: str, root: Path) -> str:
    folder = runs_dir(kind, root)
    mds = sorted(folder.glob("*.md"))
    if not mds:
        raise SystemExit(f"нет отчётов в {folder}")
    return mds[-1].stem


def _deal_stage(deal_id: int) -> str:
    data = bitrix._call("crm.deal.get", {"id": deal_id})
    result = data.get("result") or {}
    return str(result.get("STAGE_ID") or "")


def main() -> int:
    p = argparse.ArgumentParser(description="Откат автопереносов Саприн по отчёту")
    p.add_argument("--job", choices=("weekly", "daily", "manual"), required=True)
    p.add_argument("--stamp", help="например 20260907-0700; по умолчанию последний отчёт")
    p.add_argument("--deal", type=int, action="append", help="только эти deal_id (можно несколько)")
    p.add_argument("--apply", action="store_true", help="реально вернуть этапы в CRM")
    p.add_argument("--root", default=str(DEFAULT_ROOT))
    args = p.parse_args()
    dry = not args.apply
    root = Path(args.root)
    stamp = args.stamp or _latest_stamp(args.job, root)
    rows = _load_moves(args.job, stamp, root)
    rows = [r for r in rows if r.get("applied")]
    if args.deal:
        want = set(args.deal)
        rows = [r for r in rows if int(r["deal_id"]) in want]
    if not rows:
        print("нечего откатывать (нет applied-переносов в этом отчёте)")
        return 0

    print(f"отчёт {args.job} {stamp}  записей={len(rows)}  режим={'DRY' if dry else 'APPLY'}")
    ok = skip = fail = 0
    for r in rows:
        did = int(r["deal_id"])
        frm, to = r["from_stage"], r["to_stage"]
        try:
            current = _deal_stage(did)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL #{did} get: {exc}")
            fail += 1
            continue
        if current != to:
            print(
                f"  SKIP #{did} {r.get('case_number')} сейчас={stage_title(current)} "
                f"ожидали={stage_title(to)} — похоже уже двигали вручную"
            )
            skip += 1
            continue
        print(f"  {'WOULD' if dry else 'ROLL'} #{did} {r.get('case_number')} {stage_title(to)} → {stage_title(frm)}")
        if dry:
            ok += 1
            continue
        try:
            bitrix.move_stage(did, frm)
            fields = {
                bitrix.UF_LAST_KNOWN_STAGE: r.get("prev_known_stage") or frm,
            }
            if r.get("prev_stage_enter"):
                fields[bitrix.UF_STAGE_ENTER] = r["prev_stage_enter"]
            bitrix.push_fields(did, fields)
            bitrix.comment_timeline(
                did,
                f"[Саприн] Откат автопрогона {args.job} {stamp}\n"
                f"{stage_title(to)} → {stage_title(frm)}\n"
                f"Причина исходного хода: {r.get('reason') or '—'}",
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL #{did} update: {exc}")
            fail += 1
    print(f"итог ok={ok} skip={skip} fail={fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
