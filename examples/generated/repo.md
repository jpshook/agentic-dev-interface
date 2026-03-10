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
Explored at: `2026-03-10T00:00:00+00:00`

## Verification Commands

- `build`: `python -m build`
- `lint`: `ruff check .`
- `test`: `pytest -q`
- `typecheck`: `mypy .`
