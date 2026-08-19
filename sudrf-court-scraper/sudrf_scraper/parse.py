from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

PHONE_RE = re.compile(
    r"(?:\+7|8)[\s\-]?\(?\d{3,4}\)?[\s\-]?\d{2,3}[\s\-]?\d{2}[\s\-]?\d{2}"
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

NON_CONTENT_TAGS = ("script", "style", "noscript", "iframe", "svg")

# Типичные названия разделов на сайтах ГАС «Правосудие» — используются, чтобы
# помечать найденные страницы понятными категориями для базы знаний.
SECTION_KEYWORDS = {
    "contacts": ["контакт", "адрес суда", "как добраться"],
    "requisites": ["реквизит", "госпошлин", "оплат"],
    "reception": ["прием граждан", "приём граждан", "график приема", "часы работы"],
    "judges": ["судьи", "состав суда", "председатель"],
    "structure": ["структура суда", "аппарат суда", "подразделен"],
    "jurisdiction": ["подсудность", "территориальная подсудность", "юрисдикция"],
    "filing": ["подать заявление", "исковое заявление", "порядок обращения", "образцы документов"],
    "news": ["новости", "объявления", "пресс-служба"],
    "schedule": ["расписание", "календарь судебных заседаний", "назначенные дела"],
    "about": ["о суде", "история суда", "общие сведения"],
}


@dataclass
class Page:
    url: str
    title: str
    text: str
    section: str = "other"
    links: list[str] = field(default_factory=list)


def guess_section(title: str, url: str) -> str:
    haystack = f"{title} {url}".lower()
    for section, keywords in SECTION_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return section
    return "other"


def _clean_text(soup: BeautifulSoup) -> str:
    for tag in soup(NON_CONTENT_TAGS):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def parse_page(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("title")
    h1_tag = soup.find("h1")
    title = (h1_tag.get_text(strip=True) if h1_tag else None) or (
        title_tag.get_text(strip=True) if title_tag else url
    )

    # Ссылки собираем до чистки навигации: именно в меню лежат разделы сайта
    # («О суде», «Контакты», «Реквизиты» и т.п.), которые нужно обойти.
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if urlparse(href).netloc == urlparse(url).netloc:
            links.append(href.split("#")[0])

    # Основной контент чаще всего лежит в div/main с id/class типа content,
    # main, page, text — но верстка отличается между инстансами, поэтому
    # для надёжности берём весь body и просто вычищаем шапку/меню/подвал.
    body = soup.body or soup
    for selector in ("header", "footer", "nav", ".menu", "#menu", ".breadcrumbs"):
        for tag in body.select(selector):
            tag.decompose()

    text = _clean_text(body)

    return Page(url=url, title=title, text=text, section=guess_section(title, url), links=links)


def extract_contacts(text: str) -> dict:
    phones = sorted(set(PHONE_RE.findall(text)))
    emails = sorted(set(EMAIL_RE.findall(text)))
    return {"phones": phones, "emails": emails}
