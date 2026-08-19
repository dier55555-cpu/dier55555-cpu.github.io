"""Сборка результатов обхода в файлы базы знаний (JSON + Markdown)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import AppConfig
from .crawler import CrawlOutcome
from .parse import ParsedPage

logger = logging.getLogger(__name__)

_CATEGORY_TITLES = {
    "contacts": "Контакты и реквизиты",
    "structure": "Структура суда и судьи",
    "reception": "Приём граждан / график работы",
    "news": "Новости и объявления",
    "how_to_submit": "Порядок подачи документов",
    "vacancies": "Вакансии",
    "case_lookup": "Судебное делопроизводство (пропущено, см. README)",
    "other": "Прочая информация",
}

_RAW_DIR_NAME = "raw"


def outcome_to_dict(outcome: CrawlOutcome) -> dict:
    return {
        "court_id": outcome.court.court_id,
        "name": outcome.court.name,
        "base_url": outcome.court.base_url,
        "region": outcome.court.region,
        "city": outcome.court.city,
        "pages": [
            {
                "url": page.url,
                "title": page.title,
                "category": page.category,
                "text": page.text,
            }
            for page in outcome.pages
        ],
        "errors": outcome.errors,
    }


def save_crawl_outcome(outcome: CrawlOutcome, data_dir: Path) -> Path:
    """Сохраняет сырой результат обхода одного суда в data/raw/<court_id>.json.

    Это промежуточный кэш, из которого build_court_markdown/build_all
    собирают финальные файлы БЗ — так можно пересобрать markdown без
    повторного обращения к сайту.
    """
    raw_dir = data_dir / _RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{outcome.court.court_id}.json"
    path.write_text(
        json.dumps(outcome_to_dict(outcome), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Сохранён сырой результат обхода: %s (%d страниц)", path, len(outcome.pages))
    return path


def load_crawl_outcomes(data_dir: Path) -> list[dict]:
    raw_dir = data_dir / _RAW_DIR_NAME
    if not raw_dir.exists():
        return []
    outcomes = []
    for path in sorted(raw_dir.glob("*.json")):
        outcomes.append(json.loads(path.read_text(encoding="utf-8")))
    return outcomes


def _page_to_markdown(page: dict) -> str:
    return f"### {page['title']}\n\nURL: {page['url']}\n\n{page['text']}\n"


def court_dict_to_markdown(court: dict) -> str:
    lines = [f"# {court['name']}", "", f"Сайт: {court['base_url']}", ""]

    pages_by_category: dict[str, list[dict]] = {}
    for page in court["pages"]:
        pages_by_category.setdefault(page["category"], []).append(page)

    for category, category_title in _CATEGORY_TITLES.items():
        pages = pages_by_category.get(category)
        if not pages:
            continue
        lines.append(f"## {category_title}")
        lines.append("")
        for page in pages:
            lines.append(_page_to_markdown(page))

    if court.get("errors"):
        lines.append("## Ошибки при обходе (для разработчика, не для агента)")
        lines.append("")
        for error in court["errors"]:
            lines.append(f"- {error}")
        lines.append("")

    return "\n".join(lines)


def build_kb(config: AppConfig) -> dict[str, Path]:
    """Собирает data/<court_id>.md, data/<court_id>.json и data/all_courts.md
    из кэша обхода (data/raw/*.json). Требует, чтобы crawl уже был выполнен.
    """
    config.data_dir.mkdir(parents=True, exist_ok=True)
    outcomes = load_crawl_outcomes(config.data_dir)
    if not outcomes:
        raise FileNotFoundError(
            "Нет сохранённых результатов обхода в data/raw/. "
            "Сначала выполните: python -m sudrf_kb.cli crawl --all"
        )

    written: dict[str, Path] = {}
    combined_parts: list[str] = ["# База знаний: районные суды г. Воронежа", ""]

    for court in outcomes:
        court_id = court["court_id"]

        json_path = config.data_dir / f"{court_id}.json"
        json_path.write_text(
            json.dumps(court, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written[f"{court_id}.json"] = json_path

        markdown = court_dict_to_markdown(court)
        md_path = config.data_dir / f"{court_id}.md"
        md_path.write_text(markdown, encoding="utf-8")
        written[f"{court_id}.md"] = md_path

        combined_parts.append(markdown)
        combined_parts.append("\n---\n")

    combined_path = config.data_dir / "all_courts.md"
    combined_path.write_text("\n".join(combined_parts), encoding="utf-8")
    written["all_courts.md"] = combined_path

    return written


def publish_to_noya(markdown_paths: list[Path]) -> None:
    """Точка расширения: сюда добавить вызов API/вебхука загрузки документов
    в «БЗ» доски агента в НОЯ, когда будет известен точный интерфейс загрузки
    знаний платформы. Пока не реализовано - файлы грузятся в БЗ вручную.
    """
    raise NotImplementedError(
        "Автозагрузка в НОЯ не настроена. Уточните API/вебхук загрузки "
        "документов в БЗ и добавьте вызов здесь, либо загружайте "
        f"{[str(p) for p in markdown_paths]} в интерфейс НОЯ вручную."
    )
