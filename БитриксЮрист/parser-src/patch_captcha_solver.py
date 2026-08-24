"""Подключение 2captcha к bitrix-delo: gate kcaptcha на msudrf + solver в /delo.

Применять на VPS:
  python3 patch_captcha_solver.py
"""

from __future__ import annotations

from pathlib import Path

SEARCH_HELPERS = '''
def _looks_captcha_gate(html: str) -> bool:
    low = (html or "").lower()
    return ("дополнительную проверку" in low and "captcha" in low) or (
        "для продолжения необходимо пройти" in low
    ) or ('id="kcaptchaform"' in low) or ('name="captcha-response"' in low)


def _pass_kcaptcha_gate(
    fetcher: Fetcher,
    html: str,
    page_url: str,
    captcha_solver: CaptchaSolver,
) -> CaseSearchResult | None:
    """Решает картинку /captcha.php и POST captcha-response. None = прошли gate."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    form = soup.find("form", id="kcaptchaForm") or soup.find("form", attrs={"id": lambda v: v and "captcha" in v.lower()})
    if form is None:
        return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу, но форма kcaptcha не найдена.",
        )
    img = form.find("img")
    if img is None or not img.get("src"):
        return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу, но картинка не найдена.",
        )
    image_url = urljoin(page_url, img["src"])
    image_bytes = fetcher.get_bytes(image_url)
    if not image_bytes:
        return CaseSearchResult("captcha_failed", f"Не удалось скачать капчу: {image_url}")
    try:
        code = captcha_solver.solve(image_bytes)
    except Exception as exc:  # noqa: BLE001 — ошибка внешнего API
        return CaseSearchResult("captcha_failed", f"2captcha: {exc}")
    if not code:
        return CaseSearchResult("captcha_failed", "2captcha вернул пустой код.")

    action = form.get("action") or page_url
    post_url = urljoin(page_url, action)
    data = {"captcha-response": code.strip()}
    # скрытые поля, если появятся
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name and name != "captcha-response" and inp.get("type") != "submit":
            data[name] = inp.get("value") or ""

    posted = fetcher.post(post_url, data=data, respect_robots=False)
    if posted.blocked:
        return CaseSearchResult("blocked", "Сайт суда заблокировал запрос после капчи.")
    if not posted.ok or not posted.html:
        return CaseSearchResult("captcha_failed", f"POST капчи не удался: {posted.error}")
    if _looks_captcha_gate(posted.html):
        return CaseSearchResult("captcha_failed", "Капча не принята сайтом (повторный gate).")
    return None
'''

OLD_DIRECT_SIG = '''def search_case_direct(
    fetcher: Fetcher,
    domain: str,
    query: CaseQuery,
    production_type: str = "civil_first_instance",
) -> CaseSearchResult:
'''

NEW_DIRECT_SIG = '''def search_case_direct(
    fetcher: Fetcher,
    domain: str,
    query: CaseQuery,
    production_type: str = "civil_first_instance",
    captcha_solver: Optional[CaptchaSolver] = None,
    max_captcha_attempts: int = 2,
) -> CaseSearchResult:
'''

OLD_GATE = '''    html = fetch_result.html
    low = (html or "").lower()
    if "временно недоступна" in low or "приносим свои извинения" in low:
        return CaseSearchResult(
            "error",
            "Информация временно недоступна на сайте суда. Попробуйте позже или обратитесь в суд напрямую.",
        )
    if ("дополнительную проверку" in low and "captcha" in low) or (
        "для продолжения необходимо пройти" in low
    ):
        return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу (типично для мировых судей). Нужен ключ 2captcha или ручной обход.",
        )
    if looks_like_not_found(html):
'''

NEW_GATE = '''    html = fetch_result.html
    page_url = fetch_result.url or search_url
    low = (html or "").lower()
    if "временно недоступна" in low or "приносим свои извинения" in low:
        return CaseSearchResult(
            "error",
            "Информация временно недоступна на сайте суда. Попробуйте позже или обратитесь в суд напрямую.",
        )
    if _looks_captcha_gate(html):
        if captcha_solver is None:
            return CaseSearchResult(
                "captcha_required",
                "Сайт суда показывает капчу (типично для мировых судей). Нужен ключ 2captcha (TWOCAPTCHA_API_KEY).",
            )
        last_cap = None
        for _attempt in range(max(1, max_captcha_attempts)):
            gate_err = _pass_kcaptcha_gate(fetcher, html, page_url, captcha_solver)
            if gate_err is not None:
                last_cap = gate_err
                if gate_err.status == "captcha_failed":
                    # новая картинка — перезагрузим поиск
                    fetch_result = fetcher.request("GET", search_url, params=params, respect_robots=False)
                    if not fetch_result.ok or not fetch_result.html:
                        return last_cap
                    html = fetch_result.html
                    page_url = fetch_result.url or search_url
                    if not _looks_captcha_gate(html):
                        break
                    continue
                return gate_err
            # gate пройден — повторяем поиск в той же сессии (cookies)
            fetch_result = fetcher.request("GET", search_url, params=params, respect_robots=False)
            if not fetch_result.ok or not fetch_result.html:
                return CaseSearchResult(
                    "error",
                    "После капчи сайт суда не ответил. Попробуйте ещё раз.",
                )
            html = fetch_result.html
            page_url = fetch_result.url or search_url
            if _looks_captcha_gate(html):
                last_cap = CaseSearchResult("captcha_failed", "После решения снова gate-капча.")
                continue
            break
        else:
            return last_cap or CaseSearchResult(
                "captcha_failed",
                "Не удалось пройти капчу за отведённые попытки.",
            )
        if _looks_captcha_gate(html):
            return last_cap or CaseSearchResult(
                "captcha_required",
                "Сайт суда показывает капчу (типично для мировых судей).",
            )
    if looks_like_not_found(html):
'''

