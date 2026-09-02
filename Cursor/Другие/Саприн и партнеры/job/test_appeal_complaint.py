"""Апелляция по «ДВИЖЕНИЕ ЖАЛОБЫ» + Шайкин → ДДУ 2025."""

from triggers import (
    STAGE_APPEAL,
    STAGE_DECISION,
    STAGE_HEARING,
    STAGE_MAIN_NO_EXP,
    MovementRow,
    build_appeal_movement_from_sections,
    decide_next_stage,
    set_stage_ddu,
)


STAGE_DDU_TEST = "C2:UC_DDU2025"


def setup_function():
    set_stage_ddu(STAGE_DDU_TEST)


def test_appeal_sent_up_moves_to_appeal():
    appeal = [
        MovementRow(event="Регистрация жалобы (представления) в суде", date="07.08.2026"),
        MovementRow(event="Направлено в вышестоящую инстанцию", date="12.08.2026", published_at="11.08.2026"),
    ]
    d = decide_next_stage(
        current_stage=STAGE_DECISION,
        rows=[],
        appeal_rows=appeal,
    )
    assert d.action == "move"
    assert d.to_stage == STAGE_APPEAL
    assert "направлено" in d.reason.lower()


def test_appeal_returned_stays_on_decision():
    appeal = [
        MovementRow(event="Регистрация жалобы (представления) в суде", date="10.12.2025"),
        MovementRow(
            event="Решение вопроса о принятии жалобы (представления) к рассмотрению",
            date="01.04.2026",
            result="Жалоба (предст.) ВОЗВРАЩЕНА",
            basis="НЕСООТВЕТСТВИЕ ТРЕБОВАНИЯМ",
            published_at="07.04.2026",
        ),
    ]
    d = decide_next_stage(current_stage=STAGE_DECISION, rows=[], appeal_rows=appeal)
    assert d.action == "none"
    assert d.to_stage is None
    assert "returned" in d.reason


def test_appeal_tab_alone_does_not_move():
    d = decide_next_stage(
        current_stage=STAGE_DECISION,
        rows=[],
        tabs={"appeal": True},
        appeal_rows=[
            MovementRow(event="Регистрация жалобы (представления) в суде", date="07.08.2026"),
        ],
    )
    assert d.action == "none"
    assert d.to_stage is None


def test_wrong_appeal_stage_alerts_no_rollback():
    appeal = [
        MovementRow(
            event="Решение вопроса о принятии жалобы (представления) к рассмотрению",
            date="01.04.2026",
            result="Жалоба (предст.) ВОЗВРАЩЕНА",
            basis="НЕСООТВЕТСТВИЕ ТРЕБОВАНИЯМ",
        ),
    ]
    d = decide_next_stage(current_stage=STAGE_APPEAL, rows=[], appeal_rows=appeal)
    assert d.action == "none"
    assert d.to_stage is None
    assert any(a.kind == "A" for a in d.alerts)
    assert d.alerts[0].expected_stage == STAGE_DECISION


def test_shaykin_to_ddu():
    rows = [
        MovementRow(event="Предварительное судебное заседание", date="01.03.2026"),
        MovementRow(
            event="Судебное заседание",
            date="13.04.2026",
            result="Иск (заявление, жалоба) оставлены без рассмотрения",
            basis="СТОРОНЫ (не просившие о разбирательстве в их отсутствие) НЕ ЯВИЛИСЬ В СУД ПО ВТОРИЧНОМУ ВЫЗОВУ",
        ),
    ]
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows)
    assert d.action == "move"
    assert d.to_stage == STAGE_DDU_TEST
    assert "ddu" in d.reason


def test_shaykin_not_main_no_expertise():
    rows = [
        MovementRow(event="Предварительное судебное заседание", date="01.03.2026"),
        MovementRow(
            event="Судебное заседание",
            date="13.04.2026",
            result="Иск (заявление, жалоба) оставлены без рассмотрения",
            basis="СТОРОНЫ НЕ ЯВИЛИСЬ В СУД ПО ВТОРИЧНОМУ ВЫЗОВУ",
        ),
    ]
    d = decide_next_stage(current_stage=STAGE_HEARING, rows=rows)
    assert d.to_stage != STAGE_MAIN_NO_EXP


def test_main_no_exp_wrong_stage_moves_to_ddu_with_alert():
    rows = [
        MovementRow(
            event="Судебное заседание",
            date="13.04.2026",
            result="оставлены без рассмотрения",
            basis="стороны не явились",
        ),
    ]
    d = decide_next_stage(current_stage=STAGE_MAIN_NO_EXP, rows=rows)
    assert d.action == "move"
    assert d.to_stage == STAGE_DDU_TEST
    assert any(a.kind == "B" for a in d.alerts)


def test_parse_appeal_sections_pipe():
    sections = {
        "ДВИЖЕНИЕ ЖАЛОБЫ": [
            {"Направлено в вышестоящую инстанцию": "12.08.2026 |  |  |  | размещено 11.08.2026"},
        ],
    }
    rows = build_appeal_movement_from_sections(sections)
    assert len(rows) == 1
    assert "направлено" in rows[0].event.lower()
    assert rows[0].date.startswith("12.08")
