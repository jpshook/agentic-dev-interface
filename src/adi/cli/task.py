"""Task CLI placeholder."""

from __future__ import annotations

import argparse


TASK_COMMANDS = ["list", "show", "approve", "run", "verify"]


def register_task_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("task", help="Task management")
    task_subparsers = parser.add_subparsers(dest="task_command")

    list_parser = task_subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument("--repo", required=False)
    list_parser.set_defaults(handler=_not_implemented)

    show_parser = task_subparsers.add_parser("show", help="Show task")
    show_parser.add_argument("task_id", nargs="?")
    show_parser.set_defaults(handler=_not_implemented)

    for command in ["approve", "run", "verify"]:
        cmd_parser = task_subparsers.add_parser(command, help=f"task {command}")
        cmd_parser.add_argument("task_id", nargs="?")
        cmd_parser.set_defaults(handler=_not_implemented)


def _not_implemented(_: argparse.Namespace) -> int:
    print("Task commands are not implemented in Phase 1-2")
    return 1
