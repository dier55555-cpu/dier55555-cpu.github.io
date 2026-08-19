from __future__ import annotations

import json
import re
from pathlib import Path

from .config import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR
from .crawler import CourtDump


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-zа-я0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "page"


def save_raw_dump(dump: CourtDump, data_dir: Path = DEFAULT_DATA_DIR) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / f"{dump.court.slug}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(dump.to_dict(), fh, ensure_ascii=False, indent=2)
    return out_path


def build_markdown_kb(dump: CourtDump, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    """Формирует один markdown-файл на суд — удобно загружать целиком в
    базу знаний (БЗ) ИИ-агента платформы НОЕ (или любой другой, принимающей
    txt/md файлы для RAG).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    court_dir = output_dir / dump.court.slug
    court_dir.mkdir(parents=True, exist_ok=True)

    combined_path = court_dir / "_all.md"
    lines: list[str] = [
        f"# {dump.court.name}",
        "",
        f"Источник: {dump.court.url}",
        f"Дата сбора данных: {dump.scraped_at}",
        "",
    ]

    if dump.contacts.get("phones") or dump.contacts.get("emails"):
        lines.append("## Контакты (автоматически найдены на сайте)")
        for phone in dump.contacts.get("phones", []):
            lines.append(f"- Телефон: {phone}")
        for email in dump.contacts.get("emails", []):
            lines.append(f"- Email: {email}")
        lines.append("")

    for page in dump.pages:
        if not page.text.strip():
            continue
        lines.append(f"## {page.title}")
        lines.append(f"_Раздел: {page.section} | Источник: {page.url}_")
        lines.append("")
        lines.append(page.text)
        lines.append("")

        section_path = court_dir / f"{_slugify(page.title)}.md"
        section_path.write_text(
            f"# {page.title}\n\nСуд: {dump.court.name}\nИсточник: {page.url}\n\n{page.text}\n",
            encoding="utf-8",
        )

    combined_path.write_text("\n".join(lines), encoding="utf-8")
    return combined_path


def build_index(dumps: list[CourtDump], output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    """Сводный index.json со всеми судами — контакты + список разделов,
    удобен для быстрого поиска без полнотекстового индекса."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for dump in dumps:
        index.append(
            {
                "slug": dump.court.slug,
                "name": dump.court.name,
                "url": dump.court.url,
                "scraped_at": dump.scraped_at,
                "contacts": dump.contacts,
                "sections": sorted({p.section for p in dump.pages}),
                "pages_count": len(dump.pages),
            }
        )
    index_path = output_dir / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path
