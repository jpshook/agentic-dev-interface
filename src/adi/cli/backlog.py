"""Backlog CLI commands."""

from __future__ import annotations

import argparse
import sys

from adi.engine.yaml_utils import dump_yaml
from adi.services.backlog_service import BacklogService


def register_backlog_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("backlog", help="Backlog commands")
    backlog_subparsers = parser.add_subparsers(dest="backlog_command")

    show_parser = backlog_subparsers.add_parser("show", help="Show repo backlog status")
    show_parser.add_argument("--repo", required=False, help="Repo id or name")
    show_parser.set_defaults(handler=_handle_backlog_show)

    run_parser = backlog_subparsers.add_parser("run", help="Run eligible backlog tasks")
    run_parser.add_argument("--repo", required=False, help="Repo id or name")
    run_parser.add_argument("--max-tasks", type=int, required=False, help="Max tasks to dispatch")
    run_parser.add_argument(
        "--time-limit-seconds",
        type=int,
        required=False,
        help="Max scheduler runtime in seconds",
    )
    run_parser.set_defaults(handler=_handle_backlog_run)


def _handle_backlog_show(args: argparse.Namespace) -> int:
    service = BacklogService()
    try:
        payload = service.show(repo_ref=args.repo)
        print(dump_yaml(payload))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _handle_backlog_run(args: argparse.Namespace) -> int:
    service = BacklogService()
    try:
        payload = service.run(
            repo_ref=args.repo,
            max_tasks=args.max_tasks,
            time_limit_seconds=args.time_limit_seconds,
        )
        print(dump_yaml(payload))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
