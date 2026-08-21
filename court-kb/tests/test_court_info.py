"""Unit tests for court website → origin and topic extraction (no network)."""

from scraper.court_info import (
    _extract_topic_block,
    normalize_topic,
    website_to_origin,
)


def test_website_to_origin_public_to_service():
    assert website_to_origin("http://oktyabrsky.stv.sudrf.ru") == "https://oktyabrsky--stv.sudrf.ru"
    assert website_to_origin("https://oktyabrsky--stv.sudrf.ru/") == "https://oktyabrsky--stv.sudrf.ru"
    assert website_to_origin("kominternovsky--vrn.sudrf.ru") == "https://kominternovsky--vrn.sudrf.ru"


def test_normalize_topic_aliases():
    assert normalize_topic("режим работы") == "hours"
    assert normalize_topic("телефон канцелярии") == "contacts"
    assert normalize_topic("госпошлина") == "duty"
    assert normalize_topic("подсудность") == "jurisdiction"


def test_extract_hours_block_from_information_page():
    html = """
    <html><body>
    <a href="/x">О СУДЕ</a>
    <div>График приема исковых заявлений: Понедельник - четверг с 08:30 до 16:00</div>
    <div>
    Режим работы Октябрьского районного суда г. Ставрополя
    Понедельник - четверг с 08:30 до 17:15 (обеденный перерыв с 13:00 до 13:42)
    Пятница с 08:30 до 17:00
    Суббота – выходной
    Воскресенье - выходной
    Режим работы отделов
    Общественная приемная Понедельник - четверг с 08:30 до 16:00 71-58-98
    </div>
    <div>Опубликовано 29.10.2025</div>
    <div>О СУДЕ СУДЕЙСКОЕ СООБЩЕСТВО НОРМАТИВНЫЕ АКТЫ</div>
    </body></html>
    """
    text = _extract_topic_block(html, "hours")
    assert "17:15" in text
    assert "Понедельник" in text or "понедельник" in text.lower()
    assert "СУДЕЙСКОЕ СООБЩЕСТВО" not in text
