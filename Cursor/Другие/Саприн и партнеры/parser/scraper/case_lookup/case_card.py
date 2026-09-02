"""Разбор карточки дела / результатов поиска ГАС «Правосудие».

На сайтах райсудов Воронежа:
- поиск → таблица `#tablcont`;
- полная карточка → `name_op=case` с блоками ДАННЫЕ/ДВИЖЕНИЕ/СТОРОНЫ.

Шапка «ДАННЫЕ ПО ДЕЛУ» часто идёт широкой строкой «ДЕЛО | …», а не
одиночным ALL-CAPS заголовком — это учитываем отдельно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

NOT_FOUND_MARKERS = (
    "ничего не найдено",
    "не найдено",
    "не найдено дел",
    "нет данных",
    "не обнаружено",
    "данных по запросу",
    "уточните критерии поиска",
)

WRONG_CAPTCHA_MARKERS = (
    "неверный код",
    "неправильный код",
    "введите код с картинки",
    "проверочный код указан неверно",
)

INTRO_HEADERS = {
    "ДАННЫЕ ПО ДЕЛУ",
    "ОБЩИЕ СВЕДЕНИЯ",
    "ИНФОРМАЦИЯ ПО ДЕЛУ",
    "ДЕЛО",
}

SECTION_ALIASES = {
    "ДАННЫЕ ПО ДЕЛУ": "ДАННЫЕ ПО ДЕЛУ",
    "ОБЩИЕ СВЕДЕНИЯ": "ДАННЫЕ ПО ДЕЛУ",
    "ИНФОРМАЦИЯ ПО ДЕЛУ": "ДАННЫЕ ПО ДЕЛУ",
    "ДЕЛО": "ДАННЫЕ ПО ДЕЛУ",
    "ДВИЖЕНИЕ ДЕЛА": "ДВИЖЕНИЕ ДЕЛА",
    "СТОРОНЫ ПО ДЕЛУ (ТРЕТЬИ ЛИЦА)": "СТОРОНЫ ПО ДЕЛУ",
    "СТОРОНЫ ПО ДЕЛУ": "СТОРОНЫ ПО ДЕЛУ",
    # Райсуд: точные имена вкладок (см. job/sudrf_tabs_rayon.md)
    "ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)": "ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)",
    "ОБЖАЛОВАНИЕ РЕШЕНИЙ": "ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)",
    "ДВИЖЕНИЕ ЖАЛОБЫ": "ДВИЖЕНИЕ ЖАЛОБЫ",
    "ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ": "ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ",
    "СУДЕБНЫЕ АКТЫ": "СУДЕБНЫЕ АКТЫ",
    # Облсуд (апелляция): точные имена вкладок (см. job/sudrf_tabs_oblsud.md)
    "РАССМОТРЕНИЕ В НИЖЕСТОЯЩЕМ СУДЕ": "РАССМОТРЕНИЕ В НИЖЕСТОЯЩЕМ СУДЕ",
    "УЧАСТНИКИ": "УЧАСТНИКИ",
}

# Строки-шапки таблиц движения/сторон/ИЛ — не факты карточки.
COLUMN_HEADER_KEYS = {
    "наименование события",
    "вид лица, участвующего в деле",
    "дата",
    "время",
    "место проведения",
    "результат события",
    "основание для выбранного результата события",
    "основание для выбранного результата",
    "примечание",
    "дата размещения",
    "событие",
    "результат",
    "дата выдачи",
    "серия, номер бланка",
    "номер электронного ид",
    "статус",
    "кому выдан / направлен",
}

DATA_FIELD_KEYS = {
    "уникальный идентификатор дела",
    "дата поступления",
    "категория дела",
    "судья",
    "дата рассмотрения",
    "результат рассмотрения",
    "признак рассмотрения дела",
    "номер дела",
    "текущая стадия",
    "стадия",
}


@dataclass
class CaseCard:
    sections: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    case_url: Optional[str] = None
    case_number: Optional[str] = None


def _is_section_header(cells: list[str]) -> bool:
    if not cells:
        return False
    head = cells[0].strip()
    if not head or not any(ch.isalpha() for ch in head):
        return False
    if head != head.upper():
        return False
    return all(not c.strip() for c in cells[1:])


def _normalize_section_name(header: str) -> str:
    key = " ".join(header.split()).upper()
    for alias, canon in SECTION_ALIASES.items():
        if alias in key or key in alias:
            return canon
    return header.strip()


def looks_like_not_found(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in NOT_FOUND_MARKERS)


def looks_like_wrong_captcha(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in WRONG_CAPTCHA_MARKERS)


def parse_case_cards(html: str) -> list[CaseCard]:
    """Извлекает секции полной карточки дела из HTML `name_op=case`."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find(id="content") or soup
    cards: list[CaseCard] = []
    current: CaseCard | None = None
    current_section: str | None = None

    def ensure_card() -> CaseCard:
        nonlocal current, current_section
        if current is None:
            current = CaseCard()
            cards.append(current)
            current_section = "ДАННЫЕ ПО ДЕЛУ"
            current.sections.setdefault(current_section, [])
        return current

    for row in root.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if not cells or not any(c.strip() for c in cells):
            continue

        # Широкая шапка «ДЕЛО | Уникальный идентификатор…» — начало карточки.
        first = cells[0].strip().upper()
        if first == "ДЕЛО" and len(cells) >= 3:
            current = CaseCard()
            cards.append(current)
            current_section = "ДАННЫЕ ПО ДЕЛУ"
            current.sections.setdefault(current_section, [])
            # Из широкой строки вытащим пары ключ/значение по соседним ячейкам.
            for i in range(1, len(cells) - 1, 2):
                key = cells[i].strip()
                value = cells[i + 1].strip() if i + 1 < len(cells) else ""
                if key and value and key.lower() in DATA_FIELD_KEYS:
                    current.sections[current_section].append({key: value})
            continue

        if _is_section_header(cells):
            header = _normalize_section_name(cells[0])
            if header == "ДАННЫЕ ПО ДЕЛУ" or current is None:
                current = CaseCard()
                cards.append(current)
            else:
                ensure_card()
            current_section = header
            assert current is not None
            current.sections.setdefault(current_section, [])
            continue

        # Пары «ключ | значение» до первого ALL-CAPS заголовка — это данные дела.
        if len(cells) >= 2:
            key = cells[0].strip()
            value = " | ".join(c.strip() for c in cells[1:] if c.strip())
            key_l = key.lower()
            if not key:
                continue
            if key_l in COLUMN_HEADER_KEYS:
                continue
            if current is None and key_l in DATA_FIELD_KEYS:
                ensure_card()
            if current is None or current_section is None:
                continue
            # Движение: колонки событие | дата | время | место | результат | …
            if current_section == "ДВИЖЕНИЕ ДЕЛА" and len(cells) >= 3:
                event = key
                date = cells[1].strip() if len(cells) > 1 else ""
                time_ = cells[2].strip() if len(cells) > 2 else ""
                place = cells[3].strip() if len(cells) > 3 else ""
                result = cells[4].strip() if len(cells) > 4 else ""
                reason = cells[5].strip() if len(cells) > 5 else ""
                note = cells[6].strip() if len(cells) > 6 else ""
                placed = cells[7].strip() if len(cells) > 7 else ""
                parts = [p for p in (date, time_, place, result, reason, note) if p]
                # дата размещения часто дублирует — оставляем в конце если есть
                if placed and placed not in parts:
                    parts.append(f"размещено {placed}")
                value = " | ".join(parts)
                current.sections[current_section].append({event: value})
                continue
            # ДВИЖЕНИЕ ЖАЛОБЫ / ОБЖАЛОВАНИЕ: Событие | Дата | Результат | Основание | Примечание | Дата размещения
            # Пустые ячейки сохраняем позиционно (иначе «Направлено…» схлопывает дату размещения в «результат»).
            if current_section in {
                "ДВИЖЕНИЕ ЖАЛОБЫ",
                "ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)",
            } and len(cells) >= 2:
                event = key
                date = cells[1].strip() if len(cells) > 1 else ""
                result = cells[2].strip() if len(cells) > 2 else ""
                reason = cells[3].strip() if len(cells) > 3 else ""
                note = cells[4].strip() if len(cells) > 4 else ""
                placed = cells[5].strip() if len(cells) > 5 else ""
                parts = [date, result, reason, note]
                if placed:
                    parts.append(f"размещено {placed}")
                value = " | ".join(parts)
                current.sections[current_section].append({event: value})
                continue
            # Стороны: вид | ФИО/наименование | ИНН | …
            if current_section.startswith("СТОРОНЫ") and len(cells) >= 2:
                role = key
                name = cells[1].strip() if len(cells) > 1 else ""
                extras = [c.strip() for c in cells[2:] if c.strip()]
                value = name
                if extras:
                    value = name + (" | " + " | ".join(extras) if name else " | ".join(extras))
                if role and value:
                    current.sections[current_section].append({role: value})
                continue
            if value:
                current.sections[current_section].append({key: value})

    return cards