DELO_HELPER = '''
def _captcha_solver_from_env():
    key = (os.environ.get("TWOCAPTCHA_API_KEY") or "").strip()
    if not key:
        return None
    try:
        from scraper.case_lookup.captcha import TwoCaptchaSolver
        return TwoCaptchaSolver(key)
    except Exception as exc:  # noqa: BLE001
        log.warning("2captcha init failed: %s", exc)
        return None
'''

OLD_CASE_CALL = '''        result = search_case_direct(
            fetcher,
            domain,
            query,
            production_type=production_type,
        )
'''

NEW_CASE_CALL = '''        result = search_case_direct(
            fetcher,
            domain,
            query,
            production_type=production_type,
            captcha_solver=_captcha_solver_from_env(),
        )
'''

# Also allow direct (no proxy) when proxy list empty — VPS has RU IP
OLD_CHANNELS = '''    channels = _ordered_proxies()[:4]
    last_result = None
    used = ""
    t_budget = time.monotonic() + 150.0
    for channel in channels:
'''

NEW_CHANNELS = '''    channels = _ordered_proxies()[:4] or [""]
    last_result = None
    used = ""
    t_budget = time.monotonic() + 150.0
    for channel in channels:
'''

OLD_FETCHER = '''        fetcher = Fetcher(
            proxy_urls=[channel],
            delay_range=(0.0, 0.0),
            timeout=timeout,
            max_retries=1,
        )
'''

NEW_FETCHER = '''        fetcher = Fetcher(
            proxy_urls=[channel] if channel else [],
            delay_range=(0.0, 0.0),
            timeout=timeout,
            max_retries=1,
        )
'''


def patch_search(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "_pass_kcaptcha_gate" in text and "captcha_solver: Optional[CaptchaSolver]" in text:
        print("search.py already patched for kcaptcha")
        return
    # Insert helpers before search_case_direct
    if "_looks_captcha_gate" not in text:
        if OLD_DIRECT_SIG not in text:
            raise SystemExit("search_case_direct signature not found")
        text = text.replace(OLD_DIRECT_SIG, SEARCH_HELPERS + "\n" + NEW_DIRECT_SIG, 1)
    elif OLD_DIRECT_SIG in text:
        text = text.replace(OLD_DIRECT_SIG, NEW_DIRECT_SIG, 1)

    if OLD_GATE not in text:
        if "TWOCAPTCHA_API_KEY" in text and "_pass_kcaptcha_gate" in text:
            print("gate block already new?")
        else:
            raise SystemExit("captcha gate block not found in search.py")
    else:
        text = text.replace(OLD_GATE, NEW_GATE, 1)

    # Fix CaseSearchResult | None for py3.9 if needed — VPS is 3.12, OK
    # Need Fetcher import in type hints - Fetcher already used in module via runtime
    if "from scraper.fetch import Fetcher" not in text and "Fetcher" in SEARCH_HELPERS:
        # Fetcher is used as parameter type - check if imported
        if "Fetcher" not in text.split("def search_case")[0]:
            # search.py uses Fetcher without importing in annotations - it's passed in
            pass

    path.write_text(text, encoding="utf-8")
    print("search.py patched")


def patch_delo(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "_captcha_solver_from_env" not in text:
        marker = "def _case_with_channels(domain: str, query: CaseQuery, production_type: str):"
        if marker not in text:
            raise SystemExit("_case_with_channels not found")
        text = text.replace(marker, DELO_HELPER + "\n" + marker, 1)
    if OLD_CASE_CALL in text:
        text = text.replace(OLD_CASE_CALL, NEW_CASE_CALL, 1)
    elif "captcha_solver=_captcha_solver_from_env()" in text:
        print("delo already passes captcha_solver")
    else:
        raise SystemExit("search_case_direct call block not found")
    if OLD_CHANNELS in text:
        text = text.replace(OLD_CHANNELS, NEW_CHANNELS, 1)
    if OLD_FETCHER in text:
        text = text.replace(OLD_FETCHER, NEW_FETCHER, 1)
    path.write_text(text, encoding="utf-8")
    print("delo_app patched")


if __name__ == "__main__":
    patch_search(Path("/opt/bitrix-delo/scraper/case_lookup/search.py"))
    patch_delo(Path("/opt/bitrix-delo/api/delo_app.py"))
