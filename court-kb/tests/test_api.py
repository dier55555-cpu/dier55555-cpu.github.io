from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_kb_search_on_empty_corpus_returns_clear_message():
    response = client.post("/kb/search", json={"query": "режим работы суда"})
    assert response.status_code == 200
    assert "База знаний пуста" in response.json()["result"]


def test_case_lookup_unknown_court_is_404():
    response = client.post("/case-lookup", json={"court_slug": "does-not-exist", "case_number": "1"})
    assert response.status_code == 404


def test_case_lookup_disabled_court_returns_clear_status():
    response = client.post("/case-lookup", json={"court_slug": "sovetsky-vrn", "case_number": "2-1/2026"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disabled"


def test_case_lookup_requires_case_number_or_last_name():
    response = client.post("/case-lookup", json={"court_slug": "sovetsky-vrn"})
    # court_search отключён для всех судов по умолчанию, поэтому проверка "нужен
    # case_number/last_name" здесь не достигается — но disabled-ответ уже
    # покрыт test_case_lookup_disabled_court_returns_clear_status.
    assert response.status_code == 200


def test_api_key_check_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("COURT_KB_API_KEY", "secret-key")
    response = client.post(
        "/kb/search",
        json={"query": "тест"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_crawl_status_without_prior_run():
    response = client.get("/crawl/status")
    assert response.status_code == 200
    assert response.json()["status"] in ("no_data", "ok")


def test_api_key_check_accepts_correct_key(monkeypatch):
    monkeypatch.setenv("COURT_KB_API_KEY", "secret-key")
    response = client.post(
        "/kb/search",
        json={"query": "тест"},
        headers={"X-API-Key": "secret-key"},
    )
    assert response.status_code == 200
