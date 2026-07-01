from __future__ import annotations

import subprocess
import sys
import os
import shutil
import json
from pathlib import Path

from .config import init_project
from .context import ensure_claude_pointer, render_context
from .db import MemoryDb


def discover_claude_command() -> str | None:
    from_path = shutil.which("claude")
    if from_path:
        return from_path

    # Everything below is a Windows-only fallback for the packaged desktop
    # install. On macOS/Linux `claude` is expected on PATH (handled above).
    if os.name != "nt":
        return None

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    package_root = Path(local_app_data) / "Packages"
    candidates = sorted(
        package_root.glob("Claude_*/LocalCache/Roaming/Claude/claude-code/*/claude.exe"),
        reverse=True,
    )
    if candidates:
        return str(candidates[0])
    return None


def effective_root(cwd: Path) -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home()).resolve()
    cwd = cwd.resolve()
    if cwd != home:
        return cwd
    default_project = home / ".agent-memory" / "default-project.json"
    if not default_project.exists():
        return cwd
    try:
        path = Path(json.loads(default_project.read_text(encoding="utf-8"))["path"])
    except (KeyError, json.JSONDecodeError, OSError):
        return cwd
    if path.exists():
        return path.resolve()
    return cwd


def prepare_session(root: Path, claude_command: str = "claude") -> str:
    config = init_project(root)
    db = MemoryDb.open(root)
    try:
        db.ensure_project(config["project_id"], root)
        db.cleanup_open_sessions(config["project_id"])
        session_id = db.start_session(config["project_id"], claude_command)
        ensure_claude_pointer(root)
        render_context(root, db, config, session_id=session_id)
        return session_id
    finally:
        db.close()


def run_claude(root: Path, session_id: str, command: list[str]) -> int:
    db = MemoryDb.open(root)
    try:
        code = subprocess.call(command, cwd=root)
    except FileNotFoundError:
        db.finish_session(session_id, "failed_open")
        db.close()
        print(
            "memory-claude could not find the 'claude' command. Run 'claude' directly or install Claude Code.",
            file=sys.stderr,
        )
        return 127
    except KeyboardInterrupt:
        db.finish_session(session_id, "failed_open")
        db.close()
        return 130

    db.finish_session(session_id, "completed" if code == 0 else "failed_open")
    db.close()
    return code

def main(argv: list[str] | None = None) -> int:
    from .cli import _force_utf8_io

    _force_utf8_io()
    args = argv if argv is not None else sys.argv[1:]
    root = effective_root(Path.cwd())
    claude_command = discover_claude_command() or "claude"
    try:
        session_id = prepare_session(root, claude_command=claude_command)
    except Exception as exc:
        print(f"memory-claude setup failed open: {exc}", file=sys.stderr)
        try:
            return subprocess.call([claude_command, *args], cwd=root)
        except FileNotFoundError:
            return 127
    return run_claude(root, session_id, [claude_command, *args])
