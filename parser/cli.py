"""CLI: scrape court sites into NOE-ready markdown.

Run from a Russian IP. Example:
  python -m parser.cli --out knowledge/live
"""

from __future__ import annotations

import argparse
from pathlib import Path

from parser.sudrf import load_courts, scrape_court, write_knowledge


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Scrape Voronezh sudrf.ru courts")
    parser.add_argument("--config", type=Path, default=root / "courts" / "config.json")
    parser.add_argument("--out", type=Path, default=root / "knowledge" / "live")
    args = parser.parse_args()

    courts = load_courts(args.config)
    scrapes = [scrape_court(court) for court in courts]
    write_knowledge(scrapes, args.out)

    blocked = 0
    ok = 0
    for scrape in scrapes:
        for page in scrape["pages"].values():
            if page.get("blocked"):
                blocked += 1
            elif page.get("ok"):
                ok += 1
    print(f"Wrote {args.out}  ok_pages={ok} blocked_pages={blocked}")
    if blocked and not ok:
        print(
            "All pages blocked. Run this from a Russian IP/VPS, then upload "
            "the markdown files into the NOE knowledge base."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
