"""Ротация отчётов: оставляем KEEP последних штампов."""

import tempfile
from datetime import timedelta
from pathlib import Path

from run_report import RunRecorder, write_run_bundle


def test_rotate_keeps_seven():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        rec = RunRecorder("daily")
        base = rec.started.replace(second=0, microsecond=0)
        for i in range(9):
            rec.started = base + timedelta(minutes=i)
            rec.moves = []
            rec.errors = []
            write_run_bundle(rec, {"total": 1, "moved": 0, "errors": 0}, root=root, keep=7, dry_run=True)
        mds = list((root / "runs" / "daily").glob("*.md"))
        assert len(mds) == 7


def test_move_row_has_from_to():
    rec = RunRecorder("weekly")
    rec.add_move(
        deal_id=1,
        case_number="2-1/2026",
        from_stage="C2:UC_VQSC1C",
        to_stage="C2:UC_GZ6RL3",
        reason="hearing→decision",
        applied=True,
        prev_known="C2:UC_VQSC1C",
        prev_enter="2026-01-01",
    )
    assert rec.moves[0]["from_stage"] == "C2:UC_VQSC1C"
    assert rec.moves[0]["applied"] is True
