from __future__ import annotations

from pathlib import Path

from scraper.case_lookup.case_card import (
    CaseCard,
    format_case_card,
    format_case_cards,
    parse_case_cards,
)


SAMPLE_HTML = """
<html><body>
<div id="content">
<table>
<tr>
  <td>ДЕЛО</td>
  <td>Уникальный идентификатор дела</td><td>36RS0001-01-2026-000001-00</td>
  <td>Дата поступления</td><td>01.02.2026</td>
  <td>Категория дела</td><td>Споры из договоров</td>
  <td>Судья</td><td>Иванова И.И.</td>
  <td>Дата рассмотрения</td><td>15.03.2026</td>
  <td>Результат рассмотрения</td><td>Удовлетворено</td>
  <td>Признак рассмотрения дела</td><td>Единолично</td>
</tr>
<tr><td>Уникальный идентификатор дела</td><td>36RS0001-01-2026-000001-00</td></tr>
<tr><td>Дата поступления</td><td>01.02.2026</td></tr>
<tr><td>Категория дела</td><td>Споры из договоров</td></tr>
<tr><td>Судья</td><td>Иванова И.И.</td></tr>
<tr><td>Дата рассмотрения</td><td>15.03.2026</td></tr>
<tr><td>Результат рассмотрения</td><td>Удовлетворено</td></tr>
<tr><td>Признак рассмотрения дела</td><td>Единолично</td></tr>
<tr><td colspan="5">ДВИЖЕНИЕ ДЕЛА</td></tr>
<tr><td>Наименование события</td><td>Дата</td><td>Время</td><td>Место проведения</td><td>Результат события</td></tr>
<tr><td>Регистрация иска</td><td>01.02.2026</td><td></td><td></td><td>Зарегистрировано</td></tr>
<tr><td>Беседа</td><td>10.02.2026</td><td>10:00</td><td>зал 1</td><td></td></tr>
<tr><td colspan="5">СТОРОНЫ ПО ДЕЛУ (ТРЕТЬИ ЛИЦА)</td></tr>
<tr><td>Вид лица, участвующего в деле</td><td>Фамилия / наименование</td><td>ИНН</td></tr>
<tr><td>ИСТЕЦ</td><td>Петров П.П.</td><td></td></tr>
<tr><td>ОТВЕТЧИК</td><td>ООО Ромашка</td><td></td></tr>
</table>
</div>
</body></html>
"""


def test_parse_case_card_extracts_data_movement_parties() -> None:
    cards = parse_case_cards(SAMPLE_HTML)
    assert len(cards) == 1
    card = cards[0]
    assert "ДАННЫЕ ПО ДЕЛУ" in card.sections
    assert "ДВИЖЕНИЕ ДЕЛА" in card.sections
    assert "СТОРОНЫ ПО ДЕЛУ" in card.sections

    data = card.sections["ДАННЫЕ ПО ДЕЛУ"]
    flat = {k: v for row in data for k, v in row.items()}
    assert flat["Уникальный идентификатор дела"] == "36RS0001-01-2026-000001-00"
    assert flat["Судья"] == "Иванова И.И."
    assert flat["Результат рассмотрения"] == "Удовлетворено"

    movements = card.sections["ДВИЖЕНИЕ ДЕЛА"]
    assert len(movements) == 2
    assert "Регистрация иска" in movements[0]
    assert "Беседа" in movements[1]
    assert "зал 1" in movements[1]["Беседа"]

    parties = card.sections["СТОРОНЫ ПО ДЕЛУ"]
    assert parties[0] == {"ИСТЕЦ": "Петров П.П."}
    assert parties[1]["ОТВЕТЧИК"].startswith("ООО Ромашка")


def test_format_case_card_includes_required_sections() -> None:
    card = CaseCard(
        case_number="2-1/2026",
        case_url="https://example/case",
        sections={
            "ДАННЫЕ ПО ДЕЛУ": [
                {"Уникальный идентификатор дела": "UID-1"},
                {"Дата поступления": "01.01.2026"},
                {"Категория дела": "Категория"},
                {"Судья": "Судья"},
                {"Дата рассмотрения": "02.01.2026"},
                {"Результат рассмотрения": "Иск удовлетворен"},
                {"Признак рассмотрения дела": "Единолично"},
            ],
            "СТОРОНЫ ПО ДЕЛУ": [{"ИСТЕЦ": "А"}],
            "ДВИЖЕНИЕ ДЕЛА": [
                {"Регистрация": "01.01.2026 | ок"},
                {"Вынесение решения": "02.01.2026 | 12:00"},
            ],
        },
    )
    text = format_case_card(card)
    assert "=== КАРТОЧКА ДЕЛА ===" in text
    assert "Номер дела: 2-1/2026" in text
    assert "Ссылка на карточку: https://example/case" in text
    assert "Уникальный идентификатор: UID-1" in text
    assert "Текущая стадия / последнее событие: Вынесение решения" in text
    assert "Результат рассмотрения: Иск удовлетворен" in text
    assert "--- Стороны по делу ---" in text
    assert "ИСТЕЦ: А" in text
    assert "--- Движение дела ---" in text
    assert "1. Регистрация: 01.01.2026 | ок" in text
    assert "=== КОНЕЦ КАРТОЧКИ ===" in text


def test_format_case_cards_sequential() -> None:
    cards = [
        CaseCard(case_number="2-1/2026", case_url="https://a", sections={}),
        CaseCard(case_number="2-2/2026", case_url="https://b", sections={}),
    ]
    text = format_case_cards(cards)
    assert "Найдено дел: 2" in text
    assert "### Дело 1 из 2" in text
    assert "### Дело 2 из 2" in text
    assert "Номер дела: 2-1/2026" in text
    assert "Номер дела: 2-2/2026" in text


def test_format_real_voronezh_fixture() -> None:
    html = open("tests/fixtures/case_2-1248_sovetsky.html", encoding="utf-8").read()
    cards = parse_case_cards(html)
    assert cards
    card = cards[0]
    card.case_number = "2-1248/2026"
    card.case_url = "https://sovetsky--vrn.sudrf.ru/modules.php?name=sud_delo&case_id=52002218"
    text = format_case_card(card)
    assert "Уникальный идентификатор: 36RS0005-01-2026-000068-54" in text
    assert "Наседкина Елена Викторовна" in text
    assert "УДОВЛЕТВОРЕН ЧАСТИЧНО" in text
    assert "ИСТЕЦ:" in text
    assert "ОТВЕТЧИК:" in text
    assert "Судебное заседание" in text
    assert "Ссылка на карточку:" in text
