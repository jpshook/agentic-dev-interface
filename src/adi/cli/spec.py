"""Spec CLI placeholder."""

from __future__ import annotations

import argparse


SPEC_COMMANDS = ["create", "analyze", "decompose", "approve"]


def register_spec_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("spec", help="Spec management")
    spec_subparsers = parser.add_subparsers(dest="spec_command")
    for command in SPEC_COMMANDS:
        cmd_parser = spec_subparsers.add_parser(command, help=f"spec {command}")
        if command == "create":
            cmd_parser.add_argument("--repo", required=False)
        else:
            cmd_parser.add_argument("spec_id", nargs="?")
        cmd_parser.set_defaults(handler=_not_implemented)


def _not_implemented(_: argparse.Namespace) -> int:
    print("Spec commands are not implemented in Phase 1-2")
    return 1
