from __future__ import annotations

import json
import os
import shutil
import sys
import hashlib
from pathlib import Path
from typing import Any

from .config import ensure_memory_gitignored, init_project, load_config
from .context import ensure_claude_pointer, render_context
from .db import MemoryDb
from .extractor import process_raw_event


SCRIPT = """from agent_memory.cli import main\nraise SystemExit(main(['hook']))\n"""

CORRECTION_MARKERS = (
    "no,",
    "that's wrong",
    "that is wrong",
    "do not",
    "don't",
    "wrong",
    "rejected",
    "never",
)


def install_hooks(root: Path, python_executable: str = sys.executable) -> Path:
    claude_dir = root / ".claude"
    settings_path = _install_claude_assets(claude_dir, "settings.local.json", python_executable)

    _ensure_gitignore_entry(root, ".claude/settings.local.json")
    _ensure_gitignore_entry(root, ".claude/hooks/agent-memory-hook.py")
    _ensure_gitignore_entry(root, ".claude/commands/agent-memory.md")
    _ensure_gitignore_entry(root, ".claude/commands/memory-status.md")
    _ensure_gitignore_entry(root, ".claude/commands/memory-recall.md")
    _ensure_gitignore_entry(root, ".claude/commands/memory-review.md")
    _ensure_gitignore_entry(root, ".claude/commands/memory-why.md")
    _ensure_gitignore_entry(root, ".claude/commands/memory-teach.md")
    _ensure_gitignore_entry(root, ".claude/commands/memory-doctor.md")
    _ensure_gitignore_entry(root, ".claude/commands/memory-repair.md")
    _ensure_gitignore_entry(root, ".claude/skills/agent-memory/")
    _ensure_gitignore_entry(root, ".claude/skills/memory-status/")
    _ensure_gitignore_entry(root, ".claude/skills/memory-recall/")
    _ensure_gitignore_entry(root, ".claude/skills/memory-review/")
    _ensure_gitignore_entry(root, ".claude/skills/memory-why/")
    _ensure_gitignore_entry(root, ".claude/skills/memory-teach/")
    _ensure_gitignore_entry(root, ".claude/skills/memory-doctor/")
    _ensure_gitignore_entry(root, ".claude/skills/memory-repair/")
    ensure_memory_gitignored(root)
    _write_default_project(root)
    return settings_path


def install_claude_global(python_executable: str = sys.executable) -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return _install_claude_assets(home / ".claude", "settings.json", python_executable)


def _install_claude_assets(claude_dir: Path, settings_name: str, python_executable: str) -> Path:
    hooks_dir = claude_dir / "hooks"
    commands_dir = claude_dir / "commands"
    skills_dir = claude_dir / "skills"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    commands_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    script_path = hooks_dir / "agent-memory-hook.py"
    script_path.write_text(SCRIPT, encoding="utf-8")
    command_docs = _command_docs(python_executable)
    skill_docs = _skill_docs(python_executable)
    (commands_dir / "agent-memory.md").write_text(command_docs["agent-memory"], encoding="utf-8")
    (commands_dir / "memory-status.md").write_text(command_docs["memory-status"], encoding="utf-8")
    (commands_dir / "memory-recall.md").write_text(command_docs["memory-recall"], encoding="utf-8")
    (commands_dir / "memory-review.md").write_text(command_docs["memory-review"], encoding="utf-8")
    (commands_dir / "memory-why.md").write_text(command_docs["memory-why"], encoding="utf-8")
    (commands_dir / "memory-teach.md").write_text(command_docs["memory-teach"], encoding="utf-8")
    (commands_dir / "memory-doctor.md").write_text(command_docs["memory-doctor"], encoding="utf-8")
    (commands_dir / "memory-repair.md").write_text(command_docs["memory-repair"], encoding="utf-8")
    for name, text in skill_docs.items():
        skill_dir = skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")

    settings_path = claude_dir / settings_name
    settings = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings.setdefault("hooks", {})
    settings["hooks"]["SessionStart"] = [_hook_group(None, python_executable)]
    settings["hooks"]["PostToolUse"] = [_hook_group("Write|Edit|MultiEdit", python_executable)]
    settings["hooks"]["PostToolUseFailure"] = [_hook_group("Bash", python_executable)]
    settings["hooks"]["UserPromptSubmit"] = [_hook_group(None, python_executable)]
    _ensure_permission_allow(settings, _memory_permission_rules(python_executable))
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return settings_path


