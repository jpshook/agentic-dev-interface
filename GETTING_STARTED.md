# Getting Started With ADI

ADI is a local-first CLI for turning repository artifacts into a repeatable workflow:

1. register a git repository
2. explore it to capture metadata and verification commands
3. create a spec
4. decompose that spec into tasks
5. approve and run those tasks

This guide walks through the shortest useful path from install to first run.

## Requirements

- Python 3.11+
- `git`

## Install

From this repository:

```bash
python -m pip install -e '.[dev]'
```

Verify the CLI is available:

```bash
adi --help
```

## Understand Where ADI Stores Data

ADI writes its state to `~/.adi` by default.

You can override that location for testing or isolated runs:

```bash
export ADI_HOME=/absolute/path/to/.adi
```

Expected layout:

```text
~/.adi/
  config/
  repos/
  runs/
  logs/
  cache/
  templates/
```

## Step 1: Check Global Status

This initializes default config files if needed and shows what ADI currently knows about your system.

```bash
adi system status
```

Important defaults:

- Model runtimes default to `stub`, which is safe for local setup and tests.
- Worktrees default to `~/agent-worktrees`.
- Verification checks default to `test`, `lint`, `typecheck`, and `build`.

## Step 2: Register a Repository

Point ADI at an existing git repository:

```bash
adi repo init --path /absolute/path/to/repo
```

The command returns YAML containing the new repo id. You will use that id in later commands.

## Step 3: Explore the Repository

Exploration inspects the repo and writes metadata into ADI's artifact store.

```bash
adi repo explore --repo <repo-id>
```

Useful follow-up commands:

```bash
adi repo info --repo <repo-id>
adi repo doctor --repo <repo-id>
adi repos list
```

After exploration, inspect `repo.md` under:

```text
~/.adi/repos/<repo-id>/repo.md
```

That artifact records detected language, stack, package manager, and verification commands.

## Step 4: Create Your First Spec

Create a spec attached to the repository:

```bash
adi spec create --repo <repo-id> --title "Add API validation" --id SP-001 --execution-mode manual
```

Execution modes:

- `manual`: create artifacts only; you decide when to move forward
- `approval_required`: tasks need explicit approval before execution
- `auto_safe`: ADI can auto-approve low-risk generated tasks and hand them to backlog execution

The spec artifact is written under:

```text
~/.adi/repos/<repo-id>/specs/SP-001.md
```

Edit the spec body to add implementation details, acceptance criteria, and open questions before continuing.

## Step 5: Analyze and Decompose the Spec

Run the planning steps:

```bash
adi spec analyze SP-001
adi spec decompose SP-001
adi spec status SP-001
```

This produces task artifacts under:

```text
~/.adi/repos/<repo-id>/tasks/
```

If the spec still has unresolved ambiguity, keep editing the spec and rerun the planning commands.

## Step 6: Approve and Run Tasks

For a manual or approval-based flow:

```bash
adi task list --repo <repo-id>
adi task show <task-id>
adi task approve <task-id>
adi task run <task-id>
adi task verify <task-id>
```

What `adi task run` does:

1. checks policy and task state
2. creates a worktree
3. builds an implementer prompt
4. runs the configured model runtime
5. executes verification checks
6. records run artifacts

Run outputs are stored under:

```text
~/.adi/runs/<run-id>/
```

## Step 7: Use Backlog or Spec Automation

Once tasks exist, you can let ADI rank and dispatch eligible work:

```bash
adi backlog show --repo <repo-id>
adi backlog run --repo <repo-id>
```

Or run the full spec workflow:

```bash
adi spec run SP-001
```

For `auto_safe` specs, `adi spec run` can analyze, decompose, approve low-risk tasks, and hand them off to the backlog automatically.

## Configure a Real Runtime

By default, `models.yaml` uses `runtime: stub`, which is useful for smoke tests but does not perform real implementation work.

Start from the example config:

```bash
cp examples/config/models.yaml ~/.adi/config/models.yaml
```

Then update it with the runtime and command you want ADI to invoke.

Related example configs:

- `examples/config/adi.yaml`
- `examples/config/models.yaml`
- `examples/config/policies.yaml`
- `examples/config/repos.yaml`

## Common First-Run Checks

If something looks wrong, these are the fastest checks:

```bash
adi system status
adi repo doctor --repo <repo-id>
adi repo info --repo <repo-id>
```

Check that:

- the target path is a valid git repository
- the repo was explored after registration
- `repo.md` contains usable verification commands
- your `ADI_HOME` is the one you expect
- your model runtime is configured if you expect real implementation

## Minimal Happy Path

If you just want the shortest possible sequence:

```bash
python -m pip install -e '.[dev]'
adi system status
adi repo init --path /absolute/path/to/repo
adi repo explore --repo <repo-id>
adi spec create --repo <repo-id> --title "Add feature" --id SP-001 --execution-mode manual
adi spec analyze SP-001
adi spec decompose SP-001
adi task list --repo <repo-id>
adi task approve <task-id>
adi task run <task-id>
```

If you use `zsh`, keep the quotes around `'.[dev]'` so the shell passes the package extra through to `pip` unchanged.
