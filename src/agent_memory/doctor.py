from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import init_project, load_config
from .context import render_context, render_context_content
from .db import MemoryDb
from .paths import context_path


REQUIRED_SKILLS = (
    "agent-memory",
    "memory-status",
    "memory-recall",
    "memory-review",
    "memory-why",
    "memory-teach",
    "memory-doctor",
    "memory-repair",
)

REQUIRED_HOOKS = (
    "SessionStart",
    "PostToolUse",
    "PostToolUseFailure",
    "UserPromptSubmit",
)

REQUIRED_ALLOW_RULES = ("Bash(memory *)", "Bash(memory)")


def run_doctor(root: Path) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    claude_dir = home / ".claude"
    settings_path = claude_dir / "settings.json"

    memory_path = shutil.which("memory")
    _add(
        checks,
        "memory_on_path",
        "ok" if memory_path else "error",
        f"memory command resolves to {memory_path}" if memory_path else "memory command is not on PATH",
    )

    settings = _read_json(settings_path)
    if settings is None:
        _add(checks, "global_settings", "error", f"missing or invalid {settings_path}")
    else:
        _add(checks, "global_settings", "ok", f"found {settings_path}")
        _check_hooks(checks, settings, check_id="global_hooks", label="global settings")
        _check_permissions(checks, settings, check_id="global_permissions", label="global settings")

    _check_project_local_settings(checks, root)

    missing_skills = [
        name
        for name in REQUIRED_SKILLS
        if not (claude_dir / "skills" / name / "SKILL.md").exists()
    ]
    _add(
        checks,
        "global_skills",
        "ok" if not missing_skills else "error",
        "all Agent Memory skills installed"
        if not missing_skills
        else f"missing skills: {', '.join(missing_skills)}",
    )

    _check_default_project(checks, home, root)
    project_id = _check_project_memory(checks, root)
    _check_generated_context(checks, root)
    status = _overall_status(checks)
    return {
        "status": status,
        "root": str(root),
        "home": str(home),
        "project_id": project_id,
        "checks": checks,
    }


def repair_doctor(root: Path, python_executable: str) -> dict[str, Any]:
    repairs: list[dict[str, str]] = []
    from .hooks import install_claude_global, install_hooks

    try:
        path = install_claude_global(python_executable=python_executable)
        _add(repairs, "global_install", "ok", f"refreshed {path}")
    except Exception as exc:
        _add(repairs, "global_install", "error", f"global install failed: {exc}")

    try:
        path = install_hooks(root, python_executable=python_executable)
        _add(repairs, "project_install", "ok", f"refreshed {path}")
    except Exception as exc:
        _add(repairs, "project_install", "error", f"project install failed: {exc}")

    try:
        config = init_project(root)
        db = MemoryDb.open(root)
        try:
            db.ensure_project(config["project_id"], root)
            path = render_context(root, db, config)
        finally:
            db.close()
        _add(repairs, "generated_context", "ok", f"refreshed {path}")
    except Exception as exc:
        _add(repairs, "generated_context", "error", f"context render failed: {exc}")

    report = run_doctor(root)
    report["repairs"] = repairs
    if any(repair["status"] == "error" for repair in repairs):
        report["status"] = "error"
    return report


def format_doctor_report(report: dict[str, Any]) -> str:
    lines = [
        f"Agent Memory Doctor: {report['status']}",
        f"Project root: {report['root']}",
        f"Claude home: {report['home']}",
    ]
    if report.get("project_id"):
        lines.append(f"Project: {report['project_id']}")
    if report.get("repairs"):
        lines.append("")
        lines.append("Repairs:")
        for repair in report["repairs"]:
            lines.append(f"[{repair['status']}] {repair['id']}: {repair['message']}")
    lines.append("")
    for check in report["checks"]:
        lines.append(f"[{check['status']}] {check['id']}: {check['message']}")
    return "\n".join(lines)


def exit_code_for_report(report: dict[str, Any]) -> int:
    return 1 if report["status"] == "error" else 0


def _check_project_local_settings(checks: list[dict[str, str]], root: Path) -> None:
    settings_path = root / ".claude" / "settings.local.json"
    if not settings_path.exists():
        _add(checks, "project_local_settings", "warning", f"missing {settings_path}; run memory doctor --fix")
        return
    settings = _read_json(settings_path)
    if settings is None:
        _add(checks, "project_local_settings", "error", f"missing or invalid {settings_path}")
        return
    _add(checks, "project_local_settings", "ok", f"found {settings_path}")
    _check_hooks(checks, settings, check_id="project_local_hooks", label="project local settings")
    _check_permissions(checks, settings, check_id="project_local_permissions", label="project local settings")