def _default_shell() -> str:
    # Slash-command/skill frontmatter is baked at install time, so match the
    # shell of the machine being installed on: PowerShell on Windows, bash on
    # macOS/Linux. Without this the generated skills carried a Windows-only
    # `shell: powershell` that is wrong on Unix.
    return "powershell" if os.name == "nt" else "bash"


def _command_docs(python_executable: str) -> dict[str, str]:
    allowed_tools = _allowed_tools_frontmatter(python_executable)
    shell = _default_shell()
    return {
        "agent-memory": f"""---
description: Show Agent Memory status, lessons, and recent events
{allowed_tools}
shell: {shell}
---

Run these commands with Bash from the current project:

1. `memory status`
2. `memory lessons`
3. `memory events --limit 10`

Summarize what Agent Memory has learned and whether hooks are collecting events.
""",
        "memory-status": f"""---
description: Show local Agent Memory status
{allowed_tools}
shell: {shell}
---

Run `memory status` with Bash from the current project.

Summarize the memory state.
""",
        "memory-recall": f"""---
description: Recall Agent Memory lessons for a query
argument-hint: [query]
{allowed_tools}
shell: {shell}
---

Run `memory recall "$ARGUMENTS"` with Bash from the current project.

Summarize matching learned failure patterns.
""",
        "memory-review": f"""---
description: Review pending Agent Memory candidates and recent evidence
{allowed_tools}
shell: {shell}
---

Run these commands with Bash from the current project:

1. `memory review`

Review pending candidates. Recommend which candidates look safe to approve, which look noisy, and which need more evidence. Do not approve anything automatically.
""",
        "memory-why": f"""---
description: Explain why an Agent Memory lesson exists
argument-hint: [lesson-id]
{allowed_tools}
shell: {shell}
---

Run `memory why "$ARGUMENTS"` with Bash from the current project.

Explain the raw events, candidate chain, and injection history behind the lesson.
""",
        "memory-teach": f"""---
description: Record a durable Agent Memory correction from the user
argument-hint: [lesson text]
{allowed_tools}
shell: {shell}
---

Run `memory record-correction "$ARGUMENTS"` with Bash from the current project.

Summarize what was recorded and whether it created or strengthened a candidate lesson.
""",
        "memory-doctor": f"""---
description: Diagnose Agent Memory installation, hooks, skills, permissions, and project storage
{allowed_tools}
shell: {shell}
---

Run `memory doctor` with Bash from the current project.

Summarize any errors or warnings first, then give the shortest actionable fix for each issue.
""",
        "memory-repair": f"""---
description: Repair Agent Memory installation, hooks, skills, permissions, and project storage
{allowed_tools}
shell: {shell}
---

Run `memory doctor --fix` with Bash from the current project.

Summarize what was repaired. If any errors or warnings remain, list them first and give the shortest next action.
""",
    }


