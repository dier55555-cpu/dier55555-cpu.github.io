from sudrf_kb.kb_builder import court_dict_to_markdown

SAMPLE_COURT = {
    "court_id": "sovetsky",
    "name": "Советский районный суд г. Воронежа",
    "base_url": "https://sovetsky--vrn.sudrf.ru/",
    "errors": [],
    "pages": [
        {
            "url": "https://sovetsky--vrn.sudrf.ru/contacts",
            "title": "Контакты",
            "category": "contacts",
            "text": "Адрес: г. Воронеж, ул. Театральная, д. 30",
        },
        {
            "url": "https://sovetsky--vrn.sudrf.ru/news/1",
            "title": "Новость 1",
            "category": "news",
            "text": "Суд объявляет о переносе заседаний.",
        },
    ],
}


def test_court_dict_to_markdown_groups_by_category():
    markdown = court_dict_to_markdown(SAMPLE_COURT)

    assert "# Советский районный суд г. Воронежа" in markdown
    assert "## Контакты и реквизиты" in markdown
    assert "## Новости и объявления" in markdown
    assert "Театральная" in markdown
    assert "переносе заседаний" in markdown


def test_court_dict_to_markdown_includes_errors_section_when_present():
    court = dict(SAMPLE_COURT, errors=["https://example.com: заблокирован WAF"])
    markdown = court_dict_to_markdown(court)

    assert "## Ошибки при обходе" in markdown
    assert "заблокирован WAF" in markdown
