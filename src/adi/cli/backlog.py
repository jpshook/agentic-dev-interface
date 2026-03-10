"""Backlog CLI placeholder."""

from __future__ import annotations

import argparse


def register_backlog_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("backlog", help="Backlog commands")
    backlog_subparsers = parser.add_subparsers(dest="backlog_command")

    show_parser = backlog_subparsers.add_parser("show", help="Show repo backlog")
    show_parser.add_argument("--repo", required=False)
    show_parser.set_defaults(handler=_not_implemented)


def _not_implemented(_: argparse.Namespace) -> int:
    print("Backlog commands are not implemented in Phase 1-2")
    return 1
