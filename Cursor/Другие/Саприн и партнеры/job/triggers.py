"""Граф переходов воронки «Исполнение» по ТЗ v2.9 §1–2.

Детерминированные правила: только сравнение текстов/дат, без ИИ.
В8 (апелляция отменила/изменила): сразу «Решение вступило в законную силу».
Апелляция: только по «ДВИЖЕНИЕ ЖАЛОБЫ» (не по факту вкладки).
Откатов назад нет — при ошибке этапа только уведомление в календарь.
"""

from __future__ import annotations

import os
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

# «ДДУ 2025 год» — та же воронка; ID подтягивается с портала / STAGE_DDU
STAGE_DDU_NAME = "ДДУ 2025 год"
STAGE_DDU = (os.environ.get("STAGE_DDU") or "").strip()

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

STAGE_TITLE = {
    STAGE_HEARING: "Назначена дата заседания",
    STAGE_SIMPLIFIED: "Упрощенное производство",
    STAGE_EXPERTISE: "Назначена судебная экспертиза",
    STAGE_EXPERTISE_DATE: "Назначена дата экспертизы (ручной)",
    STAGE_FROM_EXPERTISE: "Дело вернулось с экспертизы",
    STAGE_MAIN_NO_EXP: "Без судебной экспертизы, основное",
    STAGE_SETTLEMENT: "Согласовано мировое (ручной)",
    STAGE_DECISION: "Вынесено решение",
    STAGE_APPEAL: "Дело в апелляции",
    STAGE_IN_FORCE: "Решение вступило в законную силу",
    STAGE_REQUEST_IL: "Запросить исполнительный лист",
    STAGE_GOT_IL: "Исполнительный лист получен",
}


def set_stage_ddu(stage_id: str) -> None:
    """Фиксирует STAGE_ID «ДДУ 2025 год» после lookup на портале."""
    global STAGE_DDU
    STAGE_DDU = (stage_id or "").strip()
    if STAGE_DDU:
        STAGE_TITLE[STAGE_DDU] = STAGE_DDU_NAME
        AUTOMATED_STAGES.discard(STAGE_DDU)  # конечная колонка — не крутим дальше


def stage_title(stage_id: str) -> str:
    if not stage_id:
        return "—"
    if stage_id == STAGE_DDU:
        return STAGE_DDU_NAME
    return STAGE_TITLE.get(stage_id, stage_id)


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
class StageAlert:
    """Разовое уведомление в календарь Bitrix (ошибка этапа)."""
    kind: str  # A | B | C
    current_stage: str
    expected_stage: Optional[str]
    detail: str = ""


@dataclass
class TriggerDecision:
    action: str  # none | move | stop_manual | comment_only
    to_stage: Optional[str] = None
    comment: str = ""
    reason: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    alerts: list[StageAlert] = field(default_factory=list)


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


def can_auto_move(from_stage: str, to_stage: str) -> bool:
    """Вперёд по воронке ИЛИ явный боковой ход на «ДДУ 2025 год»."""
    if not to_stage:
        return False
    if is_forward(from_stage, to_stage):
        return True
    if STAGE_DDU and to_stage == STAGE_DDU and from_stage in {
        STAGE_HEARING, STAGE_MAIN_NO_EXP,
    }:
        return True
    return False


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


def _parse_pipe_blob(blob: str) -> tuple[str, list[str], str]:
    parts = [p.strip() for p in str(blob).split("|")]
    published = ""
    cleaned: list[str] = []
    for p in parts:
        if p.lower().startswith("размещено"):
            published = p.split(" ", 1)[-1].strip() if " " in p else p
        else:
            cleaned.append(p)
    date_s = cleaned[0] if cleaned else ""
    return date_s, cleaned[1:], published


def build_movement_from_card_sections(sections: dict) -> list[MovementRow]:
    """Из секций CaseCard. Только вкладка «ДВИЖЕНИЕ ДЕЛА»."""
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
                date_s, rest, published = _parse_pipe_blob(str(blob))
                time_s = rest[0] if len(rest) > 0 else ""
                # эвристика: time?, place?, result, basis…
                # после date: time, place?, result, basis
                result = ""
                basis = ""
                place = ""
                tail = rest[1:] if rest else []
                # если первый rest похож на время HH:MM — это время
                if rest and re.match(r"^\d{1,2}:\d{2}", rest[0] or ""):
                    time_s = rest[0]
                    tail = rest[1:]
                else:
                    time_s = ""
                    tail = rest
                if tail:
                    if len(tail) >= 3:
                        place, result, basis = tail[0], tail[1], tail[2]
                    elif len(tail) == 2:
                        if _contains(tail[0], "назнача", "приостан", "возобнов", "вынесен", "иск", "определ", "оставлен"):
                            result, basis = tail[0], tail[1]
                        else:
                            place, result = tail[0], tail[1]
                    else:
                        result = tail[0]
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


