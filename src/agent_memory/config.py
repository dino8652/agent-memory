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
        try:
            config = load_config(root)
        except (json.JSONDecodeError, ValueError):
            config = None
        if config is not None:
            if config.get("git_mode") == "local_only":
                ensure_memory_gitignored(root)
            return config
        # config.json exists but is unreadable/corrupt: fall through and rewrite
        # a fresh one rather than letting every command crash on it.

    config = dict(DEFAULT_CONFIG)
    config["project_id"] = f"proj_{uuid.uuid4().hex[:12]}"
    config["git_mode"] = git_mode
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if git_mode == "local_only":
        ensure_memory_gitignored(root)
    return config


def load_config(root: Path) -> dict[str, Any]:
    data = json.loads(config_path(root).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json must contain a JSON object")
    # Fill in any keys added in newer versions so an older on-disk config never
    # KeyErrors a downstream reader (e.g. min_signal_threshold in the extractor).
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def ensure_memory_gitignored(root: Path) -> None:
    path = root / ".gitignore"
    entry = ".agent-memory/"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [line.strip() for line in text.splitlines()]
    if entry in lines or ".agent-memory" in lines:
        return
    separator = "\n" if text and not text.endswith("\n") else ""
    path.write_text(f"{text}{separator}{entry}\n", encoding="utf-8")
