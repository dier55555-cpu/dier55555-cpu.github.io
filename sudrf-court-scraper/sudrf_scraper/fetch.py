from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import DEFAULT_HEADERS

logger = logging.getLogger(__name__)


def build_session(proxy: str | None = None) -> requests.Session:
    """Создаёт requests.Session с ретраями и (опционально) прокси.

    sudrf.ru сбрасывает TLS-соединение для IP за пределами РФ, поэтому для
    реального скрапинга почти всегда потребуется proxy с российским IP,
    например: build_session(proxy="http://user:pass@ru-proxy-host:port").
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    retry = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})

    return session


def fetch(session: requests.Session, url: str, timeout: float = 20.0) -> requests.Response | None:
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Не удалось загрузить %s: %s", url, exc)
        return None

    # sudrf.ru отдаёт страницы либо в utf-8, либо в windows-1251; requests
    # иногда угадывает кодировку неверно, поэтому подсказываем через apparent_encoding.
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"

    return resp


def polite_sleep(seconds: float = 1.0) -> None:
    time.sleep(seconds)