def parse_search_hits(html: str, page_url: str) -> list[CaseCard]:
    """Таблица выдачи поиска (`#tablcont`) на сайтах ГАС «Правосудие»."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tablcont")
    if table is None:
        return []
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []
    headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    cards: list[CaseCard] = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        values = [c.get_text(" ", strip=True) for c in cells]
        if not any(values):
            continue
        section = []
        for header, value in zip(headers, values):
            if header and value:
                section.append({header: value})
        link = cells[0].find("a", href=True)
        card = CaseCard(sections={"РЕЗУЛЬТАТ ПОИСКА": section})
        if link:
            card.case_url = urljoin(page_url, link["href"])
            card.case_number = link.get_text(" ", strip=True) or None
        cards.append(card)
    return cards


def _section_rows(card: CaseCard, *names: str) -> list[dict[str, str]]:
    for name in names:
        for key, rows in card.sections.items():
            if name.lower() in key.lower():
                return rows
    return []


def _first_value(rows: list[dict[str, str]], *keys: str) -> Optional[str]:
    want = {k.lower() for k in keys}
    for row in rows:
        for key, value in row.items():
            if key.lower() in want and value:
                return value
    return None


def _clean_text(value: Optional[str]) -> str:
    if not value:
        return "—"
    return value.replace("\xa0", " ").strip() or "—"


def format_case_card(card: CaseCard) -> str:
    """Стабильный шаблон полной карточки для Анны (и для нескольких дел подряд)."""
    data = _section_rows(card, "ДАННЫЕ ПО ДЕЛУ", "ОБЩИЕ СВЕДЕНИЯ", "ДЕЛО")
    movement = _section_rows(card, "ДВИЖЕНИЕ ДЕЛА")
    parties = _section_rows(card, "СТОРОНЫ")
    search_hit = _section_rows(card, "РЕЗУЛЬТАТ ПОИСКА")

    uid = _first_value(data, "Уникальный идентификатор дела")
    filed = _first_value(data, "Дата поступления")
    category = _first_value(data, "Категория дела")
    judge = _first_value(data, "Судья")
    heard = _first_value(
        data,
        "Дата рассмотрения",
        "Дата рассмотрения дела в первой инстанции",
    )
    result = _first_value(data, "Результат рассмотрения")
    mode = _first_value(data, "Признак рассмотрения дела")
    stage = _first_value(data, "Текущая стадия", "Стадия")

    # Стадию часто видно по последнему событию движения.
    if not stage and movement:
        last = movement[-1]
        for event, detail in last.items():
            stage = event
            break

    # Если полной карточки нет — подтянуть поля из строки поиска.
    if search_hit and not data:
        uid = uid or _first_value(search_hit, "Уникальный идентификатор дела", "УИД")
        filed = filed or _first_value(search_hit, "Дата поступления")
        category = category or _first_value(search_hit, "Категория", "Категория / Стороны")
        judge = judge or _first_value(search_hit, "Судья")
        heard = heard or _first_value(search_hit, "Дата решения", "Дата рассмотрения")
        result = result or _first_value(search_hit, "Решение", "Результат рассмотрения")

    lines: list[str] = [
        "=== КАРТОЧКА ДЕЛА ===",
        f"Номер дела: {_clean_text(card.case_number)}",
        f"Ссылка на карточку: {_clean_text(card.case_url)}",
        "",
        "--- Основные сведения ---",
        f"Уникальный идентификатор: {_clean_text(uid)}",
        f"Дата поступления: {_clean_text(filed)}",
        f"Категория дела: {_clean_text(category)}",
        f"Судья: {_clean_text(judge)}",
        f"Дата рассмотрения: {_clean_text(heard)}",
        f"Результат рассмотрения: {_clean_text(result)}",
        f"Признак рассмотрения: {_clean_text(mode)}",
        f"Текущая стадия / последнее событие: {_clean_text(stage)}",
        "",
        "--- Стороны по делу ---",
    ]

    if parties:
        for row in parties:
            for role, name in row.items():
                if name:
                    lines.append(f"{role}: {name}")
    else:
        lines.append("—")

    lines.append("")
    lines.append("--- Движение дела ---")
    if movement:
        for index, row in enumerate(movement, 1):
            for event, detail in row.items():
                if detail:
                    lines.append(f"{index}. {event}: {detail}")
                else:
                    lines.append(f"{index}. {event}")
    else:
        lines.append("—")

    # Если полной карточки нет — дописать сырые поля поиска.
    if search_hit and not data and not movement and not parties:
        lines.append("")
        lines.append("--- Данные из поиска ---")
        for row in search_hit:
            for key, value in row.items():
                if value:
                    lines.append(f"{key}: {value}")
        lines.append(
            "(полная карточка по ссылке не загрузилась — откройте ссылку на сайте суда)"
        )

    # Прочие секции, если есть
    known = {"данные", "движение", "сторон", "результат поиска", "общие", "дело", "ещё результат"}
    for section, rows in card.sections.items():
        low = section.lower()
        if any(k in low for k in known):
            continue
        if not rows:
            continue
        lines.append("")
        lines.append(f"--- {section} ---")
        for row in rows:
            for key, value in row.items():
                if value:
                    lines.append(f"{key}: {value}")

    lines.append("=== КОНЕЦ КАРТОЧКИ ===")
    return "\n".join(lines).strip()


def format_case_cards(cards: list[CaseCard]) -> str:
    """Несколько дел — полные карточки последовательно."""
    if not cards:
        return ""
    real = [c for c in cards if "ЕЩЁ РЕЗУЛЬТАТЫ" not in c.sections]
    extras = [c for c in cards if "ЕЩЁ РЕЗУЛЬТАТЫ" in c.sections]
    total = len(real)
    parts: list[str] = []
    if total > 1:
        parts.append(f"Найдено дел: {total}. Ниже полные карточки по каждому делу подряд.")
    for i, card in enumerate(real, 1):
        header = f"### Дело {i} из {total}" if total > 1 else ""
        body = format_case_card(card)
        parts.append(f"{header}\n{body}".strip() if header else body)
    text = "\n\n".join(parts)
    for extra in extras:
        for rows in extra.sections.values():
            for row in rows:
                for msg in row.values():
                    if msg:
                        text += f"\n\n({msg})"
    return text
