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


def test_not_found_voronezh_wording():
    html = "<html><body><p>Данных по запросу не обнаружено.</p><p>Уточните критерии поиска.</p></body></html>"
    assert looks_like_not_found(html)


RESULT_HTML_LIST = """
<html><body>
<div id="content">
<p>Всего по запросу найдено — 1.</p>
<table id="tablcont">
<tr><th>№ дела</th><th>Дата поступления</th><th>Судья</th></tr>
<tr>
  <td><a href="/modules.php?name=sud_delo&name_op=case&case_id=1">2-10/2026</a></td>
  <td>01.02.2026</td>
  <td>Петров П.П.</td>
</tr>
</table>
</div>
</body></html>
"""


def test_parses_search_hit_table():
    from scraper.case_lookup.case_card import parse_search_hits
    cards = parse_search_hits(RESULT_HTML_LIST, "https://example--vrn.sudrf.ru/modules.php")
    assert len(cards) == 1
    assert cards[0].case_number == "2-10/2026"
    assert "name_op=case" in (cards[0].case_url or "")
    assert {"Судья": "Петров П.П."} in cards[0].sections["РЕЗУЛЬТАТ ПОИСКА"]


def test_not_found_voronezh_wording():
    html = "<html><body><p>Данных по запросу не обнаружено.</p><p>Уточните критерии поиска.</p></body></html>"
    assert looks_like_not_found(html)


def test_wrong_captcha_detection():
    assert looks_like_wrong_captcha(RESULT_HTML_WRONG_CAPTCHA)
    assert not looks_like_wrong_captcha(RESULT_HTML_ONE_CASE)
