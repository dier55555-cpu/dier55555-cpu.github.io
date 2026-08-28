"""
Разбор HTML-формы поиска дела («Судебное делопроизводство», модуль sud_delo).

Важно: разметка этой формы отличается от суда к суду (разные версии ГАС
«Правосудие», разное количество дополнительных полей). Поэтому здесь не
зашиты конкретные `name`-атрибуты input'ов — вместо этого форма разбирается
эвристически: для каждого поля ищем текст-подпись в той же строке таблицы
(`<tr>`) и сопоставляем её с известными формулировками полей. Если для
конкретного суда эвристика не справилась — см. `case_lookup/discover.py`,
который печатает все найденные поля для ручного маппинга через
`courts.yaml` (`case_search.field_overrides`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Нормализованная (нижний регистр) подстрока подписи -> внутреннее имя поля.
# Порядок важен: более специфичные фразы должны идти раньше общих.
KNOWN_LABELS: dict[str, str] = {
    "уникальный идентификатор дела": "case_uid",
    "номер дела": "case_number",
    "номер производства": "case_number",
    "фамилия": "last_name",
    "наименование организации": "org_name",
    "название организации": "org_name",
    "проверочный код": "captcha_code",
    "введите код": "captcha_code",
}


@dataclass
class FormField:
    name: str
    tag: str  # input | select | textarea
    input_type: Optional[str]
    value: Optional[str]
    label: str
    mapped_key: Optional[str] = None


@dataclass
class CaptchaInfo:
    field_name: str
    image_url: str


@dataclass
class SearchFormInfo:
    action_url: str
    method: str
    fields: list[FormField] = field(default_factory=list)
    captcha: Optional[CaptchaInfo] = None

    def field_by_key(self, key: str) -> Optional[FormField]:
        return next((f for f in self.fields if f.mapped_key == key), None)

    def unmapped_fields(self) -> list[FormField]:
        def is_visible(f: FormField) -> bool:
            return not (f.tag == "input" and f.input_type in ("hidden", "submit", "button"))
        return [f for f in self.fields if f.mapped_key is None and is_visible(f)]


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _match_label(label: str) -> Optional[str]:
    normalized = _normalize(label)
    for phrase, key in KNOWN_LABELS.items():
        if phrase in normalized:
            return key
    return None


def _row_label(tag) -> str:
    """Текст строки таблицы (или родительского блока), не считая значений input/option."""
    row = tag.find_parent("tr")
    container = row if row is not None else tag.find_parent(["div", "td", "li"]) or tag.parent
    if container is None:
        return ""
    texts = []
    for node in container.find_all(string=True):
        parent_name = node.parent.name if node.parent else ""
        if parent_name in ("input", "select", "option", "textarea", "script", "style"):
            continue
        stripped = node.strip()
        if stripped:
            texts.append(stripped)
    return " ".join(texts)


def _map_field_name(name: str) -> Optional[str]:
    """Запасное сопоставление по name-атрибуту ГАС «Правосудие» (G1_/U1_/A1_…)."""
    lowered = name.lower()
    if "case_numberss" in lowered:
        return "case_number"
    if "judicial_uidss" in lowered:
        return "case_uid"
    if "parts__namess" in lowered or "defendant__namess" in lowered:
        return "last_name"
    return None


def _parse_one_form(form, page_url: str) -> SearchFormInfo:
    action = (form.get("action") or "").strip()
    if action:
        action_url = urljoin(page_url, action)
    else:
        parsed = urlparse(page_url)
        action_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    method = (form.get("method") or "GET").upper()

    fields: list[FormField] = []
    captcha: Optional[CaptchaInfo] = None
    skip_types = ("hidden", "submit", "button", "reset", "image")

    for tag in form.find_all(["input", "select", "textarea"]):
        name = tag.get("name")
        if not name:
            continue
        tag_name = tag.name
        input_type = tag.get("type", "text") if tag_name == "input" else None
        value = tag.get("value")
        label = _row_label(tag)
        mapped_key = None
        if input_type not in skip_types:
            mapped_key = _match_label(label) or _map_field_name(name)

        fields.append(FormField(
            name=name, tag=tag_name, input_type=input_type,
            value=value, label=label, mapped_key=mapped_key,
        ))

        if mapped_key == "captcha_code":
            row = tag.find_parent("tr") or tag.parent
            img = row.find("img") if row else None
            if img and img.get("src"):
                captcha = CaptchaInfo(field_name=name, image_url=urljoin(page_url, img["src"]))

    return SearchFormInfo(action_url=action_url, method=method, fields=fields, captcha=captcha)


def parse_search_form(html: str, page_url: str) -> SearchFormInfo:
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form")
    if not forms:
        raise ValueError("На странице не найдена <form> — вероятно, это не форма поиска дела")

    parsed = [_parse_one_form(form, page_url) for form in forms]
    for info in parsed:
        if info.field_by_key("case_number") or info.field_by_key("last_name"):
            return info
    return parsed[0]
