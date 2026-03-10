"""ADI CLI entrypoint."""

from __future__ import annotations

import argparse
from typing import Sequence

from .backlog import register_backlog_commands
from .repo import register_repo_commands
from .spec import register_spec_commands
from .task import register_task_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adi", description="Agentic Dev Interface")
    subparsers = parser.add_subparsers(dest="command")

    register_repo_commands(subparsers)
    register_spec_commands(subparsers)
    register_task_commands(subparsers)
    register_backlog_commands(subparsers)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
