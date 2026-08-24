"""Патч: msudrf kcaptcha gate через 2captcha с POST в windows-1251."""

from __future__ import annotations

from pathlib import Path

NEW_PASS = r'''
def _looks_captcha_gate(html: str) -> bool:
    low = (html or "").lower()
    return ("дополнительную проверку" in low and "captcha" in low) or (
        "для продолжения необходимо пройти" in low
    ) or ('id="kcaptchaform"' in low) or ('name="captcha-response"' in low)


def _pass_kcaptcha_gate(
    fetcher: "Fetcher",
    html: str,
    page_url: str,
    captcha_solver: CaptchaSolver,
) -> CaseSearchResult | None:
    """Решает /captcha.php и POST captcha-response (windows-1251). None = ok."""
    from urllib.parse import urljoin, urlparse, urlencode

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    form = soup.find("form", id="kcaptchaForm") or soup.find(
        "form", attrs={"id": lambda v: v and "captcha" in str(v).lower()}
    )
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
        # fallback без обёртки
        try:
            resp_img = fetcher.session.get(
                image_url,
                headers={"User-Agent": fetcher.user_agent, "Referer": page_url},
                proxies=fetcher._current_proxies(),
                timeout=fetcher.timeout,
                verify=fetcher._ssl_verify_for(image_url),
            )
            image_bytes = resp_img.content if resp_img.status_code == 200 else None
        except Exception:
            image_bytes = None
    if not image_bytes:
        return CaseSearchResult("captcha_failed", f"Не удалось скачать капчу: {image_url}")
    try:
        code = captcha_solver.solve(image_bytes)
    except Exception as exc:  # noqa: BLE001
        return CaseSearchResult("captcha_failed", f"2captcha: {exc}")
    if not code:
        return CaseSearchResult("captcha_failed", "2captcha вернул пустой код.")

    action = form.get("action") or page_url
    post_url = urljoin(page_url, action)
    # Без query-string POST на /modules.php даёт 404 — сохраняем полный URL страницы.
    if not (form.get("action") or "").strip():
        post_url = page_url
    fields = {"captcha-response": code.strip()}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name and name != "captcha-response" and inp.get("type") != "submit":
            fields[name] = inp.get("value") or ""
    # Критично: документ charset=windows-1251 — UTF-8 тело молча отклоняется.
    body = urlencode(fields, encoding="cp1251").encode("ascii")
    parsed = urlparse(page_url)
    try:
        resp = fetcher.session.post(
            post_url,
            data=body,
            headers={
                "User-Agent": fetcher.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": page_url,
                "Origin": f"{parsed.scheme}://{parsed.netloc}",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
            proxies=fetcher._current_proxies(),
            timeout=fetcher.timeout,
            verify=fetcher._ssl_verify_for(post_url),
            allow_redirects=True,
        )
    except Exception as exc:  # noqa: BLE001
        return CaseSearchResult("captcha_failed", f"POST капчи не удался: {exc}")
    html_out = ""
    try:
        html_out = resp.content.decode("cp1251", errors="replace")
    except Exception:
        html_out = resp.text or ""
    if _looks_captcha_gate(html_out):
        return CaseSearchResult("captcha_failed", "Капча не принята сайтом (повторный gate).")
    return None

'''


def patch_search(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find("def _looks_captcha_gate")
    end = text.find("def search_case_direct")
    if start < 0 or end < 0:
        raise SystemExit("markers not found")
    text = text[:start] + NEW_PASS + "\n" + text[end:]

    # search_case_direct: use full URL with query (params in URL) so captcha POST keeps query
    old_req = '''    search_url = f"https://{domain}/modules.php"
    fetch_result = fetcher.request("GET", search_url, params=params, respect_robots=False)
'''
    new_req = '''    from urllib.parse import urlencode as _urlencode
    search_url = f"https://{domain}/modules.php?{_urlencode(params)}"
    fetch_result = fetcher.request("GET", search_url, respect_robots=False)
'''
    if old_req in text:
        text = text.replace(old_req, new_req, 1)
    # also fix retries inside captcha loop that still use params=
    text = text.replace(
        'fetch_result = fetcher.request("GET", search_url, params=params, respect_robots=False)',
        'fetch_result = fetcher.request("GET", search_url, respect_robots=False)',
    )
    path.write_text(text, encoding="utf-8")
    print("search.py updated")


def patch_captcha_solver(path: Path) -> None:
    path.write_text(
        '''"""Решатели капчи для формы поиска дела."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from pathlib import Path


class CaptchaSolver(ABC):
    @abstractmethod
    def solve(self, image_bytes: bytes) -> str:
        """Возвращает распознанный текст капчи."""


class TwoCaptchaSolver(CaptchaSolver):
    """Обёртка над 2captcha/rucaptcha. Нужен `pip install 2captcha-python`."""

    def __init__(self, api_key: str, timeout: int = 90):
        from twocaptcha import TwoCaptcha

        self._solver = TwoCaptcha(api_key)
        self._timeout = timeout

    def solve(self, image_bytes: bytes) -> str:
        if not image_bytes:
            raise ValueError("пустая картинка капчи")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        # language=1 — кириллица (msudrf kcaptcha)
        result = self._solver.normal(
            b64,
            timeout=self._timeout,
            lang="ru",
            language=1,
            minLen=4,
            maxLen=8,
        )
        code = result["code"] if isinstance(result, dict) else str(result)
        return code.strip()


class ManualCaptchaSolver(CaptchaSolver):
    def __init__(self, save_dir: Path = Path("data/captcha")):
        self.save_dir = save_dir
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def solve(self, image_bytes: bytes) -> str:
        path = self.save_dir / "captcha.png"
        path.write_bytes(image_bytes)
        print(f"Капча сохранена в {path}. Откройте файл и введите код:")
        return input("Код капчи: ").strip()
''',
        encoding="utf-8",
    )
    print("captcha.py updated")


if __name__ == "__main__":
    root = Path("/opt/bitrix-delo")
    patch_search(root / "scraper/case_lookup/search.py")
    patch_captcha_solver(root / "scraper/case_lookup/captcha.py")
