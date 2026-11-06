"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from divergent import gitutil
from divergent.compare import run_check
from divergent.config import ConfigError, default_config_path, load_config
from divergent.gitutil import GitError
from divergent.open_report import default_report_path, open_html_report
from divergent.report_html import render_html

EXIT_OK = 0
EXIT_DIVERGED = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="divergent",
        description=(
            "Check whether files changed in a main-repo commit are still "
            "identical (pre-commit) across configured variation repos. "
            "Read-only: never commits, pushes, or modifies repos. "
            "Writes an HTML report and opens it in your browser. "
            "On WSL, the report is placed under Windows Temp so Explorer can open it."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Compare a commit against variation repos")
    check.add_argument(
        "commit",
        nargs="?",
        default="HEAD",
        help="Commit to check (default: HEAD)",
    )
    check.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Path to divergent.toml (default: <main-repo>/divergent.toml)",
    )
    check.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write the HTML report to this file (default: Windows Temp on WSL, else a temp file)",
    )
    check.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the report in a browser",
    )
    return parser


def cmd_check(args: argparse.Namespace) -> int:
    try:
        cwd = Path.cwd()
        main_repo = gitutil.toplevel(cwd)
    except GitError as exc:
        print(f"error: not inside a git repository: {exc}", file=sys.stderr)
        return EXIT_ERROR

    config_path = args.config if args.config is not None else default_config_path(main_repo)

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        result = run_check(config, args.commit)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    html = render_html(result)
    if not html.endswith("\n"):
        html += "\n"

    if args.output is not None:
        out_path = args.output.resolve()
    else:
        out_path = default_report_path()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"report: {out_path}")
    if result.main_branch:
        print(f"main branch: {result.main_branch}")
    else:
        print("main branch: (detached HEAD)")
    print(f"compare ref: {result.variation_base_branch}")
    if result.all_safe:
        print("result: all syncable")
    else:
        print("result: action needed")
    for warning in result.all_warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if not args.no_open:
        ok, opened_path, warning = open_html_report(out_path)
        if opened_path != out_path:
            print(f"opened: {opened_path}")
        if warning:
            print(f"note: {warning}", file=sys.stderr)
        if not ok:
            print(
                f"warning: could not open browser; open the report manually: {opened_path}",
                file=sys.stderr,
            )

    return EXIT_OK if result.all_safe else EXIT_DIVERGED


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        code = cmd_check(args)
    else:
        parser.error(f"unknown command: {args.command}")
        return
    raise SystemExit(code)


if __name__ == "__main__":
    main()
