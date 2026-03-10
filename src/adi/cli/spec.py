"""Spec CLI commands."""

from __future__ import annotations

import argparse
import sys

from adi.engine.yaml_utils import dump_yaml
from adi.services.spec_service import SpecService


def register_spec_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("spec", help="Spec management")
    spec_subparsers = parser.add_subparsers(dest="spec_command")

    create_parser = spec_subparsers.add_parser("create", help="Create spec artifact")
    create_parser.add_argument("--repo", required=True, help="Repo id or name")
    create_parser.add_argument("--title", required=True, help="Spec title")
    create_parser.add_argument("--execution-mode", default="manual", help="manual|approval_required|auto_safe")
    create_parser.add_argument("--id", required=False, help="Optional spec id")
    create_parser.add_argument("--priority", default="medium", help="Spec priority")
    create_parser.set_defaults(handler=_handle_spec_create)

    analyze_parser = spec_subparsers.add_parser("analyze", help="Analyze spec")
    analyze_parser.add_argument("spec_id", help="Spec id")
    analyze_parser.set_defaults(handler=_handle_spec_analyze)

    decompose_parser = spec_subparsers.add_parser("decompose", help="Generate tasks from spec")
    decompose_parser.add_argument("spec_id", help="Spec id")
    decompose_parser.set_defaults(handler=_handle_spec_decompose)

    approve_parser = spec_subparsers.add_parser("approve", help="Approve decomposed spec")
    approve_parser.add_argument("spec_id", help="Spec id")
    approve_parser.set_defaults(handler=_handle_spec_approve)

    run_parser = spec_subparsers.add_parser("run", help="Run spec workflow and optional execution")
    run_parser.add_argument("spec_id", help="Spec id")
    run_parser.add_argument("--max-tasks", type=int, required=False, help="Max tasks to run")
    run_parser.add_argument("--time-limit-seconds", type=int, required=False, help="Backlog time limit")
    run_parser.set_defaults(handler=_handle_spec_run)

    status_parser = spec_subparsers.add_parser("status", help="Show spec status")
    status_parser.add_argument("spec_id", help="Spec id")
    status_parser.set_defaults(handler=_handle_spec_status)


def _handle_spec_create(args: argparse.Namespace) -> int:
    service = SpecService()
    return _run_with_errors(
        lambda: service.create_spec(
            repo_ref=args.repo,
            title=args.title,
            execution_mode=args.execution_mode,
            spec_id=args.id,
            priority=args.priority,
        )
    )


def _handle_spec_analyze(args: argparse.Namespace) -> int:
    service = SpecService()
    return _run_with_errors(lambda: service.analyze_spec(args.spec_id))


def _handle_spec_decompose(args: argparse.Namespace) -> int:
    service = SpecService()
    return _run_with_errors(lambda: service.decompose_spec(args.spec_id))


def _handle_spec_approve(args: argparse.Namespace) -> int:
    service = SpecService()
    return _run_with_errors(lambda: service.approve_spec(args.spec_id))


def _handle_spec_run(args: argparse.Namespace) -> int:
    service = SpecService()
    return _run_with_errors(
        lambda: service.run_spec(
            args.spec_id,
            max_tasks=args.max_tasks,
            time_limit_seconds=args.time_limit_seconds,
        )
    )


def _handle_spec_status(args: argparse.Namespace) -> int:
    service = SpecService()
    return _run_with_errors(lambda: service.spec_status(args.spec_id))


def _run_with_errors(fn):
    try:
        payload = fn()
        print(dump_yaml(payload))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
