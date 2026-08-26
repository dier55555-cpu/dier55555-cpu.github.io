"""Fix: use HTML from successful kcaptcha POST (often already search results)."""

from __future__ import annotations

import re
from pathlib import Path


HELPER = '''
def _looks_like_search_form_only(html: str) -> bool:
    """Форма поиска без таблицы результатов (частый ответ msudrf после «пустого» GET)."""
    if "case_id=" in (html or ""):
        return False
    return "bookmark_type_1" in (html or "") or "g1_case__CASE_NUMBERSS" in (html or "")


'''


def patch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    if "_looks_like_search_form_only" not in text:
        text = text.replace("def _looks_captcha_gate", HELPER + "def _looks_captcha_gate", 1)

    # Change return type and success return of _pass_kcaptcha_gate
    text = text.replace(
        ') -> CaseSearchResult | None:\n    """Решает /captcha.php и POST captcha-response (windows-1251). None = ok."""',
        ') -> tuple[CaseSearchResult | None, str | None]:\n    """Решает /captcha.php и POST captcha-response (windows-1251).\n\n    Returns (error, html_after). On success html_after is POST body (часто уже результаты).\n    """',
        1,
    )

    start = text.find("def _pass_kcaptcha_gate")
    end = text.find("\ndef search_case_direct")
    if start < 0 or end < 0:
        raise SystemExit("function bounds not found")
    fn = text[start:end]

    # Every error return becomes (result, None); final success (None, html_out)
    fn2 = fn
    # simple replacements for return CaseSearchResult(...) that are single-line
    fn2 = re.sub(
        r'return CaseSearchResult\("captcha_failed", f"Не удалось скачать капчу: \{image_url\}"\)',
        r'return CaseSearchResult("captcha_failed", f"Не удалось скачать капчу: {image_url}"), None',
        fn2,
    )
    fn2 = re.sub(
        r'return CaseSearchResult\("captcha_failed", f"2captcha: \{exc\}"\)',
        r'return CaseSearchResult("captcha_failed", f"2captcha: {exc}"), None',
        fn2,
    )
    fn2 = fn2.replace(
        'return CaseSearchResult("captcha_failed", "2captcha вернул пустой код.")',
        'return CaseSearchResult("captcha_failed", "2captcha вернул пустой код."), None',
    )
    fn2 = re.sub(
        r'return CaseSearchResult\("captcha_failed", f"POST капчи не удался: \{exc\}"\)',
        r'return CaseSearchResult("captcha_failed", f"POST капчи не удался: {exc}"), None',
        fn2,
    )
    fn2 = fn2.replace(
        'return CaseSearchResult("captcha_failed", "Капча не принята сайтом (повторный gate).")',
        'return CaseSearchResult("captcha_failed", "Капча не принята сайтом (повторный gate)."), None',
    )

    # multiline captcha_required returns
    fn2 = fn2.replace(
        '''return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу, но форма kcaptcha не найдена.",
        )''',
        '''return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу, но форма kcaptcha не найдена.",
        ), None''',
    )
    fn2 = fn2.replace(
        '''return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу, но картинка не найдена.",
        )''',
        '''return CaseSearchResult(
            "captcha_required",
            "Сайт суда показывает капчу, но картинка не найдена.",
        ), None''',
    )

    # success end
    if "return None, html_out" not in fn2:
        # last `return None` in function
        idx = fn2.rfind("return None")
        if idx < 0:
            raise SystemExit("no final return None")
        fn2 = fn2[:idx] + "return None, html_out" + fn2[idx + len("return None") :]

    text = text[:start] + fn2 + text[end:]

    # Replace captcha loop body
    pattern = re.compile(
        r"        last_cap = None\n"
        r"        for _attempt in range\(max\(1, max_captcha_attempts\)\):.*?,"
        r"\n                \"Сайт суда показывает капчу \(типично для мировых судей\)\.\",\n"
        r"            \)\n",
        re.S,
    )
    new_loop = '''        last_cap = None
        for _attempt in range(max(1, max_captcha_attempts)):
            gate_err, html_after = _pass_kcaptcha_gate(fetcher, html, page_url, captcha_solver)
            if gate_err is not None:
                last_cap = gate_err
                if gate_err.status == "captcha_failed":
                    fetch_result = fetcher.request("GET", search_url, respect_robots=False)
                    if not fetch_result.ok or not fetch_result.html:
                        return last_cap
                    html = fetch_result.html
                    page_url = fetch_result.url or search_url
                    if not _looks_captcha_gate(html):
                        break
                    continue
                return gate_err
            # POST капчи часто уже содержит выдачу — не теряем его вторым GET.
            if html_after and not _looks_captcha_gate(html_after) and (
                "case_id=" in html_after or not _looks_like_search_form_only(html_after)
            ):
                html = html_after
                break
            fetch_result = fetcher.request("GET", search_url, respect_robots=False)
            if not fetch_result.ok or not fetch_result.html:
                if html_after and not _looks_captcha_gate(html_after):
                    html = html_after
                    break
                return CaseSearchResult(
                    "error",
                    "После капчи сайт суда не ответил. Попробуйте ещё раз.",
                )
            html = fetch_result.html
            page_url = fetch_result.url or search_url
            if html_after and "case_id=" in html_after and "case_id=" not in (html or ""):
                html = html_after
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
'''
    m = pattern.search(text)
    if not m:
        i = text.find("last_cap = None")
        raise SystemExit(f"loop not found, context={text[i:i+500]!r}")
    text = text[: m.start()] + new_loop + text[m.end() :]

    # If no captcha but form-only page — force a captcha-bearing reload can't easily.
    # After captcha block / before not_found: if form-only, return clearer error
    needle = "    if looks_like_not_found(html):"
    inject = '''    if _looks_like_search_form_only(html) and "case_id=" not in html:
        return CaseSearchResult(
            "error",
            "Сайт мирового судьи вернул форму поиска без результатов. "
            "Повторите запрос (нужна свежая капча на URL с номером дела).",
        )
    if looks_like_not_found(html):
'''
    if "_looks_like_search_form_only(html) and \"case_id=\"" not in text:
        if needle not in text:
            raise SystemExit("not_found needle missing")
        text = text.replace(needle, inject, 1)

    path.write_text(text, encoding="utf-8")
    print("patched", path)


if __name__ == "__main__":
    patch(Path("/opt/bitrix-delo/scraper/case_lookup/search.py"))
