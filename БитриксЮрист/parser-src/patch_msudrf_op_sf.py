"""msudrf search via op=sf + g1_case__CASE_NUMBERSS (JS theme 2.0)."""

from __future__ import annotations

from pathlib import Path


OLD = '''    prod = SUDRF_PRODUCTION.get(production_type) or SUDRF_PRODUCTION["civil_first_instance"]
    case_number = normalize_case_number(query.case_number)
    last_name = (query.last_name or "").strip() or None
    if not case_number and not last_name:
        return CaseSearchResult("error", "Нужно указать case_number или last_name.")

    params = {
        "name": "sud_delo",
        "srv_num": "1",
        "name_op": "r",
        "delo_id": str(prod["delo_id"]),
        "case_type": "0",
        "new": "0",
        "delo_table": prod["table"],
    }
    if case_number:
        params[prod["case_number_field"]] = case_number
    if last_name:
        params[prod["last_name_field"]] = last_name

    from urllib.parse import urlencode as _urlencode
    search_url = f"https://{domain}/modules.php?{_urlencode(params)}"
    fetch_result = fetcher.request("GET", search_url, respect_robots=False)
'''

NEW = '''    prod = SUDRF_PRODUCTION.get(production_type) or SUDRF_PRODUCTION["civil_first_instance"]
    case_number = normalize_case_number(query.case_number)
    last_name = (query.last_name or "").strip() or None
    if not case_number and not last_name:
        return CaseSearchResult("error", "Нужно указать case_number или last_name.")

    host = (domain or "").lower()
    is_ms = host.endswith(".msudrf.ru")

    # Районные sudrf: классический name_op=r + G1_CASE__*.
    # Мировые (тема 2.0): кнопка «Искать» собирает op=sf + g1_case__CASE_NUMBERSS.
    if is_ms:
        params = {
            "name": "sud_delo",
            "op": "sf",
            "delo_id": str(prod["delo_id"]),
        }
        if case_number:
            params["g1_case__CASE_NUMBERSS"] = case_number
        if last_name:
            # поле стороны на форме гражданских
            params["G1_PARTS__NAMESS"] = last_name
    else:
        params = {
            "name": "sud_delo",
            "srv_num": "1",
            "name_op": "r",
            "delo_id": str(prod["delo_id"]),
            "case_type": "0",
            "new": "0",
            "delo_table": prod["table"],
        }
        if case_number:
            params[prod["case_number_field"]] = case_number
        if last_name:
            params[prod["last_name_field"]] = last_name

    from urllib.parse import urlencode as _urlencode
    search_url = f"https://{domain}/modules.php?{_urlencode(params)}"
    fetch_result = fetcher.request("GET", search_url, respect_robots=False)
'''


def patch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if 'params["g1_case__CASE_NUMBERSS"]' in text and 'is_ms = host.endswith(".msudrf.ru")' in text:
        print("already patched")
        return
    if OLD not in text:
        raise SystemExit("OLD block not found")
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("patched", path)


if __name__ == "__main__":
    patch(Path("/opt/bitrix-delo/scraper/case_lookup/search.py"))
