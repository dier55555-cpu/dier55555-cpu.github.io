"""Оффлайн-тесты парсера и краулера на локальных HTML-фикстурах.

Реальные сайты sudrf.ru недоступны из большинства облачных/зарубежных сред —
их F5 BigIP WAF обрывает TLS-хендшейк для таких IP (проверено вручную).
Поэтому тесты поднимают локальный HTTP-сервер с HTML, имитирующим типовую
вёрстку ГАС «Правосудие», и гоняют через него весь пайплайн:
fetch -> parse -> crawl -> kb_builder -> search.
"""

from __future__ import annotations

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sudrf_scraper.config import Court
from sudrf_scraper.crawler import crawl_court
from sudrf_scraper.fetch import build_session
from sudrf_scraper.kb_builder import build_index, build_markdown_kb, save_raw_dump
from sudrf_scraper.parse import extract_contacts, parse_page
from sudrf_scraper.search import CourtKnowledgeBase

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def start_fixture_server() -> tuple[http.server.HTTPServer, int]:
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(FIXTURES_DIR), **kw
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def test_parse_page_extracts_title_text_links():
    html = (FIXTURES_DIR / "index.html").read_text(encoding="utf-8")
    page = parse_page("http://example.test/", html)
    assert "Советский районный суд" in page.title
    assert "Прием граждан" in page.text or "прием" in page.text.lower()
    assert any("contacts.html" in link for link in page.links)


def test_extract_contacts_finds_phone_and_email():
    text = "Телефон приемной: 8 (473) 123-45-67, email: info@example.test"
    contacts = extract_contacts(text)
    assert contacts["phones"]
    assert "info@example.test" in contacts["emails"]


def test_crawl_and_build_kb(tmp_path):
    server, port = start_fixture_server()
    try:
        base_url = f"http://127.0.0.1:{port}/index.html"
        court = Court(slug="test-court", name="Тестовый районный суд", url=base_url)
        session = build_session()

        dump = crawl_court(court, session, max_pages=10, max_depth=2, delay=0)
        assert len(dump.pages) >= 3
        assert dump.contacts["phones"]

        data_dir = tmp_path / "data"
        output_dir = tmp_path / "output"
        save_raw_dump(dump, data_dir=data_dir)
        build_markdown_kb(dump, output_dir=output_dir)
        build_index([dump], output_dir=output_dir)

        assert (data_dir / "test-court.json").exists()
        assert (output_dir / "test-court" / "_all.md").exists()
        assert (output_dir / "index.json").exists()

        kb = CourtKnowledgeBase(data_dir)
        courts = kb.list_courts()
        assert courts and courts[0]["slug"] == "test-court"

        hits = kb.search("реквизиты госпошлины")
        assert hits
        assert any("реквизит" in h.snippet.lower() or "реквизит" in h.title.lower() for h in hits)
    finally:
        server.shutdown()


if __name__ == "__main__":
    test_parse_page_extracts_title_text_links()
    test_extract_contacts_finds_phone_and_email()
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_crawl_and_build_kb(Path(td))
    print("OK: все проверки пройдены")
