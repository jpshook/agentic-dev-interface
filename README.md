# ADI (Agentic Dev Interface)

ADI is a local-first Python CLI for safe, repeatable, artifact-driven software development workflows.

Start with the getting started guide: [GETTING_STARTED.md](/Users/jpshook/Code/agentic-dev-interface/GETTING_STARTED.md)

This repository currently implements:
- project bootstrap
- config loading and merge
- markdown + YAML frontmatter artifact parsing/writing
- artifact store
- repo onboarding and deterministic exploration
- `adi repo init/explore/info/doctor`
- task lifecycle validation and transitions
- deterministic task execution pipeline with locks, worktrees, verification, and run artifacts
- prompt generation and model-agnostic agent runner integration
- implementer retry loop (`verification_fix_cycles` / `total_task_attempts`)
- `adi task list/show/approve/run/verify`
- backlog scheduling, ranking, dependency gating, and worker dispatch
- `adi backlog show/run`
- spec lifecycle analysis/decomposition/approval/run/status workflows
- deterministic spec-to-task planning with dependency graph generation
- cross-repo orchestration with dependency-aware dispatch
- `adi spec create/analyze/decompose/approve/run/status/repos`
- `adi repos list`
- `adi system status`

## Requirements

- Python 3.11+
- `git`

## Install (editable)

```bash
python -m pip install -e '.[dev]'
```

If you use `zsh`, keep the quotes around `'.[dev]'` so the shell does not treat it as a glob pattern.

## Claude Code Setup

ADI can use Claude Code as its shell-backed model runtime.

Install and authenticate Claude Code:

```bash
npm install -g @anthropic-ai/claude-code
claude
```

Then copy the example model config:

```bash
cp /Users/jpshook/Code/agentic-dev-interface/examples/config/models.yaml ~/.adi/config/models.yaml
adi system model
```

The example config uses Claude Code in non-interactive mode for the `implementer` and `reviewer` roles.

## CLI

```bash
adi repo init --path /absolute/path/to/repo
adi repo explore --repo <repo-id-or-name>
adi repo info --repo <repo-id-or-name>
adi repo doctor --repo <repo-id-or-name>
adi repo delete --repo <repo-id-or-name>
adi repos list
adi task list --repo <repo-id-or-name>
adi task show <task-id>
adi task approve <task-id>
adi task delete <task-id>
adi task run <task-id>
adi task verify <task-id>
adi backlog show --repo <repo-id-or-name>
adi backlog run --repo <repo-id-or-name>
adi spec create --repo <repo-id-or-name> --title "<title>" [--execution-mode manual|approval_required|auto_safe]
adi spec analyze <spec-id>
adi spec decompose <spec-id>
adi spec approve <spec-id>
adi spec delete <spec-id>
adi spec status <spec-id>
adi spec repos <spec-id>
adi spec run <spec-id>
adi system status
adi system model
```

## Agent Runtime (Phase 4)

`adi task run <task-id>` now executes:

1. policy + state checks
2. worktree creation
3. implementer prompt generation
4. agent execution (stub or shell runtime)
5. verification checks
6. retry loop on failed verification
7. run artifact recording + task state update

Prompt templates live at:
- `/Users/jpshook/Code/agentic-dev-interface/src/adi/templates/prompts/implementer.md`
- `/Users/jpshook/Code/agentic-dev-interface/src/adi/templates/prompts/reviewer.md`

Override prompts by placing templates in `~/.adi/templates/prompts/`.

## Backlog Orchestration (Phase 5)

`adi backlog run` orchestrates repository tasks by:

1. loading tasks from `~/.adi/repos/<repo>/tasks`
2. filtering eligible tasks (`approved`, dependencies satisfied, policy `auto_execute`)
3. ranking with deterministic heuristics (priority, size, dependency count, creation time)
4. dispatching tasks through a worker pool
5. running each task via the Phase 4 task execution loop
6. writing backlog run summary artifacts under `~/.adi/runs/<run-id>/`

Concurrency controls are configured in `adi.yaml`:
- `execution.max_active_runs_global`
- `execution.max_active_runs_per_repo`

## Spec Planning + Orchestration (Phase 6-7)

`adi spec run <spec-id>` supports:

1. spec analysis (`draft -> analyzed`)
2. deterministic decomposition (`analyzed -> decomposed`)
3. task artifact generation with dependencies and acceptance checks
4. approval + backlog handoff based on execution mode
5. multi-repo orchestration with cross-repo dependency ordering

Execution modes:
- `manual`: analyze/decompose only
- `approval_required`: requires explicit `adi spec approve` before execution
- `auto_safe`: auto-approve generated tasks and hand off to backlog execution

## ADI Home Layout

By default ADI writes state to `~/.adi` (override with `ADI_HOME`).

```text
~/.adi/
  config/
    adi.yaml
    policies.yaml
    models.yaml
    repos.yaml
  repos/
    <repo-id>/
      repo.md
      specs/
      tasks/
      backlog/
      explore/
      state/
  runs/
  logs/
  cache/
  templates/
```

## Example Generated `repo.md`

```markdown
---
id: demo-repo
name: demo-repo
root: /Users/example/src/demo-repo
default_branch: main
status: active
commands:
  test: pytest -q
  lint: ruff check .
  typecheck: mypy .
  build: python -m build
language: python
stack:
- python
package_manager: pip
last_explored_at: '2026-03-10T00:00:00+00:00'
---
# Repository demo-repo

Root: `/Users/example/src/demo-repo`
Language: `python`
Stack: `python`
Package manager: `pip`

## Verification Commands

- `build`: `python -m build`
- `lint`: `ruff check .`
- `test`: `pytest -q`
- `typecheck`: `mypy .`
```

## Running Tests

```bash
pytest
```

## Notes

- Frontmatter round-tripping preserves unknown fields.
- Repo detection is deterministic and currently supports Node/TypeScript, Python, Go, and Rust.
- Task execution remains deterministic and policy-gated.
- Agent-assisted implementation is now supported through a model-agnostic runner.
- Run outputs are recorded under `~/.adi/runs/<run-id>/` for debugging/auditability.
- Default model runtime is `stub`; configure `models.yaml` with `runtime: shell` and `command` for active implementation behavior.
