# ADI (Agentic Dev Interface)

ADI is a local-first Python CLI for safe, repeatable, artifact-driven software development workflows.

This repository currently implements **Phase 1 + Phase 2** of the v1 spec:
- project bootstrap
- config loading and merge
- markdown + YAML frontmatter artifact parsing/writing
- artifact store
- repo onboarding and deterministic exploration
- `adi repo init/explore/info/doctor`

## Requirements

- Python 3.11+
- `git`

## Install (editable)

```bash
python -m pip install -e .[dev]
```

## CLI

```bash
adi repo init --path /absolute/path/to/repo
adi repo explore --repo <repo-id-or-name>
adi repo info --repo <repo-id-or-name>
adi repo doctor --repo <repo-id-or-name>
```

`spec`, `task`, and `backlog` command groups are scaffolded and intentionally stubbed in this slice.

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
- Policies/verifier/worktree/agent runner are scaffolded and will be expanded in later phases.
