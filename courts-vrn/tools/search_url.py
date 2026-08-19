"""Build official GAS Pravosudie search URLs for Voronezh district courts."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "courts.json"


def load_courts() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def find_court(query: str) -> dict | None:
    q = query.strip().lower()
    for court in load_courts()["courts"]:
        hay = " ".join(
            [
                court["id"],
                court["name"],
                court["district"],
                court["host"],
            ]
        ).lower()
        if q in hay:
            return court
    return None


def case_search_url(query: str) -> str:
    court = find_court(query)
    if not court:
        raise KeyError(f"Unknown court: {query}")
    return court["search_url"]


if __name__ == "__main__":
    import sys

    key = sys.argv[1] if len(sys.argv) > 1 else "ленинский"
    print(case_search_url(key))