def _skill_docs(python_executable: str) -> dict[str, str]:
    command_docs = _command_docs(python_executable)
    return {
        "agent-memory": command_docs["agent-memory"].replace(
            "description: Show Agent Memory status, lessons, and recent events",
            "description: Inspect local Agent Memory status, promoted lessons, and recent raw events. Use when the user asks whether memory is working or what it has learned.",
        ),
        "memory-status": command_docs["memory-status"].replace(
            "description: Show local Agent Memory status",
            "description: Inspect local Agent Memory status. Use when the user asks whether the wrapper or hooks are working.",
        ),
        "memory-recall": command_docs["memory-recall"].replace(
            "description: Recall Agent Memory lessons for a query",
            "description: Recall Agent Memory lessons for a query. Use when the user asks what memory knows about a specific failure or file.",
        ),
        "memory-review": command_docs["memory-review"].replace(
            "description: Review pending Agent Memory candidates and recent evidence",
            "description: Review pending Agent Memory candidates and recent evidence. Use when the user asks what memory should learn or promote.",
        ),
        "memory-why": command_docs["memory-why"].replace(
            "description: Explain why an Agent Memory lesson exists",
            "description: Explain why an Agent Memory lesson exists. Use when the user asks why a lesson is present or whether it is trustworthy.",
        ),
        "memory-teach": command_docs["memory-teach"].replace(
            "description: Record a durable Agent Memory correction from the user",
            "description: Record a durable Agent Memory correction from the user. Use when the user explicitly wants Agent Memory to remember a correction.",
        ),
        "memory-doctor": command_docs["memory-doctor"].replace(
            "description: Diagnose Agent Memory installation, hooks, skills, permissions, and project storage",
            "description: Diagnose Agent Memory installation, hooks, skills, permissions, and project storage. Use when the user asks whether Agent Memory is installed correctly or a slash command/hook is failing.",
        ),
        "memory-repair": command_docs["memory-repair"].replace(
            "description: Repair Agent Memory installation, hooks, skills, permissions, and project storage",
            "description: Repair Agent Memory installation, hooks, skills, permissions, and project storage. Use when diagnostics show missing hooks, missing slash skills, stale permissions, or broken project setup.",
        ),
    }


def _memory_permission_rules(python_executable: str) -> list[str]:
    return ["Bash(memory *)", "Bash(memory)"]


def _allowed_tools_frontmatter(python_executable: str) -> str:
    rules = _memory_permission_rules(python_executable)
    return "allowed-tools:\n" + "\n".join(f"  - {rule}" for rule in rules)


def _ensure_permission_allow(settings: dict[str, Any], rules: list[str]) -> None:
    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    allow[:] = [rule for rule in allow if not _is_agent_memory_permission(rule)]
    for rule in rules:
        if rule not in allow:
            allow.append(rule)


def _is_agent_memory_permission(rule: Any) -> bool:
    return isinstance(rule, str) and ("agent_memory" in rule or rule in {"Bash(memory *)", "Bash(memory)"})


def _write_default_project(root: Path) -> None:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    path = home / ".agent-memory" / "default-project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"path": str(root)}) + "\n", encoding="utf-8")


def _hook_group(matcher: str | None, python_executable: str) -> dict[str, Any]:
    command = _hook_command(python_executable)
    group: dict[str, Any] = {
        "hooks": [
            {
                "type": "command",
                "command": command,
            }
        ]
    }
    if matcher is not None:
        group["matcher"] = matcher
    return group


def _hook_command(python_executable: str) -> str:
    # A bare "memory hook" only works if the launcher is on PATH when Claude
    # Code spawns the hook. If the only "memory" we can find lives in the same
    # virtualenv Scripts/bin dir as this interpreter, it is on PATH only while
    # that venv is active -- unreliable for hooks -- so pin the absolute
    # interpreter, which runs regardless of the runtime PATH. A global launcher
    # (e.g. pipx) that resolves elsewhere keeps the portable "memory hook" form.
    memory_path = shutil.which("memory")
    if memory_path and not _memory_is_in_venv_scripts(memory_path, python_executable):
        return "memory hook"
    return f'"{python_executable}" -m agent_memory hook'


def _memory_is_in_venv_scripts(memory_path: str, python_executable: str) -> bool:
    try:
        mem_dir = Path(memory_path).resolve().parent
        py_dir = Path(python_executable).resolve().parent
    except (OSError, ValueError):
        return False
    if mem_dir != py_dir:
        return False
    return (py_dir / "pyvenv.cfg").exists() or (py_dir.parent / "pyvenv.cfg").exists()


def _ensure_gitignore_entry(root: Path, entry: str) -> None:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [line.strip() for line in text.splitlines()]
    if entry in lines:
        return
    separator = "\n" if text and not text.endswith("\n") else ""
    path.write_text(f"{text}{separator}{entry}\n", encoding="utf-8")


