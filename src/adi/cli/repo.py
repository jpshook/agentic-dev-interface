"""Repo command handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from adi.engine.yaml_utils import dump_yaml
from adi.services.repo_service import RepoService


def register_repo_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("repo", help="Repository onboarding and diagnostics")
    repo_subparsers = parser.add_subparsers(dest="repo_command")

    init_parser = repo_subparsers.add_parser("init", help="Initialize a repository in ADI")
    init_parser.add_argument("--path", required=True, help="Path to target repository")
    init_parser.set_defaults(handler=_handle_repo_init)

    explore_parser = repo_subparsers.add_parser("explore", help="Explore a registered repository")
    explore_parser.add_argument("--repo", required=True, help="Repo id or name")
    explore_parser.set_defaults(handler=_handle_repo_explore)

    info_parser = repo_subparsers.add_parser("info", help="Show repository metadata")
    info_parser.add_argument("--repo", required=True, help="Repo id or name")
    info_parser.set_defaults(handler=_handle_repo_info)

    doctor_parser = repo_subparsers.add_parser("doctor", help="Run repository health checks")
    doctor_parser.add_argument("--repo", required=True, help="Repo id or name")
    doctor_parser.set_defaults(handler=_handle_repo_doctor)


def _handle_repo_init(args: argparse.Namespace) -> int:
    service = RepoService()
    result = service.init_repo(Path(args.path))
    _print_yaml({"repo": result})
    return 0


def _handle_repo_explore(args: argparse.Namespace) -> int:
    service = RepoService()
    result = service.explore_repo(args.repo)
    _print_yaml(result)
    return 0


def _handle_repo_info(args: argparse.Namespace) -> int:
    service = RepoService()
    result = service.repo_info(args.repo)
    _print_yaml(result)
    return 0


def _handle_repo_doctor(args: argparse.Namespace) -> int:
    service = RepoService()
    result = service.repo_doctor(args.repo)
    _print_yaml(result)
    return 0


def _print_yaml(data: dict[str, Any]) -> None:
    print(dump_yaml(data))
