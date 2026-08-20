"""CLI: JSON на stdin → JSON {status, result} на stdout. Для PHP/CGI на sweb."""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

ROOT = Path("/home/d/dier555/court-kb-app")


def _load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    _load_env()

    raw = sys.stdin.read()
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        sys.stdout.write(json.dumps({"status": "error", "result": "Тело запроса должно быть JSON."}, ensure_ascii=False))
        return 0

    from scraper.case_lookup.search import CaseQuery, VORONEZH_SUDRF_COURTS, search_case_direct
    from scraper.fetch import Fetcher
    from scraper.proxy_pool import proxies_from_env

    slug = str(body.get("court_slug") or "").strip()
    domain = VORONEZH_SUDRF_COURTS.get(slug)
    if domain is None:
        allowed = ", ".join(VORONEZH_SUDRF_COURTS)
        sys.stdout.write(json.dumps({
            "status": "error",
            "result": f"Неизвестный суд '{slug}'. Допустимые: {allowed}.",
        }, ensure_ascii=False))
        return 0
    case_number = str(body.get("case_number") or "").strip() or None
    last_name = str(body.get("last_name") or "").strip() or None
    if not case_number and not last_name:
        sys.stdout.write(json.dumps({
            "status": "error",
            "result": "Нужно указать case_number или last_name.",
        }, ensure_ascii=False))
        return 0

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
    sys.stdout.write(json.dumps({"status": result.status, "result": text}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