def _check_hooks(checks: list[dict[str, str]], settings: dict[str, Any], *, check_id: str, label: str) -> None:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        _add(checks, check_id, "error", f"{label} has no hooks object")
        return

    missing = [name for name in REQUIRED_HOOKS if name not in hooks]
    bad_commands = []
    for name in REQUIRED_HOOKS:
        command = _first_hook_command(hooks.get(name))
        if command is not None and not _is_working_hook_command(command):
            bad_commands.append(f"{name}={command}")

    if missing:
        _add(checks, check_id, "error", f"missing hooks: {', '.join(missing)}")
    elif bad_commands:
        _add(checks, check_id, "warning", f"unrecognized hook commands: {', '.join(bad_commands)}")
    else:
        _add(checks, check_id, "ok", "all required hooks invoke the memory hook")


def _check_permissions(checks: list[dict[str, str]], settings: dict[str, Any], *, check_id: str, label: str) -> None:
    permissions = settings.get("permissions")
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    if not isinstance(allow, list):
        _add(checks, check_id, "error", f"{label} has no permissions.allow list")
        return
    missing = [rule for rule in REQUIRED_ALLOW_RULES if rule not in allow]
    stale = [rule for rule in allow if isinstance(rule, str) and "agent_memory" in rule]
    if stale:
        _add(checks, check_id, "warning", f"stale non-portable allow rules: {', '.join(stale)}")
        return
    _add(
        checks,
        check_id,
        "ok" if not missing else "error",
        "portable memory permissions installed" if not missing else f"missing allow rules: {', '.join(missing)}",
    )


def _check_project_memory(checks: list[dict[str, str]], root: Path) -> str | None:
    try:
        try:
            config = load_config(root)
        except FileNotFoundError:
            config = init_project(root)
        db = MemoryDb.open(root)
        try:
            db.ensure_project(config["project_id"], root)
        finally:
            db.close()
    except Exception as exc:
        _add(checks, "project_memory", "error", f"project memory failed: {exc}")
        return None
    _add(checks, "project_memory", "ok", "project memory database opens successfully")
    return str(config["project_id"])


def _check_generated_context(checks: list[dict[str, str]], root: Path) -> None:
    path = context_path(root)
    if not path.exists():
        _add(checks, "generated_context", "warning", f"missing {path}; run memory doctor --fix")
        return
    try:
        config = load_config(root)
        db = MemoryDb.open(root)
        try:
            expected = render_context_content(db, config, record_injections=False)
        finally:
            db.close()
        actual = path.read_text(encoding="utf-8")
    except Exception as exc:
        _add(checks, "generated_context", "error", f"context check failed: {exc}")
        return

    if actual != expected:
        _add(checks, "generated_context", "warning", f"{path} is stale; run memory doctor --fix")
        return
    _add(checks, "generated_context", "ok", f"{path} is current")


def _check_default_project(checks: list[dict[str, str]], home: Path, root: Path) -> None:
    default_project = home / ".agent-memory" / "default-project.json"
    if not default_project.exists():
        _add(checks, "default_project", "warning", f"missing {default_project}; run memory doctor --fix")
        return
    try:
        configured = Path(json.loads(default_project.read_text(encoding="utf-8"))["path"])
    except (KeyError, json.JSONDecodeError, OSError):
        _add(checks, "default_project", "warning", f"invalid {default_project}; run memory doctor --fix")
        return

    try:
        configured_resolved = configured.resolve()
        root_resolved = root.resolve()
    except OSError:
        _add(checks, "default_project", "warning", f"default project path is not usable: {configured}")
        return

    if configured_resolved != root_resolved:
        _add(
            checks,
            "default_project",
            "warning",
            f"default project points to {configured}; current project is {root}",
        )
        return
    _add(checks, "default_project", "ok", f"default project points to {root}")


def _is_working_hook_command(command: str) -> bool:
    # Both forms run the hook: the portable "memory hook" launcher and the
    # absolute-interpreter "<python> -m agent_memory hook" form used for
    # virtualenv installs. Only genuinely unexpected commands are flagged.
    return command == "memory hook" or command.endswith("-m agent_memory hook")


def _first_hook_command(group: Any) -> str | None:
    if not isinstance(group, list) or not group:
        return None
    hooks = group[0].get("hooks") if isinstance(group[0], dict) else None
    if not isinstance(hooks, list) or not hooks:
        return None
    command = hooks[0].get("command") if isinstance(hooks[0], dict) else None
    return command if isinstance(command, str) else None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _add(checks: list[dict[str, str]], check_id: str, status: str, message: str) -> None:
    checks.append({"id": check_id, "status": status, "message": message})


def _overall_status(checks: list[dict[str, str]]) -> str:
    statuses = {check["status"] for check in checks}
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "ok"
