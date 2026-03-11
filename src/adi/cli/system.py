"""System status CLI commands."""

from __future__ import annotations

import argparse
import sys

from adi.engine.yaml_utils import dump_yaml
from adi.services.system_service import SystemService


def register_system_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("system", help="System-wide ADI status")
    system_subparsers = parser.add_subparsers(dest="system_command")

    status_parser = system_subparsers.add_parser("status", help="Show global status")
    status_parser.set_defaults(handler=_handle_system_status)

    model_parser = system_subparsers.add_parser("model", help="Validate configured model runtime")
    model_parser.add_argument("--role", default="implementer", help="Model role to validate")
    model_parser.add_argument("--repo", required=False, help="Optional repo id for repo-specific overrides")
    model_parser.set_defaults(handler=_handle_system_model)


def _handle_system_status(_args: argparse.Namespace) -> int:
    service = SystemService()
    try:
        print(dump_yaml(service.status()))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _handle_system_model(args: argparse.Namespace) -> int:
    service = SystemService()
    try:
        payload = service.check_model(role=args.role, repo_id=args.repo)
        print(dump_yaml(payload))
        return 0 if payload.get("ready", False) else 1
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
