#!/home/d/dier555/court-kb-app/venv/bin/python3.11
"""CGI-обёртка /delo для хостинга sweb, где пользовательский uvicorn
не принимает соединения на произвольном порту (CageFS). Запускается Apache
на каждый POST и ходит на sudrf через пул резидентных прокси."""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

ROOT = Path("/home/d/dier555/court-kb-app")
ENV_FILE = ROOT / ".env"


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _respond(status_code: int, payload: dict) -> None:
    sys.stdout.write(f"Status: {status_code}\n")
    sys.stdout.write("Content-Type: application/json; charset=utf-8\n\n")
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def main() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    _load_env()

    expected = os.environ.get("COURT_KB_API_KEY")
    incoming = os.environ.get("HTTP_X_API_KEY") or ""
    if expected and incoming != expected:
        _respond(401, {"status": "error", "result": "Неверный или отсутствующий X-API-Key"})
        return

    length = int(os.environ.get("CONTENT_LENGTH") or "0")
    raw = sys.stdin.read(length) if length else ""
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        _respond(400, {"status": "error", "result": "Тело запроса должно быть JSON."})
        return

    from scraper.case_lookup.search import CaseQuery, VORONEZH_SUDRF_COURTS, search_case_direct
    from scraper.fetch import Fetcher
    from scraper.proxy_pool import proxies_from_env

    slug = str(body.get("court_slug") or "").strip()
    domain = VORONEZH_SUDRF_COURTS.get(slug)
    if domain is None:
        allowed = ", ".join(VORONEZH_SUDRF_COURTS)
        _respond(200, {"status": "error", "result": f"Неизвестный суд '{slug}'. Допустимые: {allowed}."})
        return
    case_number = str(body.get("case_number") or "").strip() or None
    last_name = str(body.get("last_name") or "").strip() or None
    if not case_number and not last_name:
        _respond(200, {"status": "error", "result": "Нужно указать case_number или last_name."})
        return

    proxy_urls = proxies_from_env()
    random.shuffle(proxy_urls)
    fetcher = Fetcher(proxy_urls=proxy_urls, delay_range=(0.0, 0.0), timeout=12.0, max_retries=2)
    result = search_case_direct(
        fetcher,
        domain,
        CaseQuery(case_number=case_number, last_name=last_name),
        production_type=str(body.get("production_type") or "civil_first_instance"),
    )
    text = result.as_text() if result.status == "found" else result.message
    _respond(200, {"status": result.status, "result": text})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _respond(500, {"status": "error", "result": f"Ошибка поиска дела: {exc}"})
