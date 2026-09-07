"""Отчёты прогона weekly/daily: markdown + jsonl, ротация 7 комплектов.

Каталог: {SAPRIN_REPORT_DIR}/runs/{weekly|daily}/
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from triggers import stage_title

TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Moscow")
KEEP_RUNS = 7
DEFAULT_ROOT = Path(os.environ.get("SAPRIN_REPORT_DIR") or "/opt/saprin/logs")


def detect_job_kind() -> str:
    raw = (os.environ.get("SAPRIN_JOB_KIND") or "").strip().lower()
    if raw in {"weekly", "daily"}:
        return raw
    return "manual"


def runs_dir(kind: str, root: Optional[Path] = None) -> Path:
    base = Path(root) if root is not None else DEFAULT_ROOT
    return base / "runs" / kind


def portal_deal_url(webhook_url: str, deal_id: int) -> str:
    base = (webhook_url or "").split("/rest/")[0].rstrip("/")
    if not base:
        return f"deal/{deal_id}"
    return f"{base}/crm/deal/details/{deal_id}/"


def rotate_runs(kind: str, keep: int = KEEP_RUNS, root: Optional[Path] = None) -> None:
    folder = runs_dir(kind, root)
    if not folder.is_dir():
        return
    stamps = sorted({p.stem for p in folder.glob("*.md")})
    extra = stamps[:-keep] if keep >= 0 else list(stamps)
    for stamp in extra:
        for suffix in (".md", "-moves.jsonl", "-errors.jsonl", "-stats.json"):
            path = folder / f"{stamp}{suffix}"
            if path.is_file():
                path.unlink()


class RunRecorder:
    def __init__(self, kind: str) -> None:
        self.kind = kind if kind in {"weekly", "daily", "manual"} else "manual"
        self.started = datetime.now(TZ)
        self.moves: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []

    def add_move(
        self,
        *,
        deal_id: int,
        case_number: Optional[str],
        from_stage: str,
        to_stage: str,
        reason: str,
        applied: bool,
        prev_known: Optional[str],
        prev_enter: Optional[str],
        comment: str = "",
    ) -> None:
        self.moves.append({
            "deal_id": deal_id,
            "case_number": case_number or "",
            "from_stage": from_stage,
            "to_stage": to_stage,
            "from_title": stage_title(from_stage),
            "to_title": stage_title(to_stage),
            "reason": reason or "",
            "applied": bool(applied),
            "prev_known_stage": prev_known or from_stage,
            "prev_stage_enter": prev_enter or "",
            "comment": (comment or "")[:400],
            "at": datetime.now(TZ).isoformat(timespec="seconds"),
        })

    def add_error(
        self,
        *,
        deal_id: int,
        case_number: Optional[str],
        stage_id: str,
        status: str,
        message: str,
        court_website: str = "",
    ) -> None:
        self.errors.append({
            "deal_id": deal_id,
            "case_number": case_number or "",
            "stage_id": stage_id,
            "stage_title": stage_title(stage_id),
            "status": status,
            "message": (message or "")[:800],
            "court_website": court_website or "",
            "at": datetime.now(TZ).isoformat(timespec="seconds"),
        })

    def add_alert(self, deal_id: int, case_number: Optional[str], kind: str, detail: str) -> None:
        self.alerts.append({
            "deal_id": deal_id,
            "case_number": case_number or "",
            "kind": kind,
            "detail": (detail or "")[:400],
        })


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def render_markdown(
    *,
    kind: str,
    started: datetime,
    finished: datetime,
    stats: dict[str, Any],
    moves: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    webhook_url: str = "",
    dry_run: bool = False,
) -> str:
    applied = [m for m in moves if m.get("applied")]
    planned = [m for m in moves if not m.get("applied")]
    lines = [
        f"# Саприн — отчёт {kind}",
        "",
        f"Прогон: **{started.strftime('%d.%m.%Y %H:%M')}** → **{finished.strftime('%H:%M')}** (МСК).",
        f"Режим: **{'DRY_RUN (в CRM не писали этапы)' if dry_run else 'бой (этапы записаны)'}**.",
        "",
        "## Сводка",
        "",
        "| Показатель | Кол-во |",
        "|---|---|",
        f"| Сделок в выборке | {stats.get('total', 0)} |",
        f"| Переносов этапа | **{stats.get('moved', len(applied))}** |",
        f"| Ошибки парсера / ГАС | **{stats.get('errors', len(errors))}** |",
        f"| Пропуск | {stats.get('skipped', 0)} |",
        f"| Алерты | {stats.get('alerts', len(alerts))} |",
        f"| Стоп юристу | {stats.get('trigger_stop', 0)} |",
        "",
        "Откат: только строки из `*-moves.jsonl` с `applied=true`, если этап в CRM всё ещё «стало».",
        "",
    ]
    by_pair = Counter((m.get("from_title"), m.get("to_title")) for m in (applied or planned))
    if by_pair:
        lines += ["### Переходы", "", "| Было | Стало | Кол-во |", "|---|---|---|"]
        for (a, b), n in by_pair.most_common():
            lines.append(f"| {a} | {b} | {n} |")
        lines.append("")
    show = applied if applied else planned
    if show:
        title = "## Переносы (для отката)" if applied else "## Переносы (не применялись, DRY_RUN)"
        lines += [title, "", "| Сделка | Дело | Было | Стало | Причина |", "|---|---|---|---|---|"]
        for m in show:
            url = portal_deal_url(webhook_url, int(m["deal_id"]))
            lines.append(
                f"| [{m['deal_id']}]({url}) | {m.get('case_number') or '—'} | "
                f"{m.get('from_title')} | {m.get('to_title')} | {m.get('reason') or '—'} |"
            )
        lines.append("")
    if errors:
        lines += ["## Ошибки (повтор на следующем таймере)", "", "| Сделка | Дело | Статус | Сообщение |", "|---|---|---|---|"]
        for e in errors:
            msg = (e.get("message") or "").replace("|", "/").replace("\n", " ")[:160]
            lines.append(
                f"| {e['deal_id']} | {e.get('case_number') or '—'} | {e.get('status')} | {msg} |"
            )
        lines.append("")
    if alerts:
        lines += ["## Алерты календаря", "", "| Сделка | Дело | Тип |", "|---|---|---|"]
        for a in alerts:
            lines.append(f"| {a['deal_id']} | {a.get('case_number') or '—'} | {a.get('kind')} |")
        lines.append("")
    lines.append("Ошибки парсера **не откатываются** — CRM этап не меняли.")
    return "\n".join(lines) + "\n"


def write_run_bundle(
    recorder: RunRecorder,
    stats: dict[str, Any],
    *,
    webhook_url: str = "",
    dry_run: bool = False,
    root: Optional[Path] = None,
    keep: int = KEEP_RUNS,
) -> dict[str, str]:
    finished = datetime.now(TZ)
    folder = runs_dir(recorder.kind, root)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = recorder.started.strftime("%Y%m%d-%H%M")
    md_path = folder / f"{stamp}.md"
    moves_path = folder / f"{stamp}-moves.jsonl"
    errors_path = folder / f"{stamp}-errors.jsonl"
    stats_path = folder / f"{stamp}-stats.json"
    meta = {
        "kind": recorder.kind,
        "stamp": stamp,
        "started": recorder.started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "stats": stats,
        "moves": len(recorder.moves),
        "applied_moves": sum(1 for m in recorder.moves if m.get("applied")),
        "errors": len(recorder.errors),
    }
    stats_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_jsonl(moves_path, recorder.moves)
    _write_jsonl(errors_path, recorder.errors)
    md_path.write_text(
        render_markdown(
            kind=recorder.kind,
            started=recorder.started,
            finished=finished,
            stats=stats,
            moves=recorder.moves,
            errors=recorder.errors,
            alerts=recorder.alerts,
            webhook_url=webhook_url,
            dry_run=dry_run,
        ),
        encoding="utf-8",
    )
    rotate_runs(recorder.kind, keep=keep, root=root)
    return {
        "stamp": stamp,
        "md": str(md_path),
        "moves": str(moves_path),
        "errors": str(errors_path),
    }
