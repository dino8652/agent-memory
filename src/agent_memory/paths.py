from __future__ import annotations

from pathlib import Path


def project_root(root: Path | None = None) -> Path:
    return Path.cwd() if root is None else root


def memory_dir(root: Path) -> Path:
    return project_root(root) / ".agent-memory"


def config_path(root: Path) -> Path:
    return memory_dir(root) / "config.json"


def db_path(root: Path) -> Path:
    return memory_dir(root) / "index.sqlite"


def context_path(root: Path) -> Path:
    return memory_dir(root) / "claude-context.md"
