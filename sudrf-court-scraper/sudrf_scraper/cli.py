from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import DEFAULT_COURTS_FILE, DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR, get_proxy_from_env, load_courts
from .crawler import crawl_court
from .fetch import build_session
from .kb_builder import build_index, build_markdown_kb, save_raw_dump


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сбор информации с сайтов районных судов (sudrf.ru) для базы знаний ИИ-агента."
    )
    parser.add_argument("--courts-file", default=str(DEFAULT_COURTS_FILE), help="JSON со списком судов")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Куда сохранить сырые JSON-дампы")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Куда сохранить markdown для БЗ")
    parser.add_argument("--only", nargs="*", help="Обработать только суды с этими slug (по умолчанию все)")
    parser.add_argument("--max-pages", type=int, default=60, help="Максимум страниц на сайт")
    parser.add_argument("--max-depth", type=int, default=3, help="Максимальная глубина обхода ссылок")
    parser.add_argument("--delay", type=float, default=1.0, help="Пауза между запросами, секунды")
    parser.add_argument(
        "--proxy",
        default=None,
        help="HTTP(S)-прокси с российским IP, например http://user:pass@host:port. "
        "Можно также задать переменную окружения SUDRF_PROXY. Без прокси с "
        "зарубежного/датацентрового IP сайты sudrf.ru обрывают TLS-соединение.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    proxy = args.proxy or get_proxy_from_env()
    courts = load_courts(args.courts_file)
    if args.only:
        courts = [c for c in courts if c.slug in set(args.only)]

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    session = build_session(proxy=proxy)

    dumps = []
    for court in courts:
        print(f"Обрабатываю: {court.name} ({court.url})")
        dump = crawl_court(
            court,
            session,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            delay=args.delay,
        )
        save_raw_dump(dump, data_dir=data_dir)
        build_markdown_kb(dump, output_dir=output_dir)
        dumps.append(dump)
        print(f"  -> собрано страниц: {len(dump.pages)}, телефонов: {len(dump.contacts.get('phones', []))}")

    index_path = build_index(dumps, output_dir=output_dir)
    print(f"Готово. Сводный индекс: {index_path}")


if __name__ == "__main__":
    main()