def handle_stdin() -> int:
    # Read raw bytes and decode as UTF-8 rather than trusting sys.stdin's text
    # decoding. On Windows the spawned hook process gets a locale code page
    # (e.g. cp1252) for stdin, which both mangles non-ASCII UTF-8 that Claude
    # Code sends and turns a leading UTF-8 BOM into stray bytes that break
    # json.loads -- silently no-opping the hook. "utf-8-sig" decodes the real
    # UTF-8 payload and absorbs any BOM some shells prepend when piping.
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        raw = buffer.read().decode("utf-8-sig", errors="replace")
    else:
        raw = sys.stdin.read()
    raw = raw.lstrip("\ufeff").strip()
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    return handle_hook_payload(payload)


def handle_hook_payload(payload: dict[str, Any]) -> int:
    event_name = payload.get("hook_event_name")
    root = _effective_hook_root(Path(payload.get("cwd") or Path.cwd()))
    config = init_project(root)
    db = MemoryDb.open(root)
    try:
        db.ensure_project(config["project_id"], root)
        if event_name == "SessionStart":
            _handle_session_start(root, db, config, payload)
            return 0
        if event_name == "PostToolUse" and payload.get("tool_name") in {"Write", "Edit", "MultiEdit"}:
            _handle_file_touch(root, payload)
            return 0
        if event_name == "PostToolUseFailure" and payload.get("tool_name") == "Bash":
            _handle_bash_failure(root, db, config, payload)
            return 0
        if event_name == "UserPromptSubmit":
            _handle_user_prompt(root, db, config, payload)
            return 0
        return 0
    finally:
        db.close()


def _handle_bash_failure(root: Path, db: MemoryDb, config: dict[str, Any], payload: dict[str, Any]) -> None:
    command = (payload.get("tool_input") or {}).get("command")
    if _is_agent_memory_command(command):
        return
    response = payload.get("tool_response") or {}
    stderr = _stringify(response.get("stderr") or response.get("error") or response.get("message") or response)
    recent_files = _recent_files(root, payload.get("session_id"))
    files_touched = _dedupe(recent_files + _file_mentions(f"{command or ''} {stderr}"))
    file_change_state = _file_change_state_for_failure(root, command, stderr, files_touched)
    exit_code = response.get("exit_code") if isinstance(response, dict) else None
    event_id = db.insert_raw_event(
        project_id=config["project_id"],
        session_id=payload.get("session_id"),
        event_type="failed_command",
        source="claude_hook",
        summary=f"{command or 'Bash'} failed",
        command=command,
        exit_code=exit_code if isinstance(exit_code, int) else 1,
        stderr_excerpt=stderr[:4000],
        user_text=None,
        files_touched=files_touched,
        file_change_state=file_change_state,
    )
    process_raw_event(db, config, event_id)
    recall = _recall_context(db, config, f"{command or ''} {stderr}")
    if recall:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUseFailure",
                        "additionalContext": recall,
                    }
                }
            )
        )


def _handle_user_prompt(root: Path, db: MemoryDb, config: dict[str, Any], payload: dict[str, Any]) -> None:
    prompt = payload.get("prompt") or payload.get("user_prompt") or payload.get("message") or ""
    if not _looks_like_correction(prompt):
        return
    files_touched = _dedupe(_recent_files(root, payload.get("session_id")) + _file_mentions(prompt))
    event_id = db.insert_raw_event(
        project_id=config["project_id"],
        session_id=payload.get("session_id"),
        event_type="user_correction",
        source="claude_hook",
        summary=prompt[:120],
        command=None,
        exit_code=None,
        stderr_excerpt=None,
        user_text=prompt,
        files_touched=files_touched,
        file_change_state="unknown",
    )
    process_raw_event(db, config, event_id)


