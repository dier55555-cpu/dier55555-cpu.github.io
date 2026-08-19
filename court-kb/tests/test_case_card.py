from scraper.case_lookup.case_card import (
    format_case_card,
    looks_like_not_found,
    looks_like_wrong_captcha,
    parse_case_cards,
)

RESULT_HTML_ONE_CASE = """
<html><body>
<table>
<tr><td>ДАННЫЕ ПО ДЕЛУ</td><td></td></tr>
<tr><td>Дата поступления</td><td>01.01.2026</td></tr>
<tr><td>Категория дела</td><td>Гражданское</td></tr>
<tr><td>Судья</td><td>Иванов И.И.</td></tr>
<tr><td>Дата рассмотрения</td><td>15.02.2026</td></tr>
<tr><td>ДВИЖЕНИЕ ДЕЛА</td><td></td></tr>
<tr><td>Наименование события</td><td>Принятие к производству</td></tr>
<tr><td>Дата</td><td>01.01.2026</td></tr>
</table>
</body></html>
"""

RESULT_HTML_NOT_FOUND = """
<html><body><p>По вашему запросу ничего не найдено</p></body></html>
"""

RESULT_HTML_WRONG_CAPTCHA = """
<html><body><p>Неверный код с картинки, попробуйте ещё раз</p></body></html>
"""


def test_parses_sections_and_rows():
    cards = parse_case_cards(RESULT_HTML_ONE_CASE)
    assert len(cards) == 1

    card = cards[0]
    assert set(card.sections.keys()) == {"ДАННЫЕ ПО ДЕЛУ", "ДВИЖЕНИЕ ДЕЛА"}
    assert {"Судья": "Иванов И.И."} in card.sections["ДАННЫЕ ПО ДЕЛУ"]
    assert {"Наименование события": "Принятие к производству"} in card.sections["ДВИЖЕНИЕ ДЕЛА"]


def test_format_case_card_produces_readable_text():
    card = parse_case_cards(RESULT_HTML_ONE_CASE)[0]
    text = format_case_card(card)
    assert "ДАННЫЕ ПО ДЕЛУ" in text
    assert "Судья: Иванов И.И." in text


def test_not_found_detection():
    assert looks_like_not_found(RESULT_HTML_NOT_FOUND)
    assert not looks_like_not_found(RESULT_HTML_ONE_CASE)


def test_wrong_captcha_detection():
    assert looks_like_wrong_captcha(RESULT_HTML_WRONG_CAPTCHA)
    assert not looks_like_wrong_captcha(RESULT_HTML_ONE_CASE)
