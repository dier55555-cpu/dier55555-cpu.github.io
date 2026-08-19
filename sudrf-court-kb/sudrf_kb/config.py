"""Загрузка конфигурации судов и параметров обхода из config/courts.yaml."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "courts.yaml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


@dataclasses.dataclass(frozen=True)
class CourtConfig:
    court_id: str
    name: str
    base_url: str
    region: str = ""
    city: str = ""


@dataclasses.dataclass(frozen=True)
class CrawlConfig:
    max_pages_per_court: int = 60
    max_depth: int = 3
    request_delay_seconds: float = 1.5
    timeout_seconds: int = 20
    user_agent: str = "Mozilla/5.0 (compatible; DendriitKB-Bot/1.0)"
    respect_robots_txt: bool = True
    sensitive_path_markers: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class AppConfig:
    courts: list[CourtConfig]
    crawl: CrawlConfig
    data_dir: Path = DEFAULT_DATA_DIR

    def get_court(self, court_id: str) -> CourtConfig:
        for court in self.courts:
            if court.court_id == court_id:
                return court
        raise KeyError(
            f"Суд с court_id={court_id!r} не найден в конфигурации. "
            f"Доступные: {[c.court_id for c in self.courts]}"
        )


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    path = Path(path)
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))

    courts = [CourtConfig(**item) for item in raw.get("courts", [])]

    crawl_raw = raw.get("crawl", {})
    crawl = CrawlConfig(
        max_pages_per_court=crawl_raw.get("max_pages_per_court", 60),
        max_depth=crawl_raw.get("max_depth", 3),
        request_delay_seconds=crawl_raw.get("request_delay_seconds", 1.5),
        timeout_seconds=crawl_raw.get("timeout_seconds", 20),
        user_agent=crawl_raw.get(
            "user_agent", "Mozilla/5.0 (compatible; DendriitKB-Bot/1.0)"
        ),
        respect_robots_txt=crawl_raw.get("respect_robots_txt", True),
        sensitive_path_markers=tuple(crawl_raw.get("sensitive_path_markers", [])),
    )

    return AppConfig(courts=courts, crawl=crawl)
