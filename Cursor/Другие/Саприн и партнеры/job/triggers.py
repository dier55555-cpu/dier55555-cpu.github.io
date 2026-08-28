"""Граф переходов воронки «Исполнение» по ТЗ v2.9 §1–2.

Детерминированные правила: только сравнение текстов/дат, без ИИ.
В8 (апелляция отменила/изменила) — стоп + комментарий юристу.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional


# STAGE_ID воронки CATEGORY_ID=2
STAGE_HEARING = "C2:UC_VQSC1C"          # Назначена дата заседания
STAGE_SIMPLIFIED = "C2:UC_X3GNNS"       # Упрощенное производство
STAGE_EXPERTISE = "C2:FINAL_INVOICE"    # Назначена судебная экспертиза
STAGE_EXPERTISE_DATE = "C2:UC_YADE6K"   # Назначена дата экспертизы (ручной)
STAGE_FROM_EXPERTISE = "C2:UC_SM5W4O"   # Дело вернулось с экспертизы
STAGE_MAIN_NO_EXP = "C2:UC_IPH4VF"      # Без судебной экспертизы, основное
STAGE_SETTLEMENT = "C2:UC_S1LPCC"       # Согласовано мировое (ручной)
STAGE_DECISION = "C2:UC_GZ6RL3"         # Вынесено решение
STAGE_APPEAL = "C2:UC_YJ087T"           # Дело в апелляции
STAGE_IN_FORCE = "C2:UC_2M4FYU"         # Решение вступило в законную силу
STAGE_REQUEST_IL = "C2:UC_B2ZGR1"       # Запросить исполнительный лист
STAGE_GOT_IL = "C2:UC_ILS0X3"           # Исполнительный лист получен

# Порядок «вперёд» по воронке (для запрета отката автоматикой)
STAGE_ORDER = [
    STAGE_HEARING,
    STAGE_SIMPLIFIED,
    STAGE_EXPERTISE,
    STAGE_EXPERTISE_DATE,
    STAGE_FROM_EXPERTISE,
    STAGE_MAIN_NO_EXP,
    STAGE_SETTLEMENT,
    STAGE_DECISION,
    STAGE_APPEAL,
    STAGE_IN_FORCE,
    STAGE_REQUEST_IL,
    STAGE_GOT_IL,
]

AUTOMATED_STAGES = {
    STAGE_HEARING, STAGE_SIMPLIFIED, STAGE_EXPERTISE, STAGE_FROM_EXPERTISE,
    STAGE_MAIN_NO_EXP, STAGE_DECISION, STAGE_APPEAL, STAGE_IN_FORCE,
    STAGE_REQUEST_IL, STAGE_GOT_IL,
}

MANUAL_ONLY_STAGES = {
    STAGE_EXPERTISE_DATE, STAGE_SETTLEMENT,
}


@dataclass
class MovementRow:
    event: str = ""
    date: str = ""
    time: str = ""
    place: str = ""
    result: str = ""
    basis: str = ""
    note: str = ""
    published_at: str = ""


@dataclass
class TriggerDecision:
    action: str  # none | move | stop_manual | comment_only
    to_stage: Optional[str] = None
    comment: str = ""
    reason: str = ""
    fields: dict[str, Any] = field(default_factory=dict)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ").strip()).lower()


def _contains(hay: str, *needles: str) -> bool:
    h = _norm(hay)
    return any(_norm(n) in h for n in needles if n)


def parse_ru_date(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", raw)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def stage_rank(stage_id: str) -> int:
    try:
        return STAGE_ORDER.index(stage_id)
    except ValueError:
        return -1


def is_forward(from_stage: str, to_stage: str) -> bool:
    a, b = stage_rank(from_stage), stage_rank(to_stage)
    if a < 0 or b < 0:
        return False
    return b > a


def latest_matching(rows: list[MovementRow], pred) -> Optional[MovementRow]:
    for row in reversed(rows):
        if pred(row):
            return row
    return None


def comment_from_row(prefix: str, row: MovementRow) -> str:
    parts = [
        "На основании данных с сайта суда,",
        row.event or "—",
    ]
    if row.result:
        parts.append(f"— {row.result}")
    if row.basis:
        parts.append(f", основание: {row.basis}")
    if row.date or row.time:
        parts.append(f", дата события: {row.date} {row.time}".rstrip())
    if row.published_at:
        parts.append(f", дата размещения на сайте: {row.published_at}")
    return prefix + " ".join(parts)


def build_movement_from_card_sections(sections: dict) -> list[MovementRow]:
    """Из секций CaseCard (ключ события → 'дата | время | … | размещено …').

    Берём только вкладку «ДВИЖЕНИЕ ДЕЛА», не «ДВИЖЕНИЕ ЖАЛОБЫ».
    """
    try:
        from sudrf_labels import is_rayon_movement_tab
    except ImportError:  # pragma: no cover
        from job.sudrf_labels import is_rayon_movement_tab  # type: ignore

    rows: list[MovementRow] = []
    for name, items in (sections or {}).items():
        if not is_rayon_movement_tab(str(name)):
            continue
        for item in items or []:
            if not isinstance(item, dict):
                continue
            for event, blob in item.items():
                parts = [p.strip() for p in str(blob).split("|")]
                published = ""
                cleaned = []
                for p in parts:
                    if p.lower().startswith("размещено"):
                        published = p.split(" ", 1)[-1].strip() if " " in p else p
                    else:
                        cleaned.append(p)
                # эвристика: date, time, place?, result, basis…
                date_s = cleaned[0] if len(cleaned) > 0 else ""
                time_s = cleaned[1] if len(cleaned) > 1 else ""
                rest = cleaned[2:]
                result = ""
                basis = ""
                place = ""
                if rest:
                    # если 3+ хвоста: место, результат, основание
                    if len(rest) >= 3:
                        place, result, basis = rest[0], rest[1], rest[2]
                    elif len(rest) == 2:
                        # часто результат + основание ИЛИ место + результат
                        if _contains(rest[0], "назнача", "приостан", "возобнов", "вынесен", "иск", "определ"):
                            result, basis = rest[0], rest[1]
                        else:
                            place, result = rest[0], rest[1]
                    else:
                        result = rest[0]
                rows.append(MovementRow(
                    event=str(event).strip(),
                    date=date_s,
                    time=time_s,
                    place=place,
                    result=result,
                    basis=basis,
                    published_at=published,
                ))
    return rows


def build_movement_from_text(result_text: str) -> list[MovementRow]:
    """Fallback: строки вида 'N. Событие: дата | время | …' из format_case_card."""
    rows: list[MovementRow] = []
    in_block = False
    for line in (result_text or "").splitlines():
        s = line.strip()
        if s.startswith("--- Движение дела"):
            in_block = True
            continue
        if in_block and s.startswith("---"):
            break
        if not in_block:
            continue
        m = re.match(r"^\d+\.\s*(.+?):\s*(.*)$", s)
        if not m:
            continue
        event, blob = m.group(1).strip(), m.group(2).strip()
        fake = {"ДВИЖЕНИЕ ДЕЛА": [{event: blob}]}
        rows.extend(build_movement_from_card_sections(fake))
    return rows


def detect_tabs(result_text: str, sections: Optional[dict] = None) -> dict[str, bool]:
    """Детект вкладок райсуда по точным именам (job/sudrf_labels.py)."""
    try:
        from sudrf_labels import (
            is_rayon_acts_tab,
            is_rayon_appeal_tab,
            is_rayon_writs_tab,
        )
    except ImportError:  # pragma: no cover
        from job.sudrf_labels import (  # type: ignore
            is_rayon_acts_tab,
            is_rayon_appeal_tab,
            is_rayon_writs_tab,
        )

    names = [str(k) for k in (sections or {}).keys()]
    blob = result_text or ""
    appeal = any(is_rayon_appeal_tab(n) for n in names) or is_rayon_appeal_tab(blob)
    il = any(is_rayon_writs_tab(n) for n in names) or is_rayon_writs_tab(blob)
    acts = any(is_rayon_acts_tab(n) for n in names) or is_rayon_acts_tab(blob)
    return {"appeal": appeal, "il": il, "acts": acts}


def decide_next_stage(
    *,
    current_stage: str,
    rows: list[MovementRow],
    tabs: Optional[dict[str, bool]] = None,
    today: Optional[date] = None,
    stage_enter_date: Optional[date] = None,
    decision_final_date: Optional[date] = None,
    decision_published_at: Optional[date] = None,
    appeal_result: Optional[str] = None,
) -> TriggerDecision:
    """Главная функция графа. Никогда не двигает назад."""
    today = today or date.today()
    tabs = tabs or {}

    # --- Этап 2: Назначена дата заседания — развилка по приоритету ---
    if current_stage == STAGE_HEARING:
        # 1) Вынесено решение
        row = latest_matching(rows, lambda r: (
            _contains(r.event, "судебное заседание")
            and _contains(r.result, "вынесено решение")
        ) or _contains(r.result, "вынесено решение по делу"))
        if row:
            return TriggerDecision(
                action="move",
                to_stage=STAGE_DECISION,
                comment=comment_from_row("", row),
                reason="hearing→decision: вынесено решение",
                fields=_decision_fields(row),
            )
        # 2) Экспертиза
        row = latest_matching(rows, lambda r: (
            _contains(r.result, "производство по делу приостановлено")
            and _contains(r.basis, "назначение судом экспертизы")
        ))
        if row:
            return TriggerDecision(
                action="move",
                to_stage=STAGE_EXPERTISE,
                comment=comment_from_row("", row),
                reason="hearing→expertise",
            )
        # 3) Упрощённое
        row = latest_matching(rows, lambda r: _contains(
            r.event, "переход к рассмотрению дела в порядке упрощённого производства",
            "упрощенного производства", "упрощённого производства",
        ))
        if row:
            return TriggerDecision(
                action="move",
                to_stage=STAGE_SIMPLIFIED,
                comment=(
                    f"На основании данных с сайта суда, {row.event} "
                    f"{row.date} {row.time}, дата размещения на сайте: {row.published_at or '—'}"
                ),
                reason="hearing→simplified",
            )
        # 4) Без экспертизы: после предв. заседания состоялось СЗ (не будущая дата)
        #    без приостановления; «оставлено без рассмотрения» — не этот этап.
        main_row = first_held_main_hearing_no_expertise(rows, today)
        if main_row:
            return TriggerDecision(
                action="move",
                to_stage=STAGE_MAIN_NO_EXP,
                comment=comment_from_row("", main_row),
                reason="hearing→main_no_expertise",
            )
        return TriggerDecision(action="none", comment="без изменений", reason="hearing: no trigger")

    # --- Этап 3: Упрощённое → только решение ---
    if current_stage == STAGE_SIMPLIFIED:
        row = latest_matching(rows, lambda r: _contains(r.result, "вынесено решение"))
        if row:
            return TriggerDecision(
                action="move", to_stage=STAGE_DECISION,
                comment=comment_from_row("", row), reason="simplified→decision",
                fields=_decision_fields(row),
            )
        return TriggerDecision(action="none", comment="без изменений", reason="simplified: no trigger")

    # --- Этап 4: Экспертиза → (ручная дата) → возврат с экспертизы ---
    if current_stage == STAGE_EXPERTISE:
        # автоматика сама дату экспертизы не ставит; ждём «возобновлено» после назначения экспертизы
        row = latest_matching(rows, lambda r: _contains(r.result, "производство по делу возобновлено") or _contains(r.event, "возобновлено"))
        if row and _had_expertise_suspend(rows):
            return TriggerDecision(
                action="move", to_stage=STAGE_FROM_EXPERTISE,
                comment=comment_from_row("", row), reason="expertise→from_expertise",
            )
        return TriggerDecision(action="none", comment="без изменений", reason="expertise: waiting")

    if current_stage == STAGE_FROM_EXPERTISE:
        row = latest_matching(rows, lambda r: _contains(r.result, "вынесено решение"))
        if row:
            return TriggerDecision(
                action="move", to_stage=STAGE_DECISION,
                comment=comment_from_row("", row), reason="from_expertise→decision",
                fields=_decision_fields(row),
            )
        return TriggerDecision(action="none", comment="без изменений", reason="from_expertise: no trigger")

    # --- Этап 5а: Без экспертизы, основное ---
    if current_stage == STAGE_MAIN_NO_EXP:
        row_settle = latest_matching(rows, lambda r: (
            _contains(r.result, "производство по делу прекращено")
            and _contains(r.basis, "мировое")
        ))
        if row_settle:
            return TriggerDecision(
                action="stop_manual",
                comment=(
                    "На сайте: производство прекращено (мировое соглашение). "
                    "Этап «Согласовано мировое» — только вручную."
                ),
                reason="main→settlement manual",
            )
        row = latest_matching(rows, lambda r: _contains(r.result, "вынесено решение"))
        if row:
            return TriggerDecision(
                action="move", to_stage=STAGE_DECISION,
                comment=comment_from_row("", row), reason="main→decision",
                fields=_decision_fields(row),
            )
        return TriggerDecision(action="none", comment="без изменений", reason="main: no trigger")

    # --- Этап 6: Вынесено решение — 40 дней / апелляция ---
    if current_stage == STAGE_DECISION:
        d = decision_final_date
        if d is None:
            row_final = latest_matching(rows, lambda r: _contains(
                r.event, "изготовлено мотивированное решение в окончательной форме",
            ))
            if row_final:
                d = parse_ru_date(row_final.date)
                pub = parse_ru_date(row_final.published_at)
                fields = {
                    "decision_date": row_final.date,
                    "decision_published_at": row_final.published_at,
                    "deadline_40d": (d + timedelta(days=40)).isoformat() if d else "",
                }
            else:
                fields = {}
                pub = decision_published_at
        else:
            fields = {}
            pub = decision_published_at

        if tabs.get("appeal"):
            return TriggerDecision(
                action="move", to_stage=STAGE_APPEAL,
                comment="На основании данных с сайта суда появилась вкладка «ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)».",
                reason="decision→appeal: tab ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)",
                fields=fields,
            )
        # 40 дней от даты изготовления (D)
        if d and today >= d + timedelta(days=40):
            return TriggerDecision(
                action="move", to_stage=STAGE_IN_FORCE,
                comment=(
                    f"На основании данных с сайта суда, решение вступило в законную силу "
                    f"{(d + timedelta(days=40)).strftime('%d.%m.%Y')}"
                ),
                reason="decision→in_force: 40 days",
                fields=fields,
            )
        return TriggerDecision(action="none", comment="без изменений", reason="decision: waiting 40d/appeal", fields=fields)

    # --- Этап 7: Апелляция ---
    if current_stage == STAGE_APPEAL:
        ar = (appeal_result or "").strip()
        if not ar:
            # попробуем из движения
            row = latest_matching(rows, lambda r: _contains(r.event, "результат обжалования") or _contains(r.result, "оставлено без изменения", "отменено", "изменено"))
            if row:
                ar = row.result or row.event
        if ar:
            if _contains(ar, "без изменения", "оставлено без изменения"):
                return TriggerDecision(
                    action="move", to_stage=STAGE_IN_FORCE,
                    comment=f"На основании данных с сайта суда, результат обжалования: {ar}",
                    reason="appeal→in_force: unchanged",
                    fields={"appeal_result": ar},
                )
            if _contains(ar, "отмен", "изменен", "изменён"):
                return TriggerDecision(
                    action="stop_manual",
                    comment=(
                        f"Апелляция отменила/изменила решение: «{ar}». "
                        "Открытый вопрос В8 — автоматический перевод не выполняется, нужно решение юриста."
                    ),
                    reason="appeal V8 open",
                    fields={"appeal_result": ar},
                )
        return TriggerDecision(action="none", comment="без изменений", reason="appeal: waiting result")

    # --- Этап 8: Вступило в силу → через 21 день запросить ИЛ ---
    if current_stage == STAGE_IN_FORCE:
        enter = stage_enter_date
        if enter and today >= enter + timedelta(days=21):
            return TriggerDecision(
                action="move", to_stage=STAGE_REQUEST_IL,
                comment="На 21-й день после вступления решения в законную силу — этап «Запросить исполнительный лист».",
                reason="in_force→request_il: 21 days",
            )
        return TriggerDecision(action="none", comment="без изменений", reason="in_force: waiting 21d")

    # --- Этап 9: Запросить ИЛ → получен ---
    if current_stage == STAGE_REQUEST_IL:
        if tabs.get("il"):
            return TriggerDecision(
                action="move", to_stage=STAGE_GOT_IL,
                comment="На основании данных с сайта суда появилась вкладка «ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ».",
                reason="request_il→got_il",
            )
        row = latest_matching(rows, lambda r: _contains(r.event, "исполнительн") and _contains(r.event, "лист"))
        if row:
            return TriggerDecision(
                action="move", to_stage=STAGE_GOT_IL,
                comment=comment_from_row("", row),
                reason="request_il→got_il: movement",
            )
        return TriggerDecision(action="none", comment="без изменений", reason="request_il: waiting")

    if current_stage == STAGE_GOT_IL:
        return TriggerDecision(action="none", comment="конец автоматизации", reason="got_il: done")

    if current_stage in MANUAL_ONLY_STAGES:
        return TriggerDecision(action="none", comment="этап ручной — автоматика не меняет", reason="manual stage")

    return TriggerDecision(action="none", comment="без изменений", reason=f"no rules for {current_stage}")


def _decision_fields(row: MovementRow) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    # если это строка изготовления — заполним даты
    if _contains(row.event, "изготовлено мотивированное решение"):
        d = parse_ru_date(row.date)
        fields["decision_date"] = row.date
        fields["decision_published_at"] = row.published_at
        if d:
            fields["deadline_40d"] = (d + timedelta(days=40)).isoformat()
    return fields


def _had_expertise_suspend(rows: list[MovementRow]) -> bool:
    return any(
        _contains(r.result, "приостановлено") and _contains(r.basis, "экспертиз")
        for r in rows
    )


def _is_main_hearing_event(row: MovementRow) -> bool:
    return _contains(row.event, "судебное заседание") and not _contains(row.event, "предварительн")


def _is_not_main_track_result(row: MovementRow) -> bool:
    """Исходы, которые не означают «перешли в основное без экспертизы»."""
    return _contains(
        row.result,
        "без рассмотрения",
        "прекращено",
        "оставлено без движения",
        "приостановлено",
        "вынесено решение",  # это другой приоритет, сюда не должны попасть
    )


def first_held_main_hearing_no_expertise(
    rows: list[MovementRow],
    today: Optional[date] = None,
) -> Optional[MovementRow]:
    """Предзаседание → состоявшееся СЗ без приостановки/экспертизы.

    Не триггерим, если СЗ только назначено на будущую дату или результат пустой
    («ещё не прошло»), и если иск оставили без рассмотрения / производство прекратили.
    """
    today = today or date.today()
    idx_prev = None
    for i, r in enumerate(rows):
        if _contains(r.event, "предварительное судебное заседание"):
            idx_prev = i
        if idx_prev is None or i <= idx_prev:
            continue
        if not _is_main_hearing_event(r):
            continue
        event_day = parse_ru_date(r.date)
        if event_day is None or event_day > today:
            continue
        if not (r.result or "").strip():
            continue
        if _is_not_main_track_result(r):
            continue
        for mid in rows[idx_prev + 1:i]:
            if _contains(mid.result, "приостановлено") or _contains(mid.event, "приостановлено"):
                return None
        return r
    return None


def _path_to_main_no_expertise(rows: list[MovementRow], today: Optional[date] = None) -> bool:
    return first_held_main_hearing_no_expertise(rows, today) is not None
