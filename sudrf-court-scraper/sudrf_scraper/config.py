from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_COURTS_FILE = PACKAGE_DIR / "courts.json"
DEFAULT_DATA_DIR = PACKAGE_DIR / "data"
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "output"

# Сайты sudrf.ru блокируют запросы с зарубежных / датацентровых IP на уровне
# TLS-хендшейка (F5 BigIP WAF сбрасывает соединение). Поэтому скрипт нужно
# запускать с сервера/прокси с российским IP. Адрес прокси можно указать
# через переменную окружения SUDRF_PROXY или аргумент --proxy у CLI.
PROXY_ENV_VAR = "SUDRF_PROXY"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


@dataclass(frozen=True)
class Court:
    slug: str
    name: str
    url: str


def load_courts(path: os.PathLike | str = DEFAULT_COURTS_FILE) -> list[Court]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [Court(slug=item["slug"], name=item["name"], url=item["url"]) for item in raw]


def get_proxy_from_env() -> str | None:
    return os.environ.get(PROXY_ENV_VAR) or None
