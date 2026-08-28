"""Валидация и приведение номера дела к стандарту для поиска на sudrf.

Стандарт (основной номер производства в поле CASE_NUMBERSS):
  `{индекс}-{номер}/{год}`
  примеры: 2-1248/2026, 2а-45/2025, 1-12/2024, 33-1234/2025

Клиент часто присылает «сырой» текст:
  «ДЕЛО № 2-1248/2026 ~ М-52/2026»
  «дело №2-3588/2026»
По такому полному виду сайт суда ничего не находит — нужен только основной номер.

Правила приведения:
1. Убрать префиксы «дело», «№», «N», «No».
2. Отрезать материал / входящий номер после «~» / «≈» и хвост вида « М-52/2026».
3. Нормализовать тире (– — −) → «-», схлопнуть пробелы.
4. Вытащить первый фрагмент, похожий на номер производства.
5. Проверить шаблон стандарта (validate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Основной номер: 2-1248/2026, 2а-45/2025, 1-12/2024, 33-1234/2025
CASE_NUMBER_RE = re.compile(
    r"^(\d{1,4}[а-яА-ЯёЁa-zA-Z]?)-(\d{1,7}[а-яА-ЯёЁa-zA-Z]?)(?:/(\d{4}))?$",
    re.UNICODE,
)

# Фрагмент номера внутри произвольной строки
CASE_NUMBER_EXTRACT_RE = re.compile(
    r"(\d{1,4}[а-яА-ЯёЁa-zA-Z]?)\s*[-–—−‐‑]\s*(\d{1,7}[а-яА-ЯёЁa-zA-Z]?)\s*(?:/\s*(\d{4}))?",
    re.UNICODE,
)

_PREFIX_RE = re.compile(
    r"^(?:дело|дел[ауо]?|case|№|N[oо]?\.?|number)\s*",
    re.IGNORECASE | re.UNICODE,
)
_MATERIAL_TAIL_RE = re.compile(
    r"\s+[МмMm]\s*[-–—−]?\s*\d+(?:/\d+)?\s*$",
    re.UNICODE,
)


@dataclass(frozen=True)
class CaseNumberResult:
    """Результат нормализации/валидации номера дела."""

    raw: str
    normalized: Optional[str]
    ok: bool
    error: Optional[str] = None

    @property
    def value(self) -> Optional[str]:
        return self.normalized if self.ok else None


def normalize_case_number(raw: Optional[str]) -> Optional[str]:
    """Приводит ввод к стандарту `2-1248/2026` или None, если номера нет."""
    result = parse_case_number(raw)
    return result.normalized


def validate_case_number(raw: Optional[str]) -> CaseNumberResult:
    """Явная валидация: ok=True только если после приведения номер стандартен."""
    return parse_case_number(raw)


def parse_case_number(raw: Optional[str]) -> CaseNumberResult:
    if raw is None:
        return CaseNumberResult(raw="", normalized=None, ok=False, error="Номер дела пустой.")
    original = str(raw)
    text = original.strip()
    if not text:
        return CaseNumberResult(raw=original, normalized=None, ok=False, error="Номер дела пустой.")

    # 1) Префиксы «ДЕЛО №», «№»…
    text = _PREFIX_RE.sub("", text).strip()
    text = _PREFIX_RE.sub("", text).strip()  # «дело № …» — два прохода

    # 2) Материал после тильды: «2-1248/2026 ~ М-52/2026»
    for sep in ("~", "～", "≈"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    text = _MATERIAL_TAIL_RE.sub("", text).strip()

    # 3) Тире и пробелы
    text = text.replace("–", "-").replace("—", "-").replace("−", "-").replace("‐", "-").replace("‑", "-")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s*/\s*", "/", text)

    # 4) Уже чистый стандарт?
    if CASE_NUMBER_RE.match(text):
        normalized = _canonicalize(text)
        return CaseNumberResult(raw=original, normalized=normalized, ok=True)

    # 5) Вытащить первый похожий фрагмент из «мусорной» строки
    match = CASE_NUMBER_EXTRACT_RE.search(text)
    if match:
        left, right, year = match.group(1), match.group(2), match.group(3)
        candidate = f"{left}-{right}" + (f"/{year}" if year else "")
        if CASE_NUMBER_RE.match(candidate):
            normalized = _canonicalize(candidate)
            return CaseNumberResult(raw=original, normalized=normalized, ok=True)

    return CaseNumberResult(
        raw=original,
        normalized=None,
        ok=False,
        error=(
            "Не удалось распознать номер дела. Нужен вид 2-1248/2026 "
            "(без «ДЕЛО №» и без хвоста ~ М-…)."
        ),
    )


def _canonicalize(number: str) -> str:
    """Единый вид: латиница индекса → как есть, год без пробелов."""
    m = CASE_NUMBER_RE.match(number)
    if not m:
        return number
    left, right, year = m.group(1), m.group(2), m.group(3)
    # Индексы вроде «2а» на сайтах обычно в нижнем регистре кириллицы.
    left = _fold_index(left)
    right = _fold_index(right)
    if year:
        return f"{left}-{right}/{year}"
    return f"{left}-{right}"


def _fold_index(part: str) -> str:
    """2А / 2A → 2а (кириллическая «а» для sudrf, если была латиница A/a)."""
    if len(part) >= 2 and part[-1] in "Aa":
        return part[:-1] + "а"
    if len(part) >= 2 and part[-1] in "А":
        return part[:-1] + "а"
    return part
