"""Тонкий HTTP, который будит job. Не путать с Анниным :8080/delo — слушать другой порт."""

from __future__ import annotations

import os
import threading

from fastapi import FastAPI, Header, HTTPException

from bitrix import run_daily_job

app = FastAPI(title="БитриксЮрист", version="0.1.0")
_lock = threading.Lock()
_running = False
_last: dict | None = None


def _authorized(key: str | None) -> bool:
    expected = os.environ.get("BITRIX_YURIST_API_KEY", "").strip()
    if not expected:
        return True
    return key == expected


def _run() -> None:
    global _running, _last
    try:
        _last = run_daily_job()
    finally:
        _running = False


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "running": _running, "last": _last}


@app.post("/run")
def run(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    global _running
    if not _authorized(x_api_key):
        raise HTTPException(status_code=401, detail="bad api key")
    if not _lock.acquire(blocking=False):
        return {"accepted": False, "reason": "busy"}
    try:
        if _running:
            return {"accepted": False, "reason": "already running"}
        _running = True
        threading.Thread(target=_run, daemon=True).start()
        return {"accepted": True}
    finally:
        _lock.release()
