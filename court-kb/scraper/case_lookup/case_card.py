"""Разбор карточки дела / результатов поиска.

Секции карточки дела (ДАННЫЕ ПО ДЕЛУ, ДВИЖЕНИЕ ДЕЛА, СТОРОНЫ ПО ДЕЛУ и т.д.)
у разных судов называются по-разному и в разном наборе (см. README и
сравнение двух реальных карточек в комментариях ниже), поэтому вместо
жёстко заданных названий секций используется эвристика: заголовком секции
считается строка таблицы, где первая ячейка — сплошной текст в ВЕРХНЕМ
РЕГИСТРЕ, а остальные ячейки пустые (так эти карточки обычно и оформлены).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

NOT_FOUND_MARKERS = (
    "ничего не найдено",
    "не найдено",
    "не найдено дел",
    "нет данных",
)

WRONG_CAPTCHA_MARKERS = (
    "неверный код",
    "неправильный код",
    "введите код с картинки",
    "проверочный код указан неверно",
)


@dataclass
class CaseCard:
    sections: dict[str, list[dict[str, str]]] = field(default_factory=dict)


def _is_section_header(cells: list[str]) -> bool:
    if not cells:
        return False
    head = cells[0].strip()
    if not head or not any(ch.isalpha() for ch in head):
        return False
    if head != head.upper():
        return False
    return all(not c.strip() for c in cells[1:])


def looks_like_not_found(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in NOT_FOUND_MARKERS)


def looks_like_wrong_captcha(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in WRONG_CAPTCHA_MARKERS)


def parse_case_cards(html: str) -> list[CaseCard]:
    """Извлекает секции карточки(ек) дела из HTML результатов поиска.

    Может вернуть несколько карточек, если по запросу нашлось несколько дел
    на одной странице (типично для поиска по фамилии).
    """
    soup = BeautifulSoup(html, "html.parser")
    cards: list[CaseCard] = []
    current: CaseCard | None = None
    current_section: str | None = None

    for row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if not cells:
            continue

        if _is_section_header(cells):
            header = cells[0].strip()
            # Повторное появление "ДАННЫЕ ПО ДЕЛУ"/аналогичной вводной секции
            # обычно означает начало карточки следующего найденного дела.
            if header.upper() in {"ДАННЫЕ ПО ДЕЛУ", "ОБЩИЕ СВЕДЕНИЯ", "ИНФОРМАЦИЯ ПО ДЕЛУ"} or current is None:
                current = CaseCard()
                cards.append(current)
            current_section = header
            current.sections.setdefault(current_section, [])
            continue

        if current is not None and current_section is not None and len(cells) >= 2:
            key = cells[0].strip()
            value = " | ".join(c.strip() for c in cells[1:] if c.strip())
            if key:
                current.sections[current_section].append({key: value})

    return cards


def format_case_card(card: CaseCard) -> str:
    lines = []
    for section, rows in card.sections.items():
        if not rows:
            continue
        lines.append(section)
        for row in rows:
            for key, value in row.items():
                if value:
                    lines.append(f"  {key}: {value}")
        lines.append("")
    return "\n".join(lines).strip()
