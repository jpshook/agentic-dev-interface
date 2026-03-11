"""Task CLI commands."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from adi.engine.yaml_utils import dump_yaml
from adi.services.task_service import TaskService


def register_task_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("task", help="Task management")
    task_subparsers = parser.add_subparsers(dest="task_command")

    list_parser = task_subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument("--repo", required=True, help="Repo id or name")
    list_parser.set_defaults(handler=_handle_task_list)

    show_parser = task_subparsers.add_parser("show", help="Show task")
    show_parser.add_argument("task_id", help="Task id")
    show_parser.set_defaults(handler=_handle_task_show)

    approve_parser = task_subparsers.add_parser("approve", help="Approve task")
    approve_parser.add_argument("task_id", help="Task id")
    approve_parser.set_defaults(handler=_handle_task_approve)

    delete_parser = task_subparsers.add_parser("delete", help="Delete task and generated artifacts")
    delete_parser.add_argument("task_id", help="Task id")
    delete_parser.set_defaults(handler=_handle_task_delete)

    run_parser = task_subparsers.add_parser("run", help="Run task deterministically")
    run_parser.add_argument("task_id", help="Task id")
    run_parser.set_defaults(handler=_handle_task_run)

    verify_parser = task_subparsers.add_parser("verify", help="Verify task")
    verify_parser.add_argument("task_id", help="Task id")
    verify_parser.set_defaults(handler=_handle_task_verify)


def _handle_task_list(args: argparse.Namespace) -> int:
    return _run_with_errors(lambda service: service.list_tasks(args.repo))


def _handle_task_show(args: argparse.Namespace) -> int:
    return _run_with_errors(lambda service: service.show_task(args.task_id))


def _handle_task_approve(args: argparse.Namespace) -> int:
    return _run_with_errors(lambda service: service.approve_task(args.task_id))


def _handle_task_delete(args: argparse.Namespace) -> int:
    return _run_with_errors(lambda service: service.delete_task(args.task_id))


def _handle_task_run(args: argparse.Namespace) -> int:
    return _run_with_errors(lambda service: service.run_task(args.task_id))


def _handle_task_verify(args: argparse.Namespace) -> int:
    return _run_with_errors(lambda service: service.verify_task(args.task_id))


def _run_with_errors(fn: Any) -> int:
    service = TaskService()
    try:
        payload = fn(service)
        print(dump_yaml(payload))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
