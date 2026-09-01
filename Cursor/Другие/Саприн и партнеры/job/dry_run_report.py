#!/usr/bin/env python3
"""DRY_RUN прогон всех сделок + JSONL/Markdown для разбора с юристом.

Ничего не пишет в Bitrix. Использует те же pull/lookup/triggers, что и bitrix.py.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from court_pool import CourtParsePool, court_host
from sudrf_labels import VORONEZH_CITY_RAYON_HOSTS
from bitrix import Deal, lookup_delo, pull_deals, run_triggers
import bitrix
from triggers import (
    AUTOMATED_STAGES,
    MANUAL_ONLY_STAGES,
    is_forward,
)

STAGE_TITLE = {
    "C2:UC_VQSC1C": "Назначена дата заседания",
    "C2:UC_X3GNNS": "Упрощенное производство",
    "C2:FINAL_INVOICE": "Назначена судебная экспертиза",
    "C2:UC_YADE6K": "Назначена дата экспертизы (ручной)",
    "C2:UC_SM5W4O": "Дело вернулось с экспертизы",
    "C2:UC_IPH4VF": "Без судебной экспертизы, основное",
    "C2:UC_S1LPCC": "Согласовано мировое (ручной)",
    "C2:UC_GZ6RL3": "Вынесено решение",
    "C2:UC_YJ087T": "Дело в апелляции",
    "C2:UC_2M4FYU": "Решение вступило в законную силу",
    "C2:UC_B2ZGR1": "Запросить исполнительный лист",
    "C2:UC_ILS0X3": "Исполнительный лист получен",
}

TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Moscow")


def _title(stage_id: str) -> str:
    return STAGE_TITLE.get(stage_id or "", stage_id or "—")


def process_deal(deal: Deal) -> dict:
    row: dict = {
        "deal_id": deal.id,
        "title": (deal.title or "")[:120],
        "case_number": deal.case_number,
        "stage_id": deal.stage_id,
        "stage": _title(deal.stage_id),
        "court_website": deal.court_website,
        "parse_status": None,
        "action": None,
        "to_stage_id": None,
        "to_stage": None,
        "reason": None,
        "comment": None,
        "movement_rows": 0,
        "tabs_appeal": None,
        "tabs_il": None,
        "would_move": False,
        "risk": None,
        "error": None,
    }
    if deal.stage_id in MANUAL_ONLY_STAGES:
        row.update(action="skip_manual_stage", reason="этап только ручной", risk="info")
        return row
    if deal.stage_id not in AUTOMATED_STAGES:
        row.update(action="skip_not_automated", reason=f"этап {deal.stage_id} вне автоматики", risk="info")
        return row

    parsed = lookup_delo(deal)
    status = parsed.get("status")
    row["parse_status"] = status
    if status != "found":
        row["action"] = "no_parse"
        row["reason"] = f"{status}: {str(parsed.get('result') or '')[:240]}"
        row["risk"] = "error" if status not in {"skipped", "not_found"} else "warn"
        if status == "skipped" and "миров" in str(parsed.get("result") or "").lower():
            row["risk"] = "info"
        return row

    trig = run_triggers(deal, parsed)
    to_stage = trig.get("to_stage")
    action = trig.get("action")
    row.update(
        action=action,
        to_stage_id=to_stage,
        to_stage=_title(to_stage) if to_stage else None,
        reason=trig.get("reason"),
        comment=(trig.get("comment") or "")[:500],
        movement_rows=trig.get("movement_rows") or 0,
    )
    if action == "move" and to_stage:
        row["would_move"] = is_forward(deal.stage_id, to_stage)
        if not row["would_move"]:
            row["risk"] = "block_backward"
        elif deal.stage_id == "C2:UC_VQSC1C" and to_stage == "C2:UC_GZ6RL3":
            row["risk"] = "review_jump"  # скачок заседание → решение (допустимо по приоритету)
        else:
            row["risk"] = "would_move"
    elif action == "stop_manual":
        row["risk"] = "v8_or_manual"
    elif action == "none":
        row["risk"] = "wait"
    return row


def write_markdown(rows: list[dict], stats: dict, path: Path) -> None:
    moves = [r for r in rows if r.get("would_move")]
    stops = [r for r in rows if r.get("action") == "stop_manual"]
    errors = [r for r in rows if r.get("risk") == "error"]
    not_found = [r for r in rows if str(r.get("parse_status")) == "not_found"]
    skipped = [r for r in rows if r.get("action") in {"skip_manual_stage", "skip_not_automated", "no_parse"} and r.get("risk") != "error"]
    waits = [r for r in rows if r.get("action") == "none"]

    lines = [
        "# DRY_RUN — разбор для юриста",
        "",
        f"Прогон: {stats['started']} → {stats['finished']} (МСК). **В Bitrix ничего не писалось.**",
        f"Сделок в выборке: **{len(rows)}**. Пауза между запросами: {os.environ.get('PAUSE_BETWEEN_DEALS_SEC') or bitrix.PAUSE_BETWEEN_DEALS_SEC} с.",
        "",
        "## Сводка",
        "",
        "| Что будет при DRY_RUN=0 | Кол-во |",
        "|---|---|",
        f"| Автопереход этапа | **{len(moves)}** |",
        f"| Стоп юристу (В8 / мировое) | **{len(stops)}** |",
        f"| Ждать (без изменений) | {len(waits)} |",
        f"| Парсер: дело не найдено | {len(not_found)} |",
        f"| Ошибка парсера / сайт | {len(errors)} |",
        f"| Пропуск (ручной этап / мировые / нет сайта) | {len(skipped)} |",
        "",
        "### Переходы, которые система хочет сделать",
        "",
    ]
    by_edge = Counter((r["stage"], r.get("to_stage") or "—") for r in moves)
    if by_edge:
        lines += ["| Сейчас | Куда | Кол-во |", "|---|---|---|"]
        for (a, b), n in by_edge.most_common():
            lines.append(f"| {a} | {b} | {n} |")
    else:
        lines.append("_Нет автопереходов._")

    def _table(title: str, items: list[dict], extra_cols: list[str]) -> None:
        lines.extend(["", f"## {title}", ""])
        if not items:
            lines.append("_Нет._")
            return
        headers = ["Сделка", "Дело", "Этап"] + extra_cols
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for r in items:
            cells = [
                str(r["deal_id"]),
                r.get("case_number") or "—",
                r.get("stage") or "—",
            ]
            for col in extra_cols:
                if col == "Куда":
                    cells.append(r.get("to_stage") or "—")
                elif col == "Причина":
                    cells.append((r.get("reason") or "—").replace("|", "/"))
                elif col == "Комментарий":
                    cells.append((r.get("comment") or "—").replace("|", "/")[:180])
                elif col == "Статус парсера":
                    cells.append(r.get("parse_status") or r.get("action") or "—")
                elif col == "Деталь":
                    cells.append((r.get("reason") or r.get("error") or "—").replace("|", "/")[:180])
            lines.append("| " + " | ".join(cells) + " |")

    _table("1. Автопереходы (проверить, что этап в Bitrix отстаёт от сайта)", moves, ["Куда", "Причина", "Комментарий"])
    _table("2. Стоп юристу — без автоперехода", stops, ["Причина", "Комментарий"])
    _table("3. Дело не найдено на сайте", not_found, ["Деталь"])
    _table("4. Ошибки парсера / сайт недоступен", errors, ["Деталь"])
    _table(
        "5. Пропуски (не ошибка логики этапов)",
        [r for r in skipped if r.get("action") != "none"],
        ["Статус парсера", "Деталь"],
    )

    lines += [
        "",
        "## Как читать",
        "",
        "- **Автопереход** — на сайте уже есть событие следующего этапа, в CRM сделка ещё на старом. После `DRY_RUN=0` система перенесёт **на один шаг** за прогон.",
        "- **Стоп юристу** — мировое соглашение; автоматика не двигает. "
        "В8 (апелляция отменила/изменила) — авто в «вступило в силу».",
        "- **Ждать** — сайт соответствует текущему этапу (или не вышел срок 40/21 день).",
        "- Скачок «заседание → решение» — по ТЗ допустим (приоритет над экспертизой/упрощёнкой).",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not bitrix.DRY_RUN:
        print("ABORT: DRY_RUN must be 1", file=sys.stderr)
        return 2
    started = datetime.now(TZ)
    log_dir = Path(os.environ.get("SAPRIN_REPORT_DIR") or "/opt/saprin/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M")
    jsonl_path = log_dir / f"dry-run-{stamp}.jsonl"
    md_path = log_dir / f"dry-run-{stamp}.md"

    deals = pull_deals()
    host_filter = os.environ.get("COURT_HOSTS", "").strip()
    if host_filter.lower() in {"voronezh-city", "vrn-city", "6"}:
        hosts = set(VORONEZH_CITY_RAYON_HOSTS)
    elif host_filter:
        hosts = {h.strip().lower() for h in host_filter.split(",") if h.strip()}
    else:
        hosts = set()
    if hosts:
        before = len(deals)
        deals = [d for d in deals if court_host(d.court_website) in hosts]
        print(f"filter hosts={sorted(hosts)} {before}→{len(deals)}", flush=True)
    rows: list[dict] = []
    print(
        f"pulled {len(deals)} deals, DRY_RUN={bitrix.DRY_RUN} "
        f"concurrency={bitrix.PARSE_CONCURRENCY}",
        flush=True,
    )

    def _one(deal: Deal) -> dict:
        try:
            return process_deal(deal)
        except Exception as exc:  # noqa: BLE001
            return {
                "deal_id": deal.id,
                "case_number": deal.case_number,
                "stage_id": deal.stage_id,
                "stage": _title(deal.stage_id),
                "action": "crash",
                "risk": "error",
                "reason": str(exc),
                "parse_status": "crash",
            }

    pool = CourtParsePool(bitrix.PARSE_CONCURRENCY, host_pause_sec=bitrix.PARSE_HOST_PAUSE_SEC)
    done = pool.run(deals, lambda d: court_host(d.court_website), _one)
    done.sort(key=lambda t: t[0].id)

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for i, (deal, row, err) in enumerate(done, 1):
            if err or row is None:
                row = {
                    "deal_id": deal.id,
                    "case_number": deal.case_number,
                    "action": "crash",
                    "risk": "error",
                    "reason": str(err),
                    "parse_status": "crash",
                }
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"[{i}/{len(done)}] #{deal.id} {deal.case_number} {row.get('action')} "
                f"{row.get('reason')}",
                flush=True,
            )

    finished = datetime.now(TZ)
    stats = {
        "started": started.strftime("%d.%m.%Y %H:%M"),
        "finished": finished.strftime("%d.%m.%Y %H:%M"),
        "count": len(rows),
        "actions": dict(Counter(r.get("action") or "?" for r in rows)),
        "risks": dict(Counter(r.get("risk") or "?" for r in rows)),
    }
    (log_dir / f"dry-run-{stamp}-stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(rows, stats, md_path)
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)
    print(f"jsonl={jsonl_path}", flush=True)
    print(f"md={md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
