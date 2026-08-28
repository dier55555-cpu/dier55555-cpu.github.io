"""ТЗ: предзаседание → СЗ без приостановления между ними → «без экспертизы, основное»."""

from datetime import date

from triggers import (
    STAGE_HEARING,
    STAGE_MAIN_NO_EXP,
    MovementRow,
    decide_next_stage,
    first_main_hearing_after_prelim_without_suspend,
)


TODAY = date(2026, 8, 28)


def _rows(*pairs: tuple[str, str, str]) -> list[MovementRow]:
    out = []
    for event, dt, result in pairs:
        out.append(MovementRow(event=event, date=dt, result=result))
    return out


def test_future_scheduled_hearing_is_main_no_expertise():
    rows = _rows(
        ("Предварительное судебное заседание", "04.08.2026", "Назначено судебное заседание"),
        ("Судебное заседание", "10.09.2026", ""),
    )
    assert first_main_hearing_after_prelim_without_suspend(rows) is not None
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows, today=TODAY)
    assert d.action == "move"
    assert d.to_stage == STAGE_MAIN_NO_EXP


def test_left_without_consideration_still_main_no_expertise():
    rows = _rows(
        ("Предварительное судебное заседание", "01.06.2026", ""),
        (
            "Судебное заседание",
            "12.08.2026",
            "Иск (заявление, жалоба) оставлены без рассмотрения",
        ),
    )
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows, today=TODAY)
    assert d.action == "move"
    assert d.to_stage == STAGE_MAIN_NO_EXP


def test_postponed_hearing_is_main_no_expertise():
    rows = _rows(
        ("Предварительное судебное заседание", "01.07.2026", ""),
        ("Судебное заседание", "20.08.2026", "Заседание отложено"),
    )
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows, today=TODAY)
    assert d.action == "move"
    assert d.to_stage == STAGE_MAIN_NO_EXP


def test_suspend_between_blocks():
    rows = _rows(
        ("Предварительное судебное заседание", "01.07.2026", ""),
        ("Производство по делу приостановлено", "10.07.2026", "Производство по делу приостановлено"),
        ("Судебное заседание", "20.08.2026", "Заседание отложено"),
    )
    assert first_main_hearing_after_prelim_without_suspend(rows) is None
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows, today=TODAY)
    assert d.to_stage != STAGE_MAIN_NO_EXP
