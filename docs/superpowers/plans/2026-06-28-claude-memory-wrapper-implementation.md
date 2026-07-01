# Claude Memory Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only Python CLI wrapper for Claude Code that stores failure memory in SQLite, generates `.agent-memory/claude-context.md`, and exposes inspectable memory controls.

**Architecture:** The CLI has two entry points: `memory` for control commands and `memory-claude` for the wrapper. SQLite is the source of truth; generated files are projections. The extractor logs raw events generously but only promotes lessons through manual approval or repeat threshold.

**Tech Stack:** Python 3.11+, stdlib `sqlite3`, `argparse`, `subprocess`, `pathlib`, `json`, `unittest`, optional editable install through `pyproject.toml`.

---

## File Structure

- Create: `pyproject.toml` - package metadata and console scripts.
- Create: `src/agent_memory/__init__.py` - package version.
- Create: `src/agent_memory/__main__.py` - allows `python -m agent_memory`.
- Create: `src/agent_memory/cli.py` - `memory` command parser and subcommand handlers.
- Create: `src/agent_memory/wrapper.py` - `memory-claude` pre-launch flow and fail-open session handling.
- Create: `src/agent_memory/paths.py` - project root and `.agent-memory` path helpers.
- Create: `src/agent_memory/config.py` - config schema, defaults, load/save.
- Create: `src/agent_memory/db.py` - SQLite connection, schema migration, repository methods.
- Create: `src/agent_memory/context.py` - `CLAUDE.md` pointer and `claude-context.md` renderer.
- Create: `src/agent_memory/redaction.py` - v1 secret redaction.
- Create: `src/agent_memory/extractor.py` - normalization, signal checks, clustering, scoring, promotion.
- Create: `tests/test_config.py` - config and init tests.
- Create: `tests/test_context.py` - context rendering and idempotent pointer tests.
- Create: `tests/test_db.py` - schema and repository tests.
- Create: `tests/test_extractor.py` - redaction, signal, clustering, promotion tests.
- Create: `tests/test_cli.py` - command behavior tests using temp projects.
- Create: `tests/test_wrapper.py` - wrapper session cleanup and fail-open tests.
- Create: `README.md` - local usage notes.

---

### Task 1: Package Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/agent_memory/__init__.py`
- Create: `src/agent_memory/__main__.py`
- Create: `src/agent_memory/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI smoke tests**

```python
# tests/test_cli.py
from agent_memory.cli import build_parser


def test_parser_has_init_command():
    parser = build_parser()
    args = parser.parse_args(["init"])
    assert args.command == "init"


def test_parser_has_events_default_limit():
    parser = build_parser()
    args = parser.parse_args(["events"])
    assert args.command == "events"
    assert args.limit == 20
    assert args.all is False
```

- [ ] **Step 2: Run the failing test**

Run: `python -m unittest discover -s tests -p "test_cli.py" -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_memory'`.

- [ ] **Step 3: Add package metadata and minimal parser**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "agent-memory"
version = "0.1.0"
description = "Local Claude Code memory wrapper"
requires-python = ">=3.11"

[project.scripts]
memory = "agent_memory.cli:main"
memory-claude = "agent_memory.wrapper:main"

[tool.setuptools.packages.find]
where = ["src"]
```

```python
# src/agent_memory/__init__.py
__version__ = "0.1.0"
```

```python
# src/agent_memory/__main__.py
from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# src/agent_memory/cli.py
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("status")
    subparsers.add_parser("lessons")
    events = subparsers.add_parser("events")
    events.add_argument("--all", action="store_true")
    events.add_argument("--since")
    events.add_argument("--limit", type=int, default=20)

    recall = subparsers.add_parser("recall")
    recall.add_argument("query")

    approve = subparsers.add_parser("approve")
    approve.add_argument("candidate_id")

    reject = subparsers.add_parser("reject")
    reject.add_argument("candidate_id")

    forget = subparsers.add_parser("forget")
    forget.add_argument("lesson_id")

    why = subparsers.add_parser("why")
    why.add_argument("lesson_id")

    subparsers.add_parser("config")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0
```

```python
# src/agent_memory/wrapper.py
from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    return 0
```

- [ ] **Step 4: Install editable package and verify the test passes**

Run:

```bash
python -m pip install -e .
python -m unittest discover -s tests -p "test_cli.py" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

If the workspace has a git repo, run:

```bash
git add pyproject.toml src tests
git commit -m "chore: scaffold agent memory cli"
```

If there is no git repo, record this checkpoint in the final status instead of committing.

---

### Task 2: Config, Paths, And Init

**Files:**
- Create: `src/agent_memory/paths.py`
- Create: `src/agent_memory/config.py`
- Modify: `src/agent_memory/cli.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config/init tests**

```python
# tests/test_config.py
import json
import tempfile
import unittest
from pathlib import Path

from agent_memory.config import DEFAULT_CONFIG, init_project, load_config


class ConfigTests(unittest.TestCase):
    def test_init_project_writes_default_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)

            config_path = root / ".agent-memory" / "config.json"
            self.assertTrue(config_path.exists())
            self.assertEqual(config["git_mode"], "local_only")
            self.assertEqual(config["repeat_threshold"], 2)
            self.assertEqual(config["max_lessons_injected"], 10)
            self.assertEqual(config["max_context_tokens"], 800)
            self.assertEqual(config["min_signal_threshold"], 0.4)
            self.assertEqual(load_config(root), config)

    def test_init_project_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = init_project(root, git_mode="commit_lessons")
            second = init_project(root)
            self.assertEqual(second["project_id"], first["project_id"])
            self.assertEqual(second["git_mode"], "commit_lessons")

    def test_default_config_has_expected_keys(self):
        self.assertEqual(
            sorted(DEFAULT_CONFIG.keys()),
            [
                "git_mode",
                "max_context_tokens",
                "max_lessons_injected",
                "min_signal_threshold",
                "project_id",
                "repeat_threshold",
                "version",
            ],
        )
