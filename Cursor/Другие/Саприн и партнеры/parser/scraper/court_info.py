"""Справка с сайта суда ГАС «Правосудие»: режим, контакты, структура, реквизиты.

Однотипные модули на районных/городских сайтах (проверено 21.08.2026 на
Октябрьском Ставрополь, Коминтерновском Воронеж, Ленинском Ростов-на-Дону):
info_court, information, terr, govduty, sud_delo, press_dep, gbook.
Часы и телефоны НЕ храним в БЗ — снимаем с сайта по ссылке из справочника.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch import Fetcher

Status = Literal["found", "not_found", "blocked", "error"]

Topic = Literal[
    "hours",
    "contacts",
    "structure",
    "jurisdiction",
    "duty",
    "visitors",
    "general",
]

TOPIC_ALIASES = {
    "hours": "hours",
    "режим": "hours",
    "график": "hours",
    "время": "hours",
    "приемная": "hours",
    "приёмная": "hours",
    "канцелярия": "hours",
    "contacts": "contacts",
    "контакт": "contacts",
    "телефон": "contacts",
    "email": "contacts",
    "e-mail": "contacts",
    "почта": "contacts",
    "structure": "structure",
    "структур": "structure",
    "состав": "structure",
    "jurisdiction": "jurisdiction",
    "подсудност": "jurisdiction",
    "территория": "jurisdiction",
    "duty": "duty",
    "госпошлин": "duty",
    "реквизит": "duty",
    "visitors": "visitors",
    "посетител": "visitors",
    "проезд": "visitors",
    "general": "general",
    "о суде": "general",
    "справк": "general",
}

LINK_MARKERS_BY_TOPIC: dict[str, tuple[str, ...]] = {
    "hours": (
        "режим", "график приема", "график приёма", "порядок приема", "порядок приёма",
        "прием граждан", "приём граждан", "канцеляр",
    ),
    "contacts": ("контакт", "телефон", "адрес", "режим", "порядок приема", "порядок приёма"),
    "structure": ("структур", "состав", "о суде"),
    "jurisdiction": ("подсудност", "территор"),
    "duty": ("реквизит", "госпошлин", "банков"),
    "visitors": ("посетител", "проезд", "как добрать"),
    "general": ("о суде", "общая информация", "справочн"),
}

TEXT_MARKERS_BY_TOPIC: dict[str, tuple[str, ...]] = {
    "hours": (
        "режим работы", "график приема", "график приёма", "понедельник",
        "обеденный", "приемная", "приёмная", "часы приема", "часы приёма",
    ),
    "contacts": ("телефон", "факс", "@", "адрес", "контакт"),
    "structure": ("структур", "председатель", "состав", "отдел"),
    "jurisdiction": ("подсудност", "улиц", "район"),
    "duty": ("реквизит", "инн", "кпп", "р/с", "госпошлин", "бик"),
    "visitors": ("посетител", "проезд", "остановка", "паспорт"),
    "general": ("о суде", "образован", "адрес"),
}

NOISE_START = (
    "о суде",
    "01.общая",
    "02.организационная",
    "судейское сообщество",
    "нормативные акты",
    "документы суда",
    "судебное делопроизводство",
    "справочная информация",
    "пресс-служба",
    "управление судебного департамента",
    "суды субъекта",
    "муниципальные органы",
    "вакансии",
    "противодействие коррупции",
    "обращения граждан",
    "главная",
    "карта сайта",
    "обычная версия",
    "калькулятор госпошлины",
    "журнал \"",
    "журнал «",
    "уголок истории",
    "внимание!",
    "информируем вас",
    "масс-медиа",
    "социальные",
)


@dataclass
class CourtInfoResult:
    status: Status
    message: str
    source_url: Optional[str] = None
    topic: str = "hours"

    def as_text(self) -> str:
        if self.status == "found":
            if self.source_url:
                return f"{self.message}\nИсточник: {self.source_url}"
            return self.message
        return self.message


def normalize_topic(raw: Optional[str]) -> str:
    text = (raw or "hours").strip().lower().replace("ё", "е")
    if not text:
        return "hours"
    if text in TOPIC_ALIASES:
        return TOPIC_ALIASES[text]
    for key, topic in TOPIC_ALIASES.items():
        if key in text:
            return topic
    return "hours"


def website_to_origin(website: str) -> Optional[str]:
    """http://oktyabrsky.stv.sudrf.ru → https://oktyabrsky--stv.sudrf.ru"""
    raw = (website or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return None
    if host.endswith(".sudrf.ru") and "--" not in host:
        parts = host.split(".")
        if len(parts) >= 4 and parts[-2] == "sudrf":
            host = f"{parts[0]}--{parts[1]}.sudrf.ru"
    return f"https://{host}"


def fetch_court_info(
    fetcher: Fetcher,
    website: str,
    topic: str = "hours",
) -> CourtInfoResult:
    topic = normalize_topic(topic)
    origin = website_to_origin(website)
    if not origin:
        return CourtInfoResult(
            "error",
            "Нужна ссылка на официальный сайт суда (поле САЙТ из справочника).",
            topic=topic,
        )

    # Часы: один-два URL на канал (direct/прокси). Ротацию каналов делает delo_app.
    # Иначе 3 URL × timeout на мёртвом канале съедают бюджет n8n.
    if topic == "hours":
        best_text = ""
        best_url = origin + "/"
        best_score = -1
        saw_block = False
        for url in (
            origin + "/modules.php?name=information&id=1",
            origin + "/",
        ):
            page = fetcher.get(url, respect_robots=False)
            if page.blocked:
                saw_block = True
                break
            if not page.ok or not page.html:
                break
            extracted = _extract_topic_block(page.html, topic)
            score = _score_extract(extracted, topic, page.url or url)
            if score > best_score:
                best_score = score
                best_text = extracted
                best_url = page.url or url
            if best_score >= 80 and len(best_text) >= 60:
                return CourtInfoResult("found", best_text, source_url=best_url, topic=topic)
        if len(best_text) >= 60 and best_score >= 40:
            return CourtInfoResult("found", best_text, source_url=best_url, topic=topic)
        if saw_block:
            return CourtInfoResult(
                "blocked",
                "Сайт суда заблокировал запрос (нужен российский IP/прокси).",
                topic=topic,
            )
        if best_score < 0:
            return CourtInfoResult(
                "error",
                "Сайт суда временно недоступен через текущий канал. Попробуйте ещё раз.",
                topic=topic,
            )
        return CourtInfoResult(
            "not_found",
            "На сайте суда не удалось выделить запрошенные сведения в типовых разделах "
            f"(О суде / Справочная информация). Проверьте сайт напрямую: {origin}/",
            source_url=origin + "/",
            topic=topic,
        )

    home = fetcher.get(origin + "/", respect_robots=False)
    if home.blocked:
        return CourtInfoResult(
            "blocked",
            "Сайт суда заблокировал запрос (нужен российский IP/прокси).",
            topic=topic,
        )
    if not home.ok or not home.html:
        return CourtInfoResult(
            "error",
            "Сайт суда временно недоступен через прокси. Попробуйте задать вопрос ещё раз.",
            topic=topic,
        )

    markers = LINK_MARKERS_BY_TOPIC.get(topic, LINK_MARKERS_BY_TOPIC["hours"])
    candidates = _candidate_urls(home.html, origin, markers)

    # Типовые модули ГАС — порядок важен для часов.
    defaults = [
        "/modules.php?name=information&id=1",
        "/modules.php?name=information",
        "/modules.php?name=info_court",
        "/modules.php?name=information&id=2",
        "/modules.php?name=info_court&rid=1",
        "/modules.php?name=info_court&rid=4",
        "/modules.php?name=terr",
        "/modules.php?name=govduty",
        "/modules.php?name=map",
    ]
    if topic == "jurisdiction":
        defaults = ["/modules.php?name=terr"] + defaults
    elif topic == "duty":
        defaults = ["/modules.php?name=govduty", "/modules.php?name=info_court"] + defaults
    elif topic == "structure":
        defaults = ["/modules.php?name=info_court", "/modules.php?name=info_court&rid=2"] + defaults
    elif topic == "hours":
        defaults = [
            "/modules.php?name=information&id=1",
            "/modules.php?name=info_court&rid=1",
            "/modules.php?name=information",
            "/modules.php?name=info_court",
        ]

    for path in defaults:
        u = origin + path
        if u not in candidates:
            candidates.append(u)
    # Главная тоже часто содержит блок «Режим работы» (Ростов и др.).
    if origin + "/" not in candidates:
        candidates.insert(0, origin + "/")

    page_limit = 5 if topic == "hours" else 12
    good_enough = 100 if topic == "hours" else 10_000
    result = _try_pages(
        fetcher,
        topic,
        origin,
        candidates,
        markers=markers,
        page_limit=page_limit,
        good_enough=good_enough,
    )
    if result is not None:
        return result
    return CourtInfoResult(
        "not_found",
        "На сайте суда не удалось выделить запрошенные сведения в типовых разделах "
        f"(О суде / Справочная информация). Проверьте сайт напрямую: {origin}/",
        source_url=origin + "/",
        topic=topic,
    )


def _try_pages(
    fetcher: Fetcher,
    topic: str,
    origin: str,
    candidates: list[str],
    *,
    markers: tuple[str, ...],
    page_limit: int,
    good_enough: int,
) -> Optional[CourtInfoResult]:
    best_text = ""
    best_url = candidates[0] if candidates else origin + "/"
    best_score = -1
    seen_pages: set[str] = set()
    queue = list(candidates)
    scanned = 0
    idx = 0
    while idx < len(queue) and scanned < page_limit:
        url = queue[idx]
        idx += 1
        if url in seen_pages:
            continue
        seen_pages.add(url)
        scanned += 1
        page = fetcher.get(url, respect_robots=False)
        if page.blocked and not best_text:
            return CourtInfoResult(
                "blocked",
                "Сайт суда заблокировал запрос (нужен российский IP/прокси).",
                topic=topic,
            )
        if not page.ok or not page.html:
            continue
        if "name=information" in url and "id=" not in url:
            for _title, href in _links_matching(page.html, origin, markers):
                if href not in seen_pages and href not in queue:
                    queue.insert(idx, href)
        if "name=info_court" in url and "rid=" not in url and "id=" not in url:
            for _title, href in _links_matching(
                page.html, origin, markers + ("порядок", "общая информация", "структур", "реквизит")
            ):
                if href not in seen_pages and href not in queue:
                    queue.insert(idx, href)
        extracted = _extract_topic_block(page.html, topic)
        score = _score_extract(extracted, topic, page.url or url)
        if score > best_score:
            best_score = score
            best_text = extracted
            best_url = page.url or url
        if best_score >= good_enough and len(best_text) >= 60:
            return CourtInfoResult("found", best_text, source_url=best_url, topic=topic)

    if len(best_text) < 60:
        return None
    return CourtInfoResult("found", best_text, source_url=best_url, topic=topic)


def _score_extract(text: str, topic: str, url: str) -> int:
    if len(text) < 60:
        return -1
    low = text.lower().replace("ё", "е")
    score = min(len(text), 1200) // 20
    if "режим работы" in low:
        score += 80
    if "понедельник" in low and ("08" in low or "09" in low or "9:00" in low or "9.00" in low):
        score += 40
    if "information&id=" in url or "info_court&rid=" in url:
        score += 30
    if topic == "hours" and ("канцеляр" in low or "приемн" in low or "отдел" in low):
        score += 15
    if "журнал" in low or "уголок истории" in low:
        score -= 40
    return score


def _candidate_urls(html: str, origin: str, markers: tuple[str, ...]) -> list[str]:
    urls: list[str] = []
    for _title, href in _links_matching(html, origin, markers):
        if href not in urls:
            urls.append(href)
    return urls


def _links_matching(html: str, origin: str, markers: tuple[str, ...]) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        title = " ".join((a.get_text(" ", strip=True) or "").split())
        low = title.lower().replace("ё", "е")
        if not any(m in low for m in markers):
            continue
        href = a["href"].strip()
        if href.startswith("?"):
            href = "/modules.php" + href
        abs_url = urljoin(origin + "/", href)
        if urlparse(abs_url).netloc != urlparse(origin).netloc:
            continue
        out.append((title, abs_url))
    return out


def _extract_topic_block(html: str, topic: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    low = text.lower().replace("ё", "е")

    markers = TEXT_MARKERS_BY_TOPIC.get(topic, TEXT_MARKERS_BY_TOPIC["hours"])
    start = _find_best_start(low, topic, markers)
    if start == -1:
        return ""

    chunk = text[start:]
    cut = len(chunk)
    low_chunk = chunk.lower().replace("ё", "е")
    for noise in NOISE_START:
        idx = low_chunk.find(noise, 220)
        if idx != -1 and idx < cut:
            cut = idx
    if topic == "hours":
        for stop in ("опубликовано", "журнал", "уголок истории", "внимание!"):
            idx = low_chunk.find(stop, 150)
            if idx != -1 and idx < cut:
                cut = idx
    chunk = chunk[:cut].strip()

    lines: list[str] = []
    seen: set[str] = set()
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        key = line.lower()
        if "версия для печати" in key.replace("\xa0", " "):
            continue
        if key in seen and ("режим работы" in key or len(key) < 40):
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= 70:
            break
    joined = "\n".join(lines)
    low_j = joined.lower()
    if not any(m.replace("ё", "е") in low_j for m in markers):
        return ""
    return joined


def _find_best_start(low: str, topic: str, markers: tuple[str, ...]) -> int:
    """Для часов якоримся на «режим работы» рядом с днями недели и часами."""
    if topic == "hours":
        best = -1
        best_score = -1
        pos = 0
        while True:
            i = low.find("режим работы", pos)
            if i == -1:
                break
            window = low[i : i + 550]
            score = 0
            if "понедельник" in window:
                score += 5
            if any(t in window for t in ("08", "09", "9:00", "9.00", "17:", "18:", "16:")):
                score += 5
            if "выходной" in window:
                score += 2
            if score > best_score:
                best_score = score
                best = i
            pos = i + 12
        if best != -1 and best_score >= 5:
            return best
    start = -1
    for marker in markers:
        i = low.find(marker.replace("ё", "е"))
        if i != -1 and (start == -1 or i < start):
            start = i
    return start
