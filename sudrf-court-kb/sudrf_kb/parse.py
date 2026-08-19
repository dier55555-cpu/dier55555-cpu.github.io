"""Извлечение «полезного» текста из HTML-страницы суда и его классификация.

Разметка у сайтов *.sudrf.ru типовая (общий движок ГАС «Правосудие»), но
без доступа к живым страницам (geo-блок, см. README.md) точные CSS-селекторы
подобрать нельзя. Поэтому парсер работает эвристически:

1. убирает служебные блоки (script/style/nav/header/footer/меню);
2. берёт заголовок страницы + оставшийся текстовый контент;
3. классифицирует страницу по ключевым словам в URL/заголовке — это
   используется для группировки в базе знаний (контакты, новости,
   структура суда, реквизиты и т.д.).

После первого реального обхода стоит проверить качество на живых страницах
и, если нужно, заменить `extract_main_text` на точные селекторы под
конкретный шаблон (обычно общий для всех судов на sudrf.ru).
"""

from __future__ import annotations

import dataclasses
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_NOISE_TAGS = ("script", "style", "nav", "header", "footer", "form", "noscript")

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "contacts": ("контакт", "адрес", "телефон", "реквизит", "почта", "как добраться"),
    "structure": ("структура", "состав суда", "судьи", "аппарат суда", "руководство"),
    "reception": ("приём граждан", "прием граждан", "график работы", "режим работы", "часы приема"),
    "news": ("новост", "объявлен", "пресс-релиз"),
    "how_to_submit": ("подать", "обращени", "документооборот", "исковое заявление", "порядок обращения"),
    "vacancies": ("вакан", "работа в суде", "конкурс на замещение"),
    "case_lookup": ("sud_delo", "движение дела", "судебное делопроизводство", "информация по делам"),
}


@dataclasses.dataclass
class ParsedPage:
    url: str
    title: str
    category: str
    text: str
    links: list[str]


def classify_page(url: str, title: str) -> str:
    haystack = f"{url} {title}".lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return category
    return "other"


def _clean_text(soup: BeautifulSoup) -> str:
    for tag_name in _NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    # убираем дубли соседних строк (частый мусор от вложенных div/span)
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base_url).netloc
    links: set[str] = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != base_domain:
            continue
        if parsed.path.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".png", ".zip", ".rar")):
            continue
        links.add(absolute.split("#")[0])
    return sorted(links)


def parse_page(url: str, html: str) -> ParsedPage:
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url

    text = _clean_text(soup)
    text = re.sub(r"\n{3,}", "\n\n", text)

    links = extract_links(html, url)
    category = classify_page(url, title)

    return ParsedPage(url=url, title=title, category=category, text=text, links=links)