```

- [ ] **Step 2: Run the failing test**

Run: `python -m unittest discover -s tests -p "test_config.py" -v`

Expected: FAIL with `ModuleNotFoundError` for `agent_memory.config`.

- [ ] **Step 3: Implement paths and config**

```python
# src/agent_memory/paths.py
from __future__ import annotations

from pathlib import Path


MEMORY_DIR = ".agent-memory"


def project_root(start: Path | None = None) -> Path:
    return (start or Path.cwd()).resolve()


def memory_dir(root: Path) -> Path:
    return root / MEMORY_DIR


def config_path(root: Path) -> Path:
    return memory_dir(root) / "config.json"


def db_path(root: Path) -> Path:
    return memory_dir(root) / "index.sqlite"


def context_path(root: Path) -> Path:
    return memory_dir(root) / "claude-context.md"
```

```python
# src/agent_memory/config.py
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .paths import config_path, memory_dir


DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "project_id": "",
    "git_mode": "local_only",
    "repeat_threshold": 2,
    "max_lessons_injected": 10,
    "max_context_tokens": 800,
    "min_signal_threshold": 0.4,
}


def init_project(root: Path, git_mode: str = "local_only") -> dict[str, Any]:
    memory_dir(root).mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    if path.exists():
        return load_config(root)

    config = dict(DEFAULT_CONFIG)
    config["project_id"] = f"proj_{uuid.uuid4().hex[:12]}"
    config["git_mode"] = git_mode
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def load_config(root: Path) -> dict[str, Any]:
    path = config_path(root)
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Wire `memory init`**

```python
# src/agent_memory/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from .config import init_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--git-mode", choices=["local_only", "commit_lessons"], default="local_only")

    subparsers.add_parser("status")
    subparsers.add_parser("lessons")
    events = subparsers.add_parser("events")
    events.add_argument("--all", action="store_true")
    events.add_argument("--since")
    events.add_argument("--limit", type=int, default=20)

    recall = subparsers.add_parser("recall")
    recall.add_argument("query")
    approve = subparsers.add_parser("approve")
    approve.add_argument("candidate_id")
    reject = subparsers.add_parser("reject")
    reject.add_argument("candidate_id")
    forget = subparsers.add_parser("forget")
    forget.add_argument("lesson_id")
    why = subparsers.add_parser("why")
    why.add_argument("lesson_id")
    subparsers.add_parser("config")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        config = init_project(Path.cwd(), git_mode=args.git_mode)
        print(f"Initialized .agent-memory for {config['project_id']}")
    return 0
```

- [ ] **Step 5: Run tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_memory/paths.py src/agent_memory/config.py src/agent_memory/cli.py tests/test_config.py
git commit -m "feat: add local project config"
```

---

### Task 3: SQLite Schema And Repository

**Files:**
- Create: `src/agent_memory/db.py`
- Modify: `src/agent_memory/config.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing database tests**

```python
# tests/test_db.py
import tempfile
import unittest
from pathlib import Path

from agent_memory.config import init_project
from agent_memory.db import MemoryDb


class DbTests(unittest.TestCase):
    def test_migrate_creates_core_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            db = MemoryDb.open(root)
            tables = db.table_names()
            self.assertIn("projects", tables)
            self.assertIn("sessions", tables)
            self.assertIn("raw_events", tables)
            self.assertIn("candidate_patterns", tables)
            self.assertIn("lessons", tables)
            self.assertIn("injections", tables)

    def test_session_lifecycle_marks_previous_started_failed_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            first = db.start_session(config["project_id"], "claude")
            second = db.cleanup_open_sessions(config["project_id"])
            row = db.get_session(first)
            self.assertEqual(row["status"], "failed_open")
            self.assertIsNotNone(row["ended_at"])
            self.assertEqual(second, 1)

    def test_insert_raw_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="failed_command",
                source="manual",
                summary="npm test failed",
                command="npm test",
                exit_code=1,
                stderr_excerpt="expected 200 got 401",
                user_text=None,
                files_touched=["src/auth/middleware.ts"],
                file_change_state="unknown",
            )
            event = db.get_raw_event(event_id)
            self.assertEqual(event["event_type"], "failed_command")
            self.assertEqual(event["command"], "npm test")
```

- [ ] **Step 2: Run the failing database tests**

Run: `python -m unittest discover -s tests -p "test_db.py" -v`

Expected: FAIL with `ModuleNotFoundError` for `agent_memory.db`.

- [ ] **Step 3: Implement SQLite schema and repository**

