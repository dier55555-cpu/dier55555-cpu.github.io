from scraper.proxy_pool import (
    expand_ports,
    is_proxy_failure,
    parse_ports,
    parse_proxy_list,
    proxies_from_env,
    with_port,
)
from scraper.fetch import Fetcher
import requests


BASE = "http://user:pass@pool.proxy.market:10000"


def test_parse_proxy_list_comma_and_semicolon():
    assert parse_proxy_list("http://a:1@h:1, http://b:2@h:2") == [
        "http://a:1@h:1",
        "http://b:2@h:2",
    ]
    assert parse_proxy_list("http://a:1@h:1; http://b:2@h:2") == [
        "http://a:1@h:1",
        "http://b:2@h:2",
    ]
    assert parse_proxy_list("") == []
    assert parse_proxy_list(None) == []


def test_parse_ports_range_and_list():
    assert parse_ports("10001-10003") == [10001, 10002, 10003]
    assert parse_ports("10001,10006,10002") == [10001, 10006, 10002]


def test_expand_ports_keeps_userinfo():
    urls = expand_ports(BASE, [10001, 10002])
    assert urls == [
        "http://user:pass@pool.proxy.market:10001",
        "http://user:pass@pool.proxy.market:10002",
    ]
    assert with_port(BASE, 10005).endswith(":10005")


def test_proxies_from_env_expands_ports(monkeypatch):
    monkeypatch.setenv("COURT_KB_PROXY", BASE)
    monkeypatch.setenv("COURT_KB_PROXY_PORTS", "10001-10003")
    urls = proxies_from_env()
    assert [u.endswith(str(p)) for u, p in zip(urls, (10001, 10002, 10003))]
    assert len(urls) == 3


def test_is_proxy_failure_detects_sudrf_503():
    assert is_proxy_failure("ProxyError Tunnel connection failed: 503 Node has rejected the request")
    assert is_proxy_failure("HTTPSConnectionPool Read timed out")
    assert not is_proxy_failure("HTTP 404")


def test_fetcher_rotates_proxy_on_503(monkeypatch):
    urls = expand_ports(BASE, [10001, 10002])
    calls = []

    def fake_request(self, method, url, **kwargs):
        calls.append(kwargs.get("proxies"))
        if len(calls) == 1:
            raise requests.exceptions.ProxyError("503 Node has rejected the request")
        class Resp:
            status_code = 200
            encoding = "utf-8"
            content = b"<html>ok</html>"
        return Resp()

    monkeypatch.setattr(requests.Session, "request", fake_request)
    fetcher = Fetcher(proxy_urls=urls, delay_range=(0, 0), timeout=2, max_retries=2)
    result = fetcher.get("https://sovetsky--vrn.sudrf.ru/", respect_robots=False)
    assert result.ok
    assert calls[0]["https"].endswith(":10001")
    assert calls[1]["https"].endswith(":10002")
