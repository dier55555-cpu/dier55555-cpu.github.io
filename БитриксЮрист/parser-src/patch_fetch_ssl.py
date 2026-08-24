"""Патч Fetcher: для *.msudrf.ru отключаем проверку SSL (сертификат на sudrf.ru)."""

from __future__ import annotations

from pathlib import Path


def patch_fetch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "def _ssl_verify_for(url" in text:
        print("fetch.py already patched")
        return

    needle = "    def _current_proxies(self) -> Optional[dict]:"
    helper = '''    @staticmethod
    def _ssl_verify_for(url: str) -> bool:
        """Мировые судьи (*.msudrf.ru) отдают сертификат sudrf.ru → hostname mismatch."""
        host = (urlparse(url).hostname or "").lower()
        return not host.endswith(".msudrf.ru")

    def _current_proxies(self) -> Optional[dict]:
'''
    if needle not in text:
        raise SystemExit("anchor _current_proxies not found")
    text = text.replace(needle, helper, 1)

    # inject verify= into session.request and session.get calls inside Fetcher
    old_req = """                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers={"User-Agent": self.user_agent, **BROWSER_LIKE_HEADERS},
                    proxies=self._current_proxies(),
                    timeout=self.timeout,
                )"""
    new_req = """                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers={"User-Agent": self.user_agent, **BROWSER_LIKE_HEADERS},
                    proxies=self._current_proxies(),
                    timeout=self.timeout,
                    verify=self._ssl_verify_for(url),
                )"""
    if old_req not in text:
        raise SystemExit("session.request block not found")
    text = text.replace(old_req, new_req, 1)

    old_get = """            resp = self.session.get(
                url,
                headers={"User-Agent": self.user_agent, **BROWSER_LIKE_HEADERS},
                proxies=self._current_proxies(),
                timeout=self.timeout,
            )"""
    new_get = """            resp = self.session.get(
                url,
                headers={"User-Agent": self.user_agent, **BROWSER_LIKE_HEADERS},
                proxies=self._current_proxies(),
                timeout=self.timeout,
                verify=self._ssl_verify_for(url),
            )"""
    if old_get in text:
        text = text.replace(old_get, new_get, 1)

    path.write_text(text, encoding="utf-8")
    print("fetch.py patched for msudrf SSL")


if __name__ == "__main__":
    patch_fetch(Path("/opt/bitrix-delo/scraper/fetch.py"))