```python
# src/agent_memory/db.py
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import db_path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryDb:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, root: Path) -> "MemoryDb":
        path = db_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = cls(sqlite3.connect(path))
        db.migrate()
        return db

    def migrate(self) -> None:
        self.conn.executescript(
            """
            create table if not exists projects (
              id text primary key,
              root_path text not null,
              repo_remote_hash text,
              project_type text,
              created_at text not null,
              updated_at text not null
            );
            create table if not exists sessions (
              id text primary key,
              project_id text not null,
              started_at text not null,
              ended_at text,
              claude_command text,
              status text not null
            );
            create table if not exists raw_events (
              id text primary key,
              project_id text not null,
              session_id text,
              event_type text not null,
              source text not null,
              summary text not null,
              command text,
              exit_code integer,
              stderr_excerpt text,
              user_text text,
              files_touched_json text not null,
              file_change_state text,
              created_at text not null
            );
            create table if not exists candidate_patterns (
              id text primary key,
              project_id text not null,
              title text not null,
              failure_pattern text not null,
              suspected_cause text not null,
              recommended_fix text not null,
              scope_json text not null,
              trigger_json text not null,
              supporting_event_ids_json text not null,
              repeat_count integer not null,
              confidence_score real not null,
              status text not null,
              merged_into_lesson_id text,
              created_at text not null,
              updated_at text not null,
              last_seen text not null
            );
            create table if not exists lessons (
              id text primary key,
              project_id text not null,
              title text not null,
              lesson text not null,
              scope_json text not null,
              trigger_json text not null,
              project_type text,
              confidence text not null,
              confidence_score real not null,
              promotion_reason text not null,
              supporting_event_ids_json text not null,
              created_at text not null,
              updated_at text not null,
              last_seen text not null,
              validated_at text,
              disabled_at text
            );
            create table if not exists injections (
              id text primary key,
              project_id text not null,
              session_id text,
              lesson_id text not null,
              injection_type text not null,
              reason text not null,
              created_at text not null
            );
            """
        )
        self.conn.commit()

    def table_names(self) -> set[str]:
        rows = self.conn.execute("select name from sqlite_master where type='table'").fetchall()
        return {row["name"] for row in rows}

    def ensure_project(self, project_id: str, root: Path, project_type: str | None = None) -> None:
        timestamp = now_iso()
        self.conn.execute(
            """
            insert into projects (id, root_path, project_type, created_at, updated_at)
            values (?, ?, ?, ?, ?)
            on conflict(id) do update set root_path=excluded.root_path, updated_at=excluded.updated_at
            """,
            (project_id, str(root), project_type, timestamp, timestamp),
        )
        self.conn.commit()

    def start_session(self, project_id: str, claude_command: str) -> str:
        session_id = f"ses_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        self.conn.execute(
            "insert into sessions (id, project_id, started_at, claude_command, status) values (?, ?, ?, ?, ?)",
            (session_id, project_id, now_iso(), claude_command, "started"),
        )
        self.conn.commit()
        return session_id

    def cleanup_open_sessions(self, project_id: str) -> int:
        timestamp = now_iso()
        cursor = self.conn.execute(
            "update sessions set status='failed_open', ended_at=? where project_id=? and status='started'",
            (timestamp, project_id),
        )
        self.conn.commit()
        return cursor.rowcount

    def finish_session(self, session_id: str, status: str) -> None:
        self.conn.execute(
            "update sessions set status=?, ended_at=? where id=?",
            (status, now_iso(), session_id),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> dict[str, Any]:
        row = self.conn.execute("select * from sessions where id=?", (session_id,)).fetchone()
        return dict(row)

    def insert_raw_event(
        self,
        *,
        project_id: str,
        session_id: str | None,
        event_type: str,
        source: str,
        summary: str,
        command: str | None,
        exit_code: int | None,
        stderr_excerpt: str | None,
        user_text: str | None,
        files_touched: list[str],
        file_change_state: str,
    ) -> str:
        event_id = f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        self.conn.execute(
            """
            insert into raw_events
            (id, project_id, session_id, event_type, source, summary, command, exit_code,
             stderr_excerpt, user_text, files_touched_json, file_change_state, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                project_id,
                session_id,
                event_type,
                source,
                summary,
                command,
                exit_code,
                stderr_excerpt,
                user_text,
                json.dumps(files_touched),
                file_change_state,
                now_iso(),
            ),
        )
        self.conn.commit()
        return event_id

    def get_raw_event(self, event_id: str) -> dict[str, Any]:
        row = self.conn.execute("select * from raw_events where id=?", (event_id,)).fetchone()
        return dict(row)
```

- [ ] **Step 4: Run database tests**

Run: `python -m unittest discover -s tests -p "test_db.py" -v`

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_memory/db.py tests/test_db.py
git commit -m "feat: add memory sqlite store"
```

---

### Task 4: CLAUDE Pointer And Context Rendering

**Files:**
- Create: `src/agent_memory/context.py`
- Modify: `src/agent_memory/db.py`
- Test: `tests/test_context.py`

- [ ] **Step 1: Write failing context tests**

```python
# tests/test_context.py
import tempfile
import unittest
from pathlib import Path

from agent_memory.config import init_project
from agent_memory.context import POINTER, ensure_claude_pointer, render_context
from agent_memory.db import MemoryDb


class ContextTests(unittest.TestCase):
    def test_pointer_appends_once_at_bottom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude = root / "CLAUDE.md"
            claude.write_text("# Project\n\nKeep this first.\n", encoding="utf-8")

            ensure_claude_pointer(root)
            ensure_claude_pointer(root)

            text = claude.read_text(encoding="utf-8")
            self.assertEqual(text.count(POINTER), 1)
            self.assertTrue(text.rstrip().endswith(POINTER))

    def test_render_context_includes_enabled_lessons_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            db.insert_lesson(
                project_id=config["project_id"],
                title="Auth Middleware",
                lesson="Verify the user directly before authorization checks.",
                scope={"files": ["src/auth/**"]},
                trigger={"errors": ["session"]},
                project_type="next.js",
                confidence="medium",
                confidence_score=0.7,
                promotion_reason="manual_approval",
                supporting_event_ids=["evt_1"],
            )

            path = render_context(root, db, config)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Learned Failure Patterns", text)
            self.assertIn("Auth Middleware", text)
            self.assertIn("Verify the user directly", text)
            self.assertIn("Lesson ID:", text)
