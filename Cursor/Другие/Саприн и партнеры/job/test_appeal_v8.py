"""В8: апелляция отменила/изменила → «Решение вступило в законную силу»."""

from triggers import (
    STAGE_APPEAL,
    STAGE_IN_FORCE,
    MovementRow,
    decide_next_stage,
)


def test_appeal_unchanged_to_in_force():
    d = decide_next_stage(
        current_stage=STAGE_APPEAL,
        rows=[],
        appeal_result="Оставлено без изменения",
    )
    assert d.action == "move"
    assert d.to_stage == STAGE_IN_FORCE
    assert "unchanged" in d.reason


def test_appeal_cancelled_to_in_force_v8():
    d = decide_next_stage(
        current_stage=STAGE_APPEAL,
        rows=[],
        appeal_result="Решение суда отменено",
    )
    assert d.action == "move"
    assert d.to_stage == STAGE_IN_FORCE
    assert "V8" in d.reason
    assert d.action != "stop_manual"


def test_appeal_changed_to_in_force_v8():
    d = decide_next_stage(
        current_stage=STAGE_APPEAL,
        rows=[],
        appeal_result="Решение изменено",
    )
    assert d.action == "move"
    assert d.to_stage == STAGE_IN_FORCE
    assert "V8" in d.reason


def test_appeal_result_from_movement_row():
    rows = [
        MovementRow(
            event="Результат обжалования",
            date="01.09.2026",
            result="Решение отменено частично",
        ),
    ]
    d = decide_next_stage(current_stage=STAGE_APPEAL, rows=rows)
    assert d.action == "move"
    assert d.to_stage == STAGE_IN_FORCE