def build_appeal_movement_from_sections(sections: dict) -> list[MovementRow]:
    """Строки «ДВИЖЕНИЕ ЖАЛОБЫ» / вкладки обжалования.

    Колонки: Событие | Дата | Результат | Основание | Примечание | Дата размещения.
    """
    try:
        from sudrf_labels import is_rayon_appeal_movement_section
    except ImportError:  # pragma: no cover
        from job.sudrf_labels import is_rayon_appeal_movement_section  # type: ignore

    rows: list[MovementRow] = []
    for name, items in (sections or {}).items():
        if not is_rayon_appeal_movement_section(str(name)):
            continue
        for item in items or []:
            if not isinstance(item, dict):
                continue
            for event, blob in item.items():
                ev = str(event).strip()
                # шапка жалобы — не строки движения
                if _contains(ev, "вид жалобы", "заявитель", "вышестоящий суд", "жалоба №"):
                    continue
                date_s, rest, published = _parse_pipe_blob(str(blob))
                result, basis, note = "", "", ""
                if len(rest) >= 3:
                    result, basis, note = rest[0], rest[1], rest[2]
                elif len(rest) == 2:
                    result, basis = rest[0], rest[1]
                elif len(rest) == 1:
                    # одно поле: либо результат, либо схлопнутая дата размещения
                    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", rest[0] or ""):
                        result = rest[0]
                rows.append(MovementRow(
                    event=ev,
                    date=date_s,
                    result=result,
                    basis=basis,
                    note=note,
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


def build_appeal_from_text(result_text: str) -> list[MovementRow]:
    """Fallback: блок «--- ОБЖАЛОВАНИЕ… ---» / строки жалобы в тексте карточки."""
    rows: list[MovementRow] = []
    in_block = False
    for line in (result_text or "").splitlines():
        s = line.strip()
        low = s.lower()
        if "обжалование решений" in low or "движение жалобы" in low:
            in_block = True
            continue
        if in_block and s.startswith("---") and "обжалование" not in low and "жалоб" not in low:
            break
        if not in_block:
            continue
        m = re.match(r"^(?:\d+\.\s*)?(.+?):\s*(.*)$", s)
        if not m:
            continue
        event, blob = m.group(1).strip(), m.group(2).strip()
        fake = {"ДВИЖЕНИЕ ЖАЛОБЫ": [{event: blob}]}
        rows.extend(build_appeal_movement_from_sections(fake))
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


def is_complaint_sent_up(row: MovementRow) -> bool:
    return _contains(row.event, "направлено в вышестоящую инстанцию")


def is_complaint_returned_noncompliance(row: MovementRow) -> bool:
    return (
        _contains(row.event, "решение вопроса о принятии жалобы")
        and _contains(row.result, "возвращена")
        and _contains(row.basis, "несоответств")
    )


def is_left_without_consideration_parties_absent(row: MovementRow) -> bool:
    """Шайкин и аналоги: без рассмотрения + неявка сторон."""
    if not _is_main_hearing_event(row):
        return False
    if not _contains(row.result, "без рассмотрения"):
        return False
    return _contains(row.basis, "не явил", "неявка", "не явились")


def decide_next_stage(
    *,
    current_stage: str,
    rows: list[MovementRow],
    tabs: Optional[dict[str, bool]] = None,
    appeal_rows: Optional[list[MovementRow]] = None,
    today: Optional[date] = None,
    stage_enter_date: Optional[date] = None,
    decision_final_date: Optional[date] = None,
    decision_published_at: Optional[date] = None,
    appeal_result: Optional[str] = None,
) -> TriggerDecision:
    """Главная функция графа. Никогда не двигает назад."""
    today = today or date.today()
    tabs = tabs or {}
    appeal_rows = appeal_rows or []
    alerts: list[StageAlert] = []

    sent_up = latest_matching(appeal_rows, is_complaint_sent_up)
    returned = latest_matching(appeal_rows, is_complaint_returned_noncompliance)

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
        # 4) Без рассмотрения + неявка сторон → «ДДУ 2025 год»
        row = latest_matching(rows, is_left_without_consideration_parties_absent)
        if row:
            if not STAGE_DDU:
                return TriggerDecision(
                    action="none",
                    comment=comment_from_row("", row),
                    reason="hearing→ddu: STAGE_DDU не задан",
                    alerts=[StageAlert(
                        kind="B",
                        current_stage=current_stage,
                        expected_stage=None,
                        detail=f"нужен этап «{STAGE_DDU_NAME}», STAGE_DDU не найден на портале",
                    )],
                )
            return TriggerDecision(
                action="move",
                to_stage=STAGE_DDU,
                comment=comment_from_row("", row),
                reason="hearing→ddu: без рассмотрения + неявка",
            )
        # 5) ТЗ: после предзаседания есть «Судебное заседание» без приостановления
        main_row = first_main_hearing_after_prelim_without_suspend(rows)
        if main_row and not is_left_without_consideration_parties_absent(main_row):
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

    # --- Этап 4: Экспертиза → возврат с экспертизы ---
    if current_stage == STAGE_EXPERTISE:
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
        # Ошибка B: сюда попали дела «без рассмотрения + неявка» — в ДДУ, не откат словами
        row_bad = latest_matching(rows, is_left_without_consideration_parties_absent)
        if row_bad:
            if STAGE_DDU and can_auto_move(current_stage, STAGE_DDU):
                return TriggerDecision(
                    action="move",
                    to_stage=STAGE_DDU,
                    comment=comment_from_row("", row_bad),
                    reason="main→ddu: без рассмотрения + неявка",
                    alerts=[StageAlert(
                        kind="B",
                        current_stage=current_stage,
                        expected_stage=STAGE_DDU,
                        detail="ошибочно на «без экспертизы»; сайт: без рассмотрения + неявка",
                    )],
                )
            alerts.append(StageAlert(
                kind="B",
                current_stage=current_stage,
                expected_stage=STAGE_DDU or None,
                detail="сайт: без рассмотрения + неявка — нужен «ДДУ 2025 год»",
            ))
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
                alerts=alerts,
            )
        row = latest_matching(rows, lambda r: _contains(r.result, "вынесено решение"))
        if row:
            return TriggerDecision(
                action="move", to_stage=STAGE_DECISION,
                comment=comment_from_row("", row), reason="main→decision",
                fields=_decision_fields(row),
                alerts=alerts,
            )
        return TriggerDecision(action="none", comment="без изменений", reason="main: no trigger", alerts=alerts)

    # --- Этап 6: Вынесено решение — апелляция по событиям жалобы / 40 дней ---
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

        # 1) Направлено в вышестоящую инстанцию → апелляция
        if sent_up:
            return TriggerDecision(
                action="move", to_stage=STAGE_APPEAL,
                comment=(
                    "На основании данных с сайта суда, в «ДВИЖЕНИЕ ЖАЛОБЫ» появилось событие "
                    "«Направлено в вышестоящую инстанцию»"
                    + (f", дата: {sent_up.date}" if sent_up.date else "")
                    + "."
                ),
                reason="decision→appeal: направлено в вышестоящую инстанцию",
                fields=fields,
            )
        # 2) Жалоба возвращена за несоответствие — остаёмся на «Вынесено решение»
        if returned:
            return TriggerDecision(
                action="none",
                comment=(
                    "На основании данных с сайта суда, жалоба возвращена "
                    "(несоответствие требованиям). Этап «Дело в апелляции» не ставим."
                ),
                reason="decision: appeal returned noncompliance — stay",
                fields=fields,
            )
        # 3) Только вкладка/регистрация без «направлено» — ждём (больше не двигаем по вкладке)
        # 4) 40 дней → вступило в силу
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
        return TriggerDecision(
            action="none", comment="без изменений",
            reason="decision: waiting 40d/appeal sent-up", fields=fields,
        )

    # --- Этап 7: Апелляция ---
    if current_stage == STAGE_APPEAL:
        # Ошибка A: в CRM апелляция, а на сайте возврат / нет «направлено» — этап не откатываем
        if returned and not sent_up:
            alerts.append(StageAlert(
                kind="A",
                current_stage=current_stage,
                expected_stage=STAGE_DECISION,
                detail="жалоба возвращена (несоответствие требованиям); «направлено выше» нет",
            ))
        elif appeal_rows and not sent_up and not returned:
            # вкладка/регистрация есть, но в вышестоящую не ушло
            if not any(is_complaint_sent_up(r) for r in appeal_rows):
                alerts.append(StageAlert(
                    kind="A",
                    current_stage=current_stage,
                    expected_stage=STAGE_DECISION,
                    detail="нет события «Направлено в вышестоящую инстанцию»",
                ))

        ar = (appeal_result or "").strip()
        if not ar:
            row = latest_matching(rows, lambda r: _contains(r.event, "результат обжалования") or _contains(r.result, "оставлено без изменения", "отменено", "изменено"))
            if row:
                ar = row.result or row.event
            # также из строк жалобы
            if not ar:
                row_a = latest_matching(appeal_rows, lambda r: _contains(r.event, "результат обжалования") or _contains(r.result, "оставлено без изменения", "отменено", "изменено"))
                if row_a:
                    ar = row_a.result or row_a.event
        if ar:
            if _contains(ar, "без изменения", "оставлено без изменения"):
                return TriggerDecision(
                    action="move", to_stage=STAGE_IN_FORCE,
                    comment=f"На основании данных с сайта суда, результат обжалования: {ar}",
                    reason="appeal→in_force: unchanged",
                    fields={"appeal_result": ar},
                    alerts=alerts,
                )
            if _contains(ar, "отмен", "изменен", "изменён"):
                return TriggerDecision(
                    action="move", to_stage=STAGE_IN_FORCE,
                    comment=(
                        f"На основании данных с сайта суда, результат обжалования: {ar}. "
                        "После апелляции решение вступило в законную силу."
                    ),
                    reason="appeal→in_force: cancelled/changed (V8)",
                    fields={"appeal_result": ar},
                    alerts=alerts,
                )
        return TriggerDecision(
            action="none", comment="без изменений",
            reason="appeal: waiting result", alerts=alerts,
        )

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

    if STAGE_DDU and current_stage == STAGE_DDU:
        return TriggerDecision(action="none", comment="ДДУ 2025 год — конец ветки", reason="ddu: done")

    if current_stage in MANUAL_ONLY_STAGES:
        return TriggerDecision(action="none", comment="этап ручной — автоматика не меняет", reason="manual stage")

    return TriggerDecision(action="none", comment="без изменений", reason=f"no rules for {current_stage}")


def _decision_fields(row: MovementRow) -> dict[str, Any]:
    fields: dict[str, Any] = {}
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


def _is_proceedings_suspended(row: MovementRow) -> bool:
    return _contains(row.result, "приостановлено") or _contains(
        row.event, "приостановление производства", "приостановлено",
    )


def first_main_hearing_after_prelim_without_suspend(
    rows: list[MovementRow],
) -> Optional[MovementRow]:
    """После «Предварительное судебное заседание» есть «Судебное заседание»
    без приостановления между ними. Дата/результат не важны.
    """
    idx_prev = None
    for i, r in enumerate(rows):
        if _contains(r.event, "предварительное судебное заседание"):
            idx_prev = i
        if idx_prev is None or i <= idx_prev:
            continue
        if not _is_main_hearing_event(r):
            continue
        for mid in rows[idx_prev + 1:i]:
            if _is_proceedings_suspended(mid):
                return None
        return r
    return None


def first_held_main_hearing_no_expertise(
    rows: list[MovementRow],
    today: Optional[date] = None,
) -> Optional[MovementRow]:
    return first_main_hearing_after_prelim_without_suspend(rows)


def _path_to_main_no_expertise(rows: list[MovementRow], today: Optional[date] = None) -> bool:
    return first_main_hearing_after_prelim_without_suspend(rows) is not None


def format_calendar_alert_name(
    *,
    case_number: str,
    current_stage: str,
    expected_stage: Optional[str],
    deal_url: str,
) -> str:
    was = stage_title(current_stage)
    should = stage_title(expected_stage) if expected_stage else STAGE_DDU_NAME
    return (
        f"обратить внимание на стадию процесса - возможна ошибка "
        f"[{case_number or '—'}][{was} → {should}][{deal_url}]"
    )
