"""
Утилита для разведки формы поиска дела конкретного суда — запускать один раз
на каждый суд/тип производства **с российского IP/прокси**, чтобы проверить,
что автоматическая эвристика (`forms.py`) правильно нашла поля и понять,
есть ли капча.

Пример:

    python -m scraper.case_lookup.discover \
        --config courts.yaml --slug sovetsky-vrn --delo-id 1540005 \
        --proxy http://user:pass@ru-proxy-host:port

Результат печатается в консоль и сохраняется в
data/<slug>/case_search_form_<delo_id>.json — приложите этот файл, если
понадобится доработать сопоставление полей.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

from ..fetch import Fetcher
from .forms import parse_search_form


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path("courts.yaml"))
    parser.add_argument("--slug", required=True, help="slug суда из courts.yaml")
    parser.add_argument("--delo-id", type=int, required=True,
                         help="код типа производства, напр. 1540005 (гражданские) / 1540006 (уголовные) — см. README")
    parser.add_argument("--proxy", type=str, default=None)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args(argv)

    courts = yaml.safe_load(args.config.read_text(encoding="utf-8"))["courts"]
    court = next((c for c in courts if c["slug"] == args.slug), None)
    if court is None:
        print(f"Суд {args.slug!r} не найден в {args.config}", file=sys.stderr)
        return 1

    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    fetcher = Fetcher(proxies=proxies)

    form_url = f"{court['base_url'].rstrip('/')}/modules.php?name=sud_delo&name_op=sf&delo_id={args.delo_id}&srv_num=1"
    result = fetcher.get(form_url)

    if result.blocked or not result.ok or not result.html:
        print(f"Не удалось получить форму: blocked={result.blocked}, error={result.error}", file=sys.stderr)
        print("Запускайте эту команду с российского IP/прокси (--proxy).", file=sys.stderr)
        return 1

    form = parse_search_form(result.html, form_url)

    report = {
        "court_slug": args.slug,
        "delo_id": args.delo_id,
        "form_url": form_url,
        "action_url": form.action_url,
        "method": form.method,
        "fields": [asdict(f) for f in form.fields],
        "unmapped_visible_fields": [asdict(f) for f in form.unmapped_fields()],
        "captcha": asdict(form.captcha) if form.captcha else None,
    }

    out_dir = args.out / args.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"case_search_form_{args.delo_id}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nСохранено: {out_path}", file=sys.stderr)
    if report["unmapped_visible_fields"]:
        print(
            "\nВНИМАНИЕ: часть видимых полей не сопоставлена автоматически. "
            "Добавьте их в courts.yaml -> case_search.field_overrides по имени "
            "поля (name) из вывода выше.",
            file=sys.stderr,
        )
    if report["captcha"]:
        print("\nНа форме обнаружена капча — потребуется captcha_solver.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