def _handle_session_start(root: Path, db: MemoryDb, config: dict[str, Any], payload: dict[str, Any]) -> None:
    ensure_claude_pointer(root)
    path = render_context(root, db, config, session_id=payload.get("session_id"))
    context = path.read_text(encoding="utf-8")
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    )


def _handle_file_touch(root: Path, payload: dict[str, Any]) -> None:
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path")
    if not file_path:
        return
    session_id = payload.get("session_id") or "unknown"
    state = _load_state(root)
    key = str(session_id)
    files = state.setdefault(key, [])
    if file_path not in files:
        files.insert(0, file_path)
    state[key] = files[:20]
    state["_change_generation"] = int(state.get("_change_generation") or 0) + 1
    _save_state(root, state)


def _state_path(root: Path) -> Path:
    return root / ".agent-memory" / "hook-state.json"


def _load_state(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(root: Path, state: dict[str, Any]) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _recent_files(root: Path, session_id: str | None) -> list[str]:
    if not session_id:
        return []
    files = _load_state(root).get(str(session_id), [])
    return files[:10] if isinstance(files, list) else []


def _file_change_state_for_failure(root: Path, command: str | None, stderr: str, files_touched: list[str]) -> str:
    state = _load_state(root)
    failures = state.setdefault("_failures", {})
    if not isinstance(failures, dict):
        failures = {}
        state["_failures"] = failures
    key = _failure_state_key(command, stderr, files_touched)
    change_generation = int(state.get("_change_generation") or 0)
    snapshot: dict[str, Any] = {
        "change_generation": change_generation,
        "files": _file_snapshot(root, files_touched) if files_touched else {},
    }
    previous = failures.get(key)
    failures[key] = snapshot
    _save_state(root, state)
    if previous is None:
        return "unknown"
    return "unchanged" if previous == snapshot else "changed_since_last_failure"


def _failure_state_key(command: str | None, stderr: str, files_touched: list[str]) -> str:
    material = json.dumps(
        {
            "command": command or "",
            "stderr": " ".join(stderr.lower().split())[:1000],
            "files": sorted(files_touched),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _file_snapshot(root: Path, files_touched: list[str]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for file_name in sorted(files_touched):
        path = Path(file_name)
        if not path.is_absolute():
            path = root / path
        try:
            digest = _file_digest(path)
        except OSError:
            digest = None
        snapshot[file_name] = {"sha256": digest}
    return snapshot


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_mentions(text: str) -> list[str]:
    import re

    matches = re.findall(r"(?:(?:[A-Za-z]:)?[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+", text or "")
    return [match.replace("\\", "/") for match in matches]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _looks_like_correction(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CORRECTION_MARKERS)


def _is_agent_memory_command(command: str | None) -> bool:
    if not command:
        return False
    normalized = " ".join(command.strip().lower().split())
    if normalized in {"memory", "memory.exe", "memory.cmd", "memory-claude", "memory-claude.exe", "memory-claude.cmd"}:
        return True
    if normalized.startswith(("memory ", "memory.exe ", "memory.cmd ", "memory-claude ", "memory-claude.exe ", "memory-claude.cmd ")):
        return True
    return " -m agent_memory" in normalized or " -m agent-memory" in normalized


def _recall_context(db: MemoryDb, config: dict[str, Any], query: str) -> str:
    terms = set(query.lower().split())
    matches = []
    for lesson in db.enabled_lessons(config["project_id"], 100):
        haystack = f"{lesson['title']} {lesson['lesson']} {lesson['trigger_json']}".lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            matches.append((score, lesson))
    if not matches:
        return ""
    _score, lesson = sorted(matches, key=lambda item: item[0], reverse=True)[0]
    return (
        "Memory recall:\n"
        "A similar failure has been seen before.\n\n"
        f"Known lesson:\n{lesson['lesson']}\n\n"
        f"Confidence: {lesson['confidence']}\n"
        f"Last seen: {lesson['last_seen'][:10]}\n"
        f"Lesson ID: {lesson['id']}"
    )


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True)


def _effective_hook_root(cwd: Path) -> Path:
    from .wrapper import effective_root

    return effective_root(cwd)
