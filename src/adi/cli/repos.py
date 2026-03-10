"""Repository registry CLI commands."""

from __future__ import annotations

import argparse
import sys

from adi.engine.yaml_utils import dump_yaml
from adi.services.repos_service import ReposService


def register_repos_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("repos", help="Repository registry commands")
    repos_subparsers = parser.add_subparsers(dest="repos_command")

    list_parser = repos_subparsers.add_parser("list", help="List registered repositories")
    list_parser.set_defaults(handler=_handle_repos_list)


def _handle_repos_list(_args: argparse.Namespace) -> int:
    service = ReposService()
    try:
        print(dump_yaml(service.list_repos()))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