```

- [ ] **Step 2: Run failing context tests**

Run: `python -m unittest discover -s tests -p "test_context.py" -v`

Expected: FAIL with `ModuleNotFoundError` for `agent_memory.context` and missing `insert_lesson`.

- [ ] **Step 3: Add lesson repository methods**

Add these methods to `src/agent_memory/db.py`:

```python
    def insert_lesson(
        self,
        *,
        project_id: str,
        title: str,
        lesson: str,
        scope: dict[str, Any],
        trigger: dict[str, Any],
        project_type: str | None,
        confidence: str,
        confidence_score: float,
        promotion_reason: str,
        supporting_event_ids: list[str],
    ) -> str:
        lesson_id = f"les_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        timestamp = now_iso()
        self.conn.execute(
            """
            insert into lessons
            (id, project_id, title, lesson, scope_json, trigger_json, project_type, confidence,
             confidence_score, promotion_reason, supporting_event_ids_json, created_at, updated_at,
             last_seen, validated_at, disabled_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null)
            """,
            (
                lesson_id,
                project_id,
                title,
                lesson,
                json.dumps(scope),
                json.dumps(trigger),
                project_type,
                confidence,
                confidence_score,
                promotion_reason,
                json.dumps(supporting_event_ids),
                timestamp,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        self.conn.commit()
        return lesson_id

    def enabled_lessons(self, project_id: str, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select * from lessons
            where project_id=? and disabled_at is null
            order by confidence_score desc, last_seen desc
            limit ?
            """,
            (project_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Implement context rendering**

```python
# src/agent_memory/context.py
from __future__ import annotations

from pathlib import Path

from .paths import context_path


POINTER = "Before starting work, read .agent-memory/claude-context.md for learned project-specific failure patterns."


def ensure_claude_pointer(root: Path) -> None:
    path = root / "CLAUDE.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if POINTER in text:
        return
    separator = "\n\n" if text and not text.endswith("\n\n") else ""
    path.write_text(f"{text}{separator}{POINTER}\n", encoding="utf-8")


def render_context(root: Path, db, config: dict) -> Path:
    path = context_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lessons = db.enabled_lessons(config["project_id"], config["max_lessons_injected"])

    lines = [
        "# Learned Failure Patterns",
        "",
        "Generated by memory-claude. Do not edit directly.",
        "",
    ]
    if not lessons:
        lines.extend(["No promoted lessons yet.", ""])
    for lesson in lessons:
        lines.extend(
            [
                f"## {lesson['title']}",
                "",
                lesson["lesson"],
                "",
                f"Confidence: {lesson['confidence']}",
                f"Last seen: {lesson['last_seen'][:10]}",
                f"Lesson ID: {lesson['id']}",
                "",
            ]
        )

    content = "\n".join(lines)
    max_chars = config["max_context_tokens"] * 4
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n"
    path.write_text(content, encoding="utf-8")
    return path
```

- [ ] **Step 5: Run context tests**

Run: `python -m unittest discover -s tests -p "test_context.py" -v`

Expected: PASS.

- [ ] **Step 6: Run all tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agent_memory/context.py src/agent_memory/db.py tests/test_context.py
git commit -m "feat: render claude memory context"
```

---

### Task 5: Wrapper Session Lifecycle And Fail-Open Launch

**Files:**
- Modify: `src/agent_memory/wrapper.py`
- Test: `tests/test_wrapper.py`

- [ ] **Step 1: Write failing wrapper tests**

```python
# tests/test_wrapper.py
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_memory.config import init_project
from agent_memory.db import MemoryDb
from agent_memory.wrapper import prepare_session, run_claude


class WrapperTests(unittest.TestCase):
    def test_prepare_session_cleans_previous_open_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            old_session = db.start_session(config["project_id"], "claude")

            session_id = prepare_session(root, claude_command="claude")

            reopened = MemoryDb.open(root)
            self.assertEqual(reopened.get_session(old_session)["status"], "failed_open")
            self.assertEqual(reopened.get_session(session_id)["status"], "started")

    def test_run_claude_marks_session_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            session_id = db.start_session(config["project_id"], "claude")

            with patch("subprocess.call", return_value=0):
                code = run_claude(root, session_id, ["claude"])

            self.assertEqual(code, 0)
            self.assertEqual(MemoryDb.open(root).get_session(session_id)["status"], "completed")
```

- [ ] **Step 2: Run failing wrapper tests**

Run: `python -m unittest discover -s tests -p "test_wrapper.py" -v`

Expected: FAIL because `prepare_session` and `run_claude` are missing.

- [ ] **Step 3: Implement wrapper lifecycle**

```python
# src/agent_memory/wrapper.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import init_project
from .context import ensure_claude_pointer, render_context
from .db import MemoryDb


def prepare_session(root: Path, claude_command: str = "claude") -> str:
    config = init_project(root)
    db = MemoryDb.open(root)
    db.ensure_project(config["project_id"], root)
    db.cleanup_open_sessions(config["project_id"])
    ensure_claude_pointer(root)
    render_context(root, db, config)
    return db.start_session(config["project_id"], claude_command)


def run_claude(root: Path, session_id: str, command: list[str]) -> int:
    db = MemoryDb.open(root)
    try:
        code = subprocess.call(command)
    except FileNotFoundError:
        db.finish_session(session_id, "failed_open")
        print("memory-claude could not find the 'claude' command. Run 'claude' directly or install Claude Code.", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        db.finish_session(session_id, "failed_open")
        return 130

    db.finish_session(session_id, "completed" if code == 0 else "failed_open")
    return code


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path.cwd()
    claude_command = "claude"
    try:
        session_id = prepare_session(root, claude_command=claude_command)
    except Exception as exc:
        print(f"memory-claude setup failed open: {exc}", file=sys.stderr)
        return subprocess.call([claude_command, *args])
    return run_claude(root, session_id, [claude_command, *args])
```

- [ ] **Step 4: Run wrapper tests**

Run: `python -m unittest discover -s tests -p "test_wrapper.py" -v`

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_memory/wrapper.py tests/test_wrapper.py
git commit -m "feat: add claude wrapper lifecycle"
```

---

### Task 6: Redaction, Event Recording, And Signal Guardrails

**Files:**
- Create: `src/agent_memory/redaction.py`
- Create: `src/agent_memory/extractor.py`
- Modify: `src/agent_memory/cli.py`
- Test: `tests/test_extractor.py`

- [ ] **Step 1: Write failing extractor tests for redaction and signal**

```python
# tests/test_extractor.py
import tempfile
import unittest
from pathlib import Path

from agent_memory.config import init_project
from agent_memory.db import MemoryDb
from agent_memory.extractor import NormalizedEvent, process_raw_event, signal_score
from agent_memory.redaction import redact


class ExtractorTests(unittest.TestCase):
    def test_redacts_basic_secret_patterns(self):
        text = "sk-secret ghp_token Bearer abc password=hunter2 secret=value"
        redacted = redact(text)
        self.assertNotIn("sk-secret", redacted)
        self.assertNotIn("ghp_token", redacted)
        self.assertNotIn("Bearer abc", redacted)
        self.assertNotIn("password=hunter2", redacted)
        self.assertNotIn("secret=value", redacted)

    def test_low_signal_event_is_logged_but_not_clustered(self):
        event = NormalizedEvent(
            event_id="evt_1",
            event_type="failed_command",
            command_family="unknown",
            error_terms=[],
            files_touched=[],
            user_terms=[],
            file_change_state="unknown",
            summary="empty failure",
        )
        self.assertLess(signal_score(event), 0.4)

    def test_process_raw_event_skips_flaky_unchanged_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="failed_command",
                source="manual",
                summary="same test failed",
                command="npm test",
                exit_code=1,
                stderr_excerpt="auth test failed",
                user_text=None,
                files_touched=["src/auth/middleware.ts"],
                file_change_state="unchanged",
            )
            result = process_raw_event(db, config, event_id)
            self.assertEqual(result, "skipped_low_signal")
```

- [ ] **Step 2: Run failing extractor tests**

Run: `python -m unittest discover -s tests -p "test_extractor.py" -v`

Expected: FAIL because redaction and extractor modules are missing.

- [ ] **Step 3: Implement redaction**

```python
# src/agent_memory/redaction.py
from __future__ import annotations

import re


PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
    re.compile(r"ghp_[A-Za-z0-9_\-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"password=[^\s]+", re.IGNORECASE),
    re.compile(r"secret=[^\s]+", re.IGNORECASE),
]


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    result = text
    for pattern in PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result
```

- [ ] **Step 4: Implement normalization and signal checks**

```python
# src/agent_memory/extractor.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class NormalizedEvent:
    event_id: str
    event_type: str
    command_family: str
    error_terms: list[str]
    files_touched: list[str]
    user_terms: list[str]
    file_change_state: str
    summary: str


def command_family(command: str | None) -> str:
    if not command:
        return "unknown"
    parts = command.strip().split()
    if not parts:
        return "unknown"
    if len(parts) >= 2 and parts[0] in {"npm", "pnpm", "yarn"}:
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def terms(text: str | None) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text.lower())
    noisy = {"error", "failed", "expected", "actual", "traceback"}
    return [word for word in words[:20] if word not in noisy]


def normalize_raw_event(row: dict) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=row["id"],
        event_type=row["event_type"],
        command_family=command_family(row.get("command")),
        error_terms=terms(row.get("stderr_excerpt")),
        files_touched=json.loads(row.get("files_touched_json") or "[]"),
        user_terms=terms(row.get("user_text")),
        file_change_state=row.get("file_change_state") or "unknown",
        summary=row.get("summary") or "",
    )


def signal_score(event: NormalizedEvent) -> float:
    score = 0.0
    if event.command_family != "unknown":
        score += 0.15
    if event.error_terms:
        score += 0.2
    if event.files_touched:
        score += 0.2
    if event.user_terms:
        score += 0.3
    if event.file_change_state == "changed_since_last_failure":
        score += 0.15
    if event.file_change_state == "unchanged" and event.event_type == "failed_command":
        score -= 0.4
    return max(0.0, min(1.0, score))


def process_raw_event(db, config: dict, event_id: str) -> str:
    row = db.get_raw_event(event_id)
    event = normalize_raw_event(row)
    if signal_score(event) < config["min_signal_threshold"]:
        return "skipped_low_signal"
    return "candidate_needed"
```

- [ ] **Step 5: Add manual event commands**

Add subcommands to `build_parser()` in `src/agent_memory/cli.py`:

```python
    record_failure = subparsers.add_parser("record-failure")
    record_failure.add_argument("--command", dest="shell_command", required=True)
    record_failure.add_argument("--exit-code", type=int, default=1)
    record_failure.add_argument("--stderr", default="")
    record_failure.add_argument("--file", action="append", default=[])

    record_correction = subparsers.add_parser("record-correction")
    record_correction.add_argument("text")
    record_correction.add_argument("--file", action="append", default=[])
```

Handle the commands in `main()`:

```python
    if args.command in {"record-failure", "record-correction"}:
        from .config import load_config, init_project
        from .db import MemoryDb
        from .redaction import redact
        from .extractor import process_raw_event

        root = Path.cwd()
        try:
            config = load_config(root)
        except FileNotFoundError:
            config = init_project(root)
        db = MemoryDb.open(root)
        db.ensure_project(config["project_id"], root)
        if args.command == "record-failure":
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="failed_command",
                source="manual",
                summary=f"{args.shell_command} failed",
                command=args.shell_command,
                exit_code=args.exit_code,
                stderr_excerpt=redact(args.stderr),
                user_text=None,
                files_touched=args.file,
                file_change_state="unknown",
            )
        else:
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="user_correction",
                source="manual",
                summary=args.text[:120],
                command=None,
                exit_code=None,
                stderr_excerpt=None,
                user_text=redact(args.text),
                files_touched=args.file,
                file_change_state="unknown",
            )
        result = process_raw_event(db, config, event_id)
        print(f"Recorded {event_id}: {result}")
        return 0
```

- [ ] **Step 6: Run extractor tests**

Run: `python -m unittest discover -s tests -p "test_extractor.py" -v`

Expected: PASS.

- [ ] **Step 7: Run all tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/agent_memory/redaction.py src/agent_memory/extractor.py src/agent_memory/cli.py tests/test_extractor.py
git commit -m "feat: record raw memory events"
```

---

### Task 7: Candidate Clustering, Scoring, And Promotion

**Files:**
- Modify: `src/agent_memory/db.py`
- Modify: `src/agent_memory/extractor.py`
- Test: `tests/test_extractor.py`

- [ ] **Step 1: Add failing promotion tests**

Append to `tests/test_extractor.py`:

```python
    def test_repeat_threshold_promotes_candidate_to_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)

            for _ in range(2):
                event_id = db.insert_raw_event(
                    project_id=config["project_id"],
                    session_id=None,
                    event_type="failed_command",
                    source="manual",
                    summary="auth middleware failed",
                    command="npm test",
                    exit_code=1,
                    stderr_excerpt="auth middleware session rejected",
                    user_text="Do not trust cached session state",
                    files_touched=["src/auth/middleware.ts"],
                    file_change_state="changed_since_last_failure",
                )
                result = process_raw_event(db, config, event_id)

            lessons = db.enabled_lessons(config["project_id"], 10)
            self.assertEqual(result, "promoted")
            self.assertEqual(len(lessons), 1)
            self.assertIn("cached session", lessons[0]["lesson"])
```

- [ ] **Step 2: Run failing promotion test**

Run: `python -m unittest discover -s tests -p "test_extractor.py" -v`

Expected: FAIL because candidate repository and promotion are missing.

- [ ] **Step 3: Add candidate repository methods**

Add to `src/agent_memory/db.py`:

```python
    def find_pending_candidates(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from candidate_patterns where project_id=? and status='pending'",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_candidate(
        self,
        *,
        project_id: str,
        title: str,
        failure_pattern: str,
        suspected_cause: str,
        recommended_fix: str,
        scope: dict[str, Any],
        trigger: dict[str, Any],
        supporting_event_ids: list[str],
        repeat_count: int,
        confidence_score: float,
    ) -> str:
        candidate_id = f"can_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        timestamp = now_iso()
        self.conn.execute(
            """
            insert into candidate_patterns
            (id, project_id, title, failure_pattern, suspected_cause, recommended_fix,
             scope_json, trigger_json, supporting_event_ids_json, repeat_count,
             confidence_score, status, created_at, updated_at, last_seen)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                candidate_id,
                project_id,
                title,
                failure_pattern,
                suspected_cause,
                recommended_fix,
                json.dumps(scope),
                json.dumps(trigger),
                json.dumps(supporting_event_ids),
                repeat_count,
                confidence_score,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        self.conn.commit()
        return candidate_id

    def update_candidate_repeat(self, candidate_id: str, event_id: str, confidence_score: float) -> dict[str, Any]:
        candidate = dict(self.conn.execute("select * from candidate_patterns where id=?", (candidate_id,)).fetchone())
        event_ids = json.loads(candidate["supporting_event_ids_json"])
        if event_id not in event_ids:
            event_ids.append(event_id)
        repeat_count = len(event_ids)
        timestamp = now_iso()
        self.conn.execute(
            """
            update candidate_patterns
            set supporting_event_ids_json=?, repeat_count=?, confidence_score=?, updated_at=?, last_seen=?
            where id=?
            """,
            (json.dumps(event_ids), repeat_count, confidence_score, timestamp, timestamp, candidate_id),
        )
        self.conn.commit()
        candidate.update(
            supporting_event_ids_json=json.dumps(event_ids),
            repeat_count=repeat_count,
            confidence_score=confidence_score,
            updated_at=timestamp,
            last_seen=timestamp,
        )
        return candidate

    def mark_candidate_merged(self, candidate_id: str, lesson_id: str) -> None:
        self.conn.execute(
            "update candidate_patterns set status='merged', merged_into_lesson_id=?, updated_at=? where id=?",
            (lesson_id, now_iso(), candidate_id),
        )
        self.conn.commit()
```

- [ ] **Step 4: Implement clustering, scoring, and promotion**

Replace `process_raw_event()` in `src/agent_memory/extractor.py` and add helpers:

```python
def fingerprint(event: NormalizedEvent) -> str:
    file_key = event.files_touched[0].split("/")[0] if event.files_touched else "nofile"
    term_key = "-".join(event.error_terms[:3] or event.user_terms[:3] or ["noterms"])
    return f"{event.event_type}:{event.command_family}:{file_key}:{term_key}"


def overlap(left: list[str], right: list[str]) -> int:
    return len(set(left).intersection(right))


def candidate_similarity(event: NormalizedEvent, candidate: dict) -> float:
    scope = json.loads(candidate["scope_json"])
    trigger = json.loads(candidate["trigger_json"])
    score = 0.0
    if overlap(event.files_touched, scope.get("files", [])):
        score += 0.35
    if overlap(event.error_terms + event.user_terms, trigger.get("terms", [])):
        score += 0.35
    if event.command_family in trigger.get("commands", []):
        score += 0.2
    return min(1.0, score)


def confidence_score(event: NormalizedEvent, repeat_count: int, manual: bool = False) -> float:
    score = 0.0
    if repeat_count >= 2:
        score += 0.25
    if event.user_terms:
        score += 0.25
    if event.files_touched:
        score += 0.15
    if event.command_family != "unknown":
        score += 0.15
    if manual:
        score += 0.1
    return min(1.0, score)


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def draft_candidate(db, project_id: str, event: NormalizedEvent, score: float) -> str:
    title = "Avoid repeated project failure"
    if event.files_touched:
        title = f"Check {event.files_touched[0]} failure pattern"
    lesson_terms = " ".join(event.user_terms or event.error_terms[:8])
    recommended = f"When this failure appears again, review this pattern before changing code: {lesson_terms}".strip()
    return db.insert_candidate(
        project_id=project_id,
        title=title,
        failure_pattern=event.summary,
        suspected_cause="Repeated failure shape in this project.",
        recommended_fix=recommended,
        scope={"files": event.files_touched},
        trigger={"terms": event.error_terms + event.user_terms, "commands": [event.command_family]},
        supporting_event_ids=[event.event_id],
        repeat_count=1,
        confidence_score=score,
    )


def promote_candidate(db, config: dict, candidate: dict, event: NormalizedEvent, reason: str) -> str:
    score = float(candidate["confidence_score"])
    lesson_id = db.insert_lesson(
        project_id=config["project_id"],
        title=candidate["title"],
        lesson=candidate["recommended_fix"],
        scope=json.loads(candidate["scope_json"]),
        trigger=json.loads(candidate["trigger_json"]),
        project_type=None,
        confidence=confidence_label(score),
        confidence_score=score,
        promotion_reason=reason,
        supporting_event_ids=json.loads(candidate["supporting_event_ids_json"]),
    )
    db.mark_candidate_merged(candidate["id"], lesson_id)
    return lesson_id


def process_raw_event(db, config: dict, event_id: str) -> str:
    row = db.get_raw_event(event_id)
    event = normalize_raw_event(row)
    if signal_score(event) < config["min_signal_threshold"]:
        return "skipped_low_signal"

    pending = db.find_pending_candidates(config["project_id"])
    best = None
    best_score = 0.0
    for candidate in pending:
        score = candidate_similarity(event, candidate)
        if score > best_score:
            best = candidate
            best_score = score

    if best and best_score >= 0.5:
        repeat_count = int(best["repeat_count"]) + 1
        score = confidence_score(event, repeat_count)
        updated = db.update_candidate_repeat(best["id"], event.event_id, score)
        if repeat_count >= config["repeat_threshold"]:
            promote_candidate(db, config, updated, event, "repeat_threshold")
            return "promoted"
        return "clustered"

    score = confidence_score(event, 1)
    draft_candidate(db, config["project_id"], event, score)
    return "candidate_created"
```

- [ ] **Step 5: Run extractor tests**

Run: `python -m unittest discover -s tests -p "test_extractor.py" -v`

Expected: PASS.

- [ ] **Step 6: Run all tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agent_memory/db.py src/agent_memory/extractor.py tests/test_extractor.py
git commit -m "feat: promote repeated memory lessons"
```

---

### Task 8: Inspect And Control Commands

**Files:**
- Modify: `src/agent_memory/db.py`
- Modify: `src/agent_memory/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI behavior tests**

Append to `tests/test_cli.py`:

```python
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_memory.cli import main
from agent_memory.config import init_project
from agent_memory.db import MemoryDb


class CliBehaviorTests(unittest.TestCase):
    def test_status_prints_project_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            with patch("pathlib.Path.cwd", return_value=root), io.StringIO() as out, redirect_stdout(out):
                code = main(["status"])
                text = out.getvalue()
            self.assertEqual(code, 0)
            self.assertIn(config["project_id"], text)

    def test_events_defaults_to_twenty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            for index in range(25):
                db.insert_raw_event(
                    project_id=config["project_id"],
                    session_id=None,
                    event_type="failed_command",
                    source="manual",
                    summary=f"event {index}",
                    command="npm test",
                    exit_code=1,
                    stderr_excerpt="failed",
                    user_text=None,
                    files_touched=[],
                    file_change_state="unknown",
                )
            with patch("pathlib.Path.cwd", return_value=root), io.StringIO() as out, redirect_stdout(out):
                code = main(["events"])
                lines = [line for line in out.getvalue().splitlines() if line.startswith("evt_")]
            self.assertEqual(code, 0)
            self.assertEqual(len(lines), 20)
```

- [ ] **Step 2: Run failing CLI behavior tests**

Run: `python -m unittest discover -s tests -p "test_cli.py" -v`

Expected: FAIL because commands do not print repository data yet.

- [ ] **Step 3: Add list/query repository methods**

Add to `src/agent_memory/db.py`:

```python
    def list_events(self, project_id: str, limit: int | None = 20) -> list[dict[str, Any]]:
        query = "select * from raw_events where project_id=? order by created_at desc"
        params: tuple[Any, ...]
        if limit is None:
            query += ""
            params = (project_id,)
        else:
            query += " limit ?"
            params = (project_id, limit)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_candidates(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from candidate_patterns where project_id=? order by updated_at desc",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_lesson(self, lesson_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("select * from lessons where id=?", (lesson_id,)).fetchone()
        return dict(row) if row else None

    def disable_lesson(self, lesson_id: str) -> bool:
        cursor = self.conn.execute(
            "update lessons set disabled_at=? where id=? and disabled_at is null",
            (now_iso(), lesson_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def injection_history(self, lesson_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from injections where lesson_id=? order by created_at desc",
            (lesson_id,),
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Implement status/events/lessons/why/forget/config output**

In `src/agent_memory/cli.py`, add a loader helper:

```python
def load_project(root: Path):
    from .config import init_project, load_config
    from .db import MemoryDb

    try:
        config = load_config(root)
    except FileNotFoundError:
        config = init_project(root)
    db = MemoryDb.open(root)
    db.ensure_project(config["project_id"], root)
    return config, db
```

Add these branches to `main()` before the final return:

```python
    if args.command == "status":
        config, db = load_project(Path.cwd())
        lessons = db.enabled_lessons(config["project_id"], config["max_lessons_injected"])
        events = db.list_events(config["project_id"], 20)
        print(f"Project: {config['project_id']}")
        print(f"Git mode: {config['git_mode']}")
        print(f"Enabled lessons: {len(lessons)}")
        print(f"Recent events: {len(events)}")
        return 0

    if args.command == "events":
        config, db = load_project(Path.cwd())
        limit = None if args.all else args.limit
        for event in db.list_events(config["project_id"], limit):
            print(f"{event['id']} {event['event_type']} {event['summary']}")
        return 0

    if args.command == "lessons":
        config, db = load_project(Path.cwd())
        for lesson in db.enabled_lessons(config["project_id"], 100):
            print(f"{lesson['id']} [{lesson['confidence']}] {lesson['title']}")
        return 0

    if args.command == "why":
        config, db = load_project(Path.cwd())
        lesson = db.get_lesson(args.lesson_id)
        if not lesson:
            print(f"No lesson found: {args.lesson_id}")
            return 1
        print(f"Lesson: {lesson['title']}")
        print(lesson["lesson"])
        print(f"Promotion: {lesson['promotion_reason']}")
        print(f"Supporting events: {lesson['supporting_event_ids_json']}")
        injections = db.injection_history(args.lesson_id)
        print(f"Injections: {len(injections)}")
        return 0

    if args.command == "forget":
        config, db = load_project(Path.cwd())
        if db.disable_lesson(args.lesson_id):
            print(f"Disabled {args.lesson_id}")
            return 0
        print(f"No enabled lesson found: {args.lesson_id}")
        return 1

    if args.command == "config":
        config, _db = load_project(Path.cwd())
        for key in sorted(config):
            print(f"{key}: {config[key]}")
        return 0
```

- [ ] **Step 5: Implement recall**

Add to `src/agent_memory/cli.py`:

```python
    if args.command == "recall":
        config, db = load_project(Path.cwd())
        query_terms = set(args.query.lower().split())
        matches = []
        for lesson in db.enabled_lessons(config["project_id"], 100):
            haystack = f"{lesson['title']} {lesson['lesson']} {lesson['trigger_json']}".lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score:
                matches.append((score, lesson))
        for _score, lesson in sorted(matches, key=lambda item: item[0], reverse=True)[:5]:
            print(f"{lesson['id']} [{lesson['confidence']}] {lesson['title']}")
            print(lesson["lesson"])
        return 0
```

- [ ] **Step 6: Run CLI behavior tests**

Run: `python -m unittest discover -s tests -p "test_cli.py" -v`

Expected: PASS.

- [ ] **Step 7: Run all tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/agent_memory/db.py src/agent_memory/cli.py tests/test_cli.py
git commit -m "feat: add memory inspection commands"
```

---

### Task 9: README And End-To-End Verification

**Files:**
- Create: `README.md`
- Modify: files found during verification only if tests reveal defects

- [ ] **Step 1: Write README**

```md
# Claude Memory Wrapper

A local-only CLI wrapper for Claude Code that remembers repeated project failures and injects scoped lessons into future sessions.

Principle:

> Log generously, teach selectively.

## Quick Start

```bash
python -m pip install -e .
memory init
memory-claude
```

The wrapper creates `.agent-memory/claude-context.md` and appends a single pointer to the bottom of `CLAUDE.md`.

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
memory recall "auth middleware failure"
memory why <lesson-id>
memory forget <lesson-id>
memory record-failure --command "npm test" --stderr "auth failed" --file src/auth/middleware.ts
memory record-correction "Do not trust cached session state" --file src/auth/middleware.ts
```

## Reliability

`memory-claude` fails open. If memory setup fails, it attempts to launch `claude` normally.
```

- [ ] **Step 2: Run full test suite**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 3: Run editable install**

Run: `python -m pip install -e .`

Expected: completes successfully and exposes `memory` and `memory-claude`.

- [ ] **Step 4: Run local smoke test in a temp project**

Run:

```bash
mkdir tmp-memory-smoke
cd tmp-memory-smoke
memory init
memory record-failure --command "npm test" --stderr "auth middleware session rejected" --file src/auth/middleware.ts
memory record-correction "Do not trust cached session state" --file src/auth/middleware.ts
memory status
memory events
memory lessons
```

Expected:

- `.agent-memory/config.json` exists.
- `.agent-memory/index.sqlite` exists.
- `memory events` prints recent `evt_` lines.
- `memory status` prints the project id.
- No command prints a Python traceback.

- [ ] **Step 5: Run wrapper preparation smoke test without requiring Claude Code**

Run:

```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_memory.wrapper import prepare_session

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    session_id = prepare_session(root)
    assert session_id.startswith("ses_")
    assert (root / ".agent-memory" / "claude-context.md").exists()
    assert "claude-context.md" in (root / "CLAUDE.md").read_text()
print("wrapper prep ok")
PY
```

Expected: prints `wrapper prep ok`.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: add claude memory wrapper usage"
```

---

## Self-Review Notes

Spec coverage:

- Local-only wrapper: Tasks 1, 5, 9.
- `.agent-memory` config and SQLite: Tasks 2, 3.
- Generated `claude-context.md` and idempotent `CLAUDE.md` pointer: Task 4.
- Session cleanup and `failed_open`: Tasks 3, 5.
- Raw event logging and redaction: Task 6.
- Conservative extraction, flaky guardrail, repeat promotion: Tasks 6, 7.
- Inspectability commands including `memory why`: Task 8.
- End-to-end verification: Task 9.

Known v1 limitation:

- `memory-claude` cannot observe every command run inside Claude Code without hooks or terminal-level instrumentation. V1 provides wrapper setup, manual event recording, and the internal collector interface. Hook-based collection remains aligned with the schema through `raw_events.source`.
