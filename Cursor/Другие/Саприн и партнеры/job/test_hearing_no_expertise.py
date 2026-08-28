"""Правило «без экспертизы»: не по будущему СЗ и не по «без рассмотрения»."""

from datetime import date

from triggers import (
    STAGE_HEARING,
    STAGE_MAIN_NO_EXP,
    MovementRow,
    decide_next_stage,
    first_held_main_hearing_no_expertise,
)


TODAY = date(2026, 8, 28)


def _rows(*pairs: tuple[str, str, str]) -> list[MovementRow]:
    out = []
    for event, dt, result in pairs:
        out.append(MovementRow(event=event, date=dt, result=result))
    return out


def test_future_hearing_is_not_main_no_expertise():
    rows = _rows(
        ("Предварительное судебное заседание", "04.08.2026", "Назначено судебное заседание"),
        ("Судебное заседание", "10.09.2026", ""),
    )
    assert first_held_main_hearing_no_expertise(rows, TODAY) is None
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows, today=TODAY)
    assert d.action == "none"
    assert d.reason == "hearing: no trigger"


def test_left_without_consideration_is_not_main_no_expertise():
    rows = _rows(
        ("Предварительное судебное заседание", "01.06.2026", ""),
        (
            "Судебное заседание",
            "12.08.2026",
            "Иск (заявление, жалоба) оставлены без рассмотрения",
        ),
    )
    assert first_held_main_hearing_no_expertise(rows, TODAY) is None
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows, today=TODAY)
    assert d.to_stage != STAGE_MAIN_NO_EXP


def test_postponed_past_hearing_is_main_no_expertise():
    rows = _rows(
        ("Предварительное судебное заседание", "01.07.2026", ""),
        ("Судебное заседание", "20.08.2026", "Заседание отложено"),
    )
    row = first_held_main_hearing_no_expertise(rows, TODAY)
    assert row is not None
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows, today=TODAY)
    assert d.action == "move"
    assert d.to_stage == STAGE_MAIN_NO_EXP


def test_expertise_suspend_blocks():
    rows = _rows(
        ("Предварительное судебное заседание", "01.07.2026", ""),
        ("Судебное заседание", "10.07.2026", "Производство по делу приостановлено"),
        ("Судебное заседание", "20.08.2026", "Заседание отложено"),
    )
    # mid row result приостановлено — но basis не экспертиза; _path checks any приостановлено
    assert first_held_main_hearing_no_expertise(rows, TODAY) is None
