"""Командная строка для sudrf-court-kb.

Примеры:
    python -m sudrf_kb.cli crawl --all
    python -m sudrf_kb.cli crawl --court sovetsky
    python -m sudrf_kb.cli build-kb
    python -m sudrf_kb.cli serve-mcp --transport stdio
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .crawler import crawl_court
from .fetch import BlockedByWafError, PoliteFetcher
from .kb_builder import build_kb, save_crawl_outcome


def _cmd_crawl(args: argparse.Namespace) -> int:
    config = load_config()
    fetcher = PoliteFetcher(config.crawl)

    if args.all:
        courts = config.courts
    elif args.court:
        courts = [config.get_court(args.court)]
    else:
        print("Укажите --all или --court <court_id>", file=sys.stderr)
        return 2

    had_blocking_error = False
    for court in courts:
        print(f"Обход {court.name} ({court.base_url}) ...")
        outcome = crawl_court(court, config.crawl, fetcher=fetcher)
        save_crawl_outcome(outcome, config.data_dir)
        print(f"  собрано страниц: {len(outcome.pages)}, ошибок: {len(outcome.errors)}")
        for error in outcome.errors:
            print(f"  ! {error}", file=sys.stderr)
            lowered_error = error.lower()
            if any(
                marker in lowered_error
                for marker in ("geo", "заблокирован", "waf", "robots.txt")
            ):
                had_blocking_error = True

    if had_blocking_error:
        print(
            "\nПохоже, обход блокируется geo-фильтром sudrf.ru (в т.ч. это может "
            "проявляться как отказ robots.txt, если WAF блокирует и его). "
            "Запускайте краулер с российского сервера/прокси - см. README.md.",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_build_kb(_: argparse.Namespace) -> int:
    config = load_config()
    written = build_kb(config)
    print("Собраны файлы базы знаний:")
    for name, path in written.items():
        print(f"  {name} -> {path}")
    return 0


def _cmd_serve_mcp(args: argparse.Namespace) -> int:
    from . import mcp_server

    mcp_server.run(transport=args.transport, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sudrf_kb", description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="подробный лог")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="обойти сайт(ы) суда")
    crawl_parser.add_argument("--all", action="store_true", help="обойти все суды из конфига")
    crawl_parser.add_argument("--court", help="court_id одного суда для обхода")
    crawl_parser.set_defaults(func=_cmd_crawl)

    build_parser_ = subparsers.add_parser(
        "build-kb", help="собрать markdown/JSON базу знаний из результатов обхода"
    )
    build_parser_.set_defaults(func=_cmd_build_kb)

    serve_parser = subparsers.add_parser("serve-mcp", help="запустить MCP-сервер")
    serve_parser.add_argument(
        "--transport", choices=["stdio", "sse", "streamable-http"], default="stdio"
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.set_defaults(func=_cmd_serve_mcp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        return args.func(args)
    except BlockedByWafError as exc:
        print(f"Заблокировано WAF: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
