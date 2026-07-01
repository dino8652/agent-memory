# Claude Memory Wrapper

A local-only CLI wrapper for Claude Code that remembers repeated project failures and injects scoped lessons into future sessions.

Principle:

> Log generously, teach selectively.

Requires Python 3.11+ and Claude Code. Not yet published to PyPI — install from source.

## Quick Start

```bash
git clone <this-repo-url>
cd agent-memory
python3 -m pip install -e .
memory install-claude --global
```

Then just use Claude Code normally; hooks capture failures and corrections automatically.

Windows (PowerShell): use the same commands, or run the interpreter directly if
`python`/`pip` are not on PATH, e.g. `py -m pip install -e .`.

No pip? The library is pure standard-library Python, so you can run the tests and
even the CLI straight from a checkout without installing anything:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m agent_memory status
```

The global installer writes Claude Code skills and hooks under `~/.claude`, choosing
the right shell for the host OS (PowerShell on Windows, bash on macOS/Linux). Project
state stays local in each repository under `.agent-memory/` and is never committed.

`memory-claude` is still available as a convenience wrapper. It prepares memory before launching Claude and can remember a default project when launched from your home directory.
Hooks use that same default project when Claude Code starts from your home directory, so lessons stay attached to the intended project instead of `~`.

## Local Storage

SQLite is the source of truth:

```text
.agent-memory/
  config.json
  index.sqlite
  claude-context.md
  exports/
```

Default mode is local-only. Raw events are not intended to be committed.

## Commands

```bash
memory status
memory events
memory events --all
memory events --since 7d
memory lessons
memory lessons --export
memory recall "auth middleware failure"
memory review
memory why <lesson-id>
memory forget <lesson-id>
memory record-failure --command "npm test" --stderr "auth failed" --file src/auth/middleware.ts
memory record-correction "Do not trust cached session state" --file src/auth/middleware.ts
memory doctor
memory doctor --fix
memory install-claude --global
memory install-hooks
```

`memory record-failure` prints a recall block when an enabled lesson matches the failed command, stderr, or touched files.

`memory install-claude --global` writes user-level Claude Code hooks and skills to `~/.claude`, so any project opened by Claude can use `/agent-memory`, `/memory-status`, and `/memory-recall`.
It also installs review/control skills: `/memory-review`, `/memory-why`, and `/memory-teach`.
`/memory-doctor` runs the same checks as `memory doctor` and summarizes installation or hook problems.
`/memory-repair` runs `memory doctor --fix` to refresh hooks, skills, permissions, and project-local setup.
Doctor also checks that the default project pointer targets the current project, which keeps home-launched Claude sessions attached to the right memory store.
It checks both global Claude settings and project-local `.claude/settings.local.json` so stale local hooks or old Python-path permissions are visible and repairable.
It also verifies `.agent-memory/claude-context.md` is current, and `memory doctor --fix` regenerates it when lessons changed or the file went stale.

`memory install-hooks` writes project-local Claude Code hooks to `.claude/settings.local.json`. After restarting Claude Code, Bash tool failures are recorded automatically and matching lessons are returned to Claude as hook context. Correction-like user prompts are also logged as candidate memory evidence.
Failure hooks compare touched-file snapshots and edit generations between repeated failures. If the same failure repeats without relevant file changes, including command-only failures with no intervening edits, it is treated as low-signal flaky evidence instead of being promoted into a lesson.
Agent Memory ignores failed `memory ...`, `memory-claude ...`, and `python -m agent_memory ...` commands from its own slash commands so it does not learn noisy lessons about itself.

## Reliability

`memory-claude` fails open. If memory setup fails, it attempts to launch `claude` normally.

## V1 Collector Boundary

This version prepares context before Claude Code starts, supports explicit local event recording, and can install Claude Code hooks for automatic Bash failure/correction capture. Full transcript-level rejected-edit detection is still future work.
