#!/usr/bin/env python3
"""Проверка COURT_KB_PROXY / sticky-портов до запуска job.

Что ловим:
  - 407 = неверный логин/пароль или отключённый аккаунт proxy.market
  - все порты мёртвые = нельзя идти в DRY_RUN / прод
  - рассинхрон COURT_KB_PROXY vs .env.proxy

Запуск на VPS:
  /opt/saprin/venv/bin/python /opt/saprin/job/probe_proxy.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
PARSER_ENV = Path("/opt/saprin/parser/.env")
JOB_PROXY_ENV = Path("/opt/saprin/job/.env.proxy")
LOCAL_PARSER_ENV = ROOT.parent / "parser" / ".env"


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def _mask_user(url: str) -> str:
    p = urlparse(url)
    user = p.username or "?"
    return f"{user[:2]}***@{p.hostname}:{p.port}"


def main() -> int:
    # Порядок как у systemd: сначала .env.proxy, потом parser/.env (побеждает).
    for path in (JOB_PROXY_ENV, PARSER_ENV, LOCAL_PARSER_ENV, ROOT / ".env"):
        _load_env(path)

    sys.path.insert(0, str(ROOT.parent / "parser"))
    sys.path.insert(0, "/opt/saprin/parser")
    from scraper.proxy_pool import proxies_from_env  # noqa: WPS433

    urls = proxies_from_env()
    if not urls:
        print("FAIL: COURT_KB_PROXY пуст — парсер уйдёт в direct (VPS IP часто режется sudrf)")
        return 2

    print(f"pool_size={len(urls)} sample={_mask_user(urls[0])}")
    court_kb = os.environ.get("COURT_KB_PROXY", "")
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or ""
    if court_kb and http_proxy:
        u1 = urlparse(court_kb).username
        u2 = urlparse(http_proxy).username
        if u1 and u2 and u1 != u2:
            print(
                f"WARN: разные логины COURT_KB_PROXY={u1[:2]}*** "
                f"vs HTTP_PROXY={u2[:2]}*** — источник истины COURT_KB_PROXY"
            )

    auth_ok = 0
    auth_407 = 0
    sudrf_ok = 0
    # ipify на всех портах; sudrf — на первых 4 (дорого по времени)
    sudrf_ports = {urlparse(u).port for u in urls[:4]}

    for url in urls:
        port = urlparse(url).port
        proxies = {"http": url, "https": url}
        try:
            r = requests.get("https://api.ipify.org", proxies=proxies, timeout=12)
            if r.status_code == 200 and r.text.strip():
                auth_ok += 1
                ip = r.text.strip()
                print(f"  port={port} ipify=ok egress={ip}")
            else:
                print(f"  port={port} ipify=http_{r.status_code}")
        except requests.RequestException as exc:
            msg = str(exc)
            if "407" in msg:
                auth_407 += 1
                print(f"  port={port} ipify=407 AUTH FAIL")
            else:
                print(f"  port={port} ipify=ERR {msg[:100]}")
            continue

        if port not in sudrf_ports:
            continue
        try:
            r2 = requests.get(
                "https://sovetsky--vrn.sudrf.ru/modules.php?name=sud_delo",
                proxies=proxies,
                timeout=25,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True,
            )
            if r2.status_code == 200 and len(r2.content) > 1000:
                sudrf_ok += 1
                print(f"  port={port} sudrf=ok bytes={len(r2.content)}")
            else:
                print(f"  port={port} sudrf=http_{r2.status_code} bytes={len(r2.content)}")
        except requests.RequestException as exc:
            print(f"  port={port} sudrf=ERR {str(exc)[:100]}")

    print(f"summary auth_ok={auth_ok}/{len(urls)} auth_407={auth_407} sudrf_ok={sudrf_ok}")

    if auth_407 and auth_ok == 0:
        print("FAIL: 407 на всех портах — проверь логин/пароль в кабинете proxy.market")
        print("      и что COURT_KB_PROXY в /opt/saprin/parser/.env совпадает с живым аккаунтом")
        return 1
    if auth_ok == 0:
        print("FAIL: ни один sticky-порт не отвечает (ipify)")
        return 1
    if sudrf_ok == 0:
        print("FAIL: auth есть, но sudrf modules не открылся ни с одного из пробных портов")
        return 2
    print("OK: прокси живой, sudrf доступен хотя бы с одного sticky-порта")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
