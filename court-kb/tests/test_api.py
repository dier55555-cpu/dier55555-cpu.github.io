from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_list_courts_returns_six_voronezh_courts():
    response = client.get("/courts")
    assert response.status_code == 200
    slugs = {c["slug"] for c in response.json()["courts"]}
    assert slugs == {
        "sovetsky-vrn",
        "kominternovsky-vrn",
        "zheleznodorozhny-vrn",
        "levoberezhny-vrn",
        "centralny-vrn",
        "lensud-vrn",
    }


def test_list_courts_also_accepts_post():
    response = client.post("/courts")
    assert response.status_code == 200
    assert len(response.json()["courts"]) == 6


def test_corpus_export_empty():
    response = client.get("/corpus/export")
    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["documents"] == []
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_kb_search_on_empty_corpus_returns_clear_message():
    response = client.post("/kb/search", json={"query": "режим работы суда"})
    assert response.status_code == 200
    assert "База знаний пуста" in response.json()["result"]


def test_list_courts_case_search_enabled():
    response = client.get("/courts")
    assert response.status_code == 200
    assert all(c["case_search_enabled"] for c in response.json()["courts"])


def test_delo_unknown_court_is_error_json():
    response = client.post("/delo", json={"court_slug": "does-not-exist", "case_number": "1"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "Неизвестный суд" in body["result"]


def test_delo_requires_case_number_or_last_name():
    response = client.post("/delo", json={"court_slug": "sovetsky-vrn"})
    assert response.status_code == 200
    assert "case_number" in response.json()["result"]
    response = client.post("/case-lookup", json={"court_slug": "does-not-exist", "case_number": "1"})
    assert response.status_code == 404


def test_case_lookup_requires_case_number_or_last_name():
    response = client.post("/case-lookup", json={"court_slug": "sovetsky-vrn"})
    assert response.status_code == 400


def test_case_lookup_returns_search_status(monkeypatch):
    from scraper.case_lookup.search import CaseSearchResult

    def fake_search(*args, **kwargs):
        return CaseSearchResult("not_found", "По заданным критериям дел не найдено.")

    monkeypatch.setattr("api.main.search_case", fake_search)
    response = client.post(
        "/case-lookup",
        json={"court_slug": "sovetsky-vrn", "case_number": "2-1/2026"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_found"
    assert "не найдено" in body["result"]


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


def test_resolve_court_without_directory(monkeypatch, tmp_path):
    monkeypatch.setattr("api.main.DIRECTORY_PATH", tmp_path / "missing.json")
    response = client.post("/courts/resolve", json={"query": "Ленинский район г. Ставрополь"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_directory"
    assert body["matches"] == []


def test_resolve_court_from_local_directory(monkeypatch, tmp_path):
    from scraper.directory.export import write_json
    from scraper.directory.normalize import enrich_court

    records = [
        enrich_court({
            "code": "26RS0002",
            "name": "Ленинский районный суд г. Ставрополя",
            "court_type": "RS",
            "address": "355017, г Ставрополь, ул Ленина, д 219",
            "website": "http://leninsky.stv.sudrf.ru",
        })
    ]
    path = tmp_path / "courts-ru.json"
    write_json(path, records)
    monkeypatch.setattr("api.main.DIRECTORY_PATH", path)
    response = client.post("/courts/resolve", json={"query": "Ленинский район г. Ставрополь"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["matches"][0]["code"] == "26RS0002"
    assert body["matches"][0]["sudrf_domain"] == "leninsky--stv.sudrf.ru"
    assert body["matches"][0]["city"] == "Ставрополь"


def test_api_key_check_accepts_correct_key(monkeypatch):
    monkeypatch.setenv("COURT_KB_API_KEY", "secret-key")
    response = client.post(
        "/kb/search",
        json={"query": "тест"},
        headers={"X-API-Key": "secret-key"},
    )
    assert response.status_code == 200
