import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_memory import hooks as hooks_module
from agent_memory.config import init_project
from agent_memory.db import MemoryDb
from agent_memory.hooks import (
    _hook_command,
    handle_hook_payload,
    handle_stdin,
    install_claude_global,
    install_hooks,
)


class HookTests(unittest.TestCase):
    def test_install_claude_global_writes_user_settings_and_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                settings_path = install_claude_global(python_executable="python")

            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(settings_path, home / ".claude" / "settings.json")
            self.assertTrue((home / ".claude" / "hooks" / "agent-memory-hook.py").exists())
            self.assertTrue((home / ".claude" / "skills" / "agent-memory" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "memory-status" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "memory-recall" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "memory-review" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "memory-why" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "memory-teach" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "memory-doctor" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "memory-repair" / "SKILL.md").exists())
            skill_text = (home / ".claude" / "skills" / "memory-recall" / "SKILL.md").read_text(encoding="utf-8")
            why_text = (home / ".claude" / "skills" / "memory-why" / "SKILL.md").read_text(encoding="utf-8")
            teach_text = (home / ".claude" / "skills" / "memory-teach" / "SKILL.md").read_text(encoding="utf-8")
            doctor_text = (home / ".claude" / "skills" / "memory-doctor" / "SKILL.md").read_text(encoding="utf-8")
            repair_text = (home / ".claude" / "skills" / "memory-repair" / "SKILL.md").read_text(encoding="utf-8")
            review_text = (home / ".claude" / "skills" / "memory-review" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("allowed-tools:", skill_text)
            self.assertIn("Bash(memory *)", skill_text)
            self.assertIn("memory recall", skill_text)
            self.assertIn("memory why", why_text)
            self.assertIn("memory record-correction", teach_text)
            self.assertIn("memory doctor", doctor_text)
            self.assertIn("memory doctor --fix", repair_text)
            self.assertIn("memory review", review_text)
            self.assertNotIn("!`", skill_text)
            self.assertNotIn("python", skill_text.lower())
            self.assertNotIn("agent_memory", skill_text)
            self.assertIn("SessionStart", settings["hooks"])
            self.assertIn("Bash(memory *)", settings["permissions"]["allow"])
            self.assertEqual(settings["hooks"]["SessionStart"][0]["hooks"][0]["command"], "memory hook")

    def test_install_hooks_writes_local_settings_and_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_hooks(root, python_executable="python")

            settings = json.loads((root / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            script = root / ".claude" / "hooks" / "agent-memory-hook.py"
            gitignore = (root / ".gitignore").read_text(encoding="utf-8")

            self.assertTrue(script.exists())
            self.assertIn(".claude/settings.local.json", gitignore)
            self.assertIn(".claude/commands/agent-memory.md", gitignore)
            self.assertIn(".claude/skills/agent-memory/", gitignore)
            self.assertIn(".claude/skills/memory-review/", gitignore)
            self.assertIn(".claude/skills/memory-why/", gitignore)
            self.assertIn(".claude/skills/memory-teach/", gitignore)
            self.assertIn(".claude/skills/memory-doctor/", gitignore)
            self.assertIn(".claude/skills/memory-repair/", gitignore)
            self.assertTrue((root / ".claude" / "commands" / "agent-memory.md").exists())
            self.assertTrue((root / ".claude" / "commands" / "memory-status.md").exists())
            self.assertTrue((root / ".claude" / "commands" / "memory-review.md").exists())
            self.assertTrue((root / ".claude" / "commands" / "memory-why.md").exists())
            self.assertTrue((root / ".claude" / "commands" / "memory-teach.md").exists())
            self.assertTrue((root / ".claude" / "commands" / "memory-doctor.md").exists())
            self.assertTrue((root / ".claude" / "commands" / "memory-repair.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "agent-memory" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "memory-status" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "memory-review" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "memory-why" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "memory-teach" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "memory-doctor" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "memory-repair" / "SKILL.md").exists())
            command_text = (root / ".claude" / "skills" / "agent-memory" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("memory status", command_text)
            self.assertIn("Bash(memory *)", command_text)
            self.assertNotIn("!`", command_text)
            self.assertNotIn("python", command_text.lower())
            self.assertNotIn("agent_memory", command_text)
            self.assertIn("PostToolUseFailure", settings["hooks"])
            self.assertIn("UserPromptSubmit", settings["hooks"])
            self.assertIn("PostToolUse", settings["hooks"])
            self.assertIn("SessionStart", settings["hooks"])
            self.assertEqual(settings["hooks"]["PostToolUseFailure"][0]["hooks"][0]["command"], "memory hook")
            self.assertIn("Bash(memory *)", settings["permissions"]["allow"])

    def test_install_hooks_records_default_project_for_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_hooks(project, python_executable="python")

            default_file = home / ".agent-memory" / "default-project.json"
            self.assertTrue(default_file.exists())
            self.assertEqual(json.loads(default_file.read_text(encoding="utf-8"))["path"], str(project))

    def test_hook_payload_from_home_uses_default_project_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_hooks(project, python_executable="python")

                config = init_project(project)
                db = MemoryDb.open(project)
                db.ensure_project(config["project_id"], project)
                db.insert_lesson(
                    project_id=config["project_id"],
                    title="Project lesson",
                    lesson="Use the remembered project when Claude starts from home.",
                    scope={"files": []},
                    trigger={"terms": ["home", "project"], "commands": []},
                    project_type=None,
                    confidence="medium",
                    confidence_score=0.6,
                    promotion_reason="manual_approval",
                    supporting_event_ids=[],
                )
                db.close()

                payload = {
                    "session_id": "claude-session",
                    "cwd": str(home),
                    "hook_event_name": "SessionStart",
                }
                with io.StringIO() as out, redirect_stdout(out):
                    code = handle_hook_payload(payload)
                    text = out.getvalue()

            response = json.loads(text)
            self.assertEqual(code, 0)
            self.assertIn("Use the remembered project", response["hookSpecificOutput"]["additionalContext"])
            self.assertTrue((project / ".agent-memory" / "claude-context.md").exists())
            self.assertFalse((home / ".agent-memory" / "config.json").exists())

    def test_install_hooks_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            settings_path = root / ".claude" / "settings.local.json"
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(
                json.dumps(
                    {
                        "permissions": {
                            "allow": [
                                "Bash(npm test)",
                                "Bash(& 'C:\\Users\\old\\python.exe' -m agent_memory *)",
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_hooks(root, python_executable="python")

            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIn("Bash(npm test)", settings["permissions"]["allow"])
            self.assertIn("Bash(memory *)", settings["permissions"]["allow"])
            self.assertNotIn("Bash(& 'C:\\Users\\old\\python.exe' -m agent_memory *)", settings["permissions"]["allow"])
            self.assertIn("PostToolUseFailure", settings["hooks"])

    def test_install_hooks_falls_back_to_python_for_hooks_only_when_memory_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value=None):
                install_hooks(root, python_executable="python")

            settings = json.loads((root / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            skill_text = (root / ".claude" / "skills" / "memory-status" / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(settings["hooks"]["SessionStart"][0]["hooks"][0]["command"], '"python" -m agent_memory hook')
            self.assertNotIn("python", skill_text.lower())
            self.assertIn("Bash(memory *)", settings["permissions"]["allow"])

    def test_post_tool_use_failure_records_failed_bash_and_returns_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            lesson_id = db.insert_lesson(
                project_id=config["project_id"],
                title="Auth lesson",
                lesson="Do not trust cached session state.",
                scope={"files": ["src/auth/middleware.ts"]},
                trigger={"terms": ["auth", "middleware", "session"], "commands": ["npm test"]},
                project_type=None,
                confidence="medium",
                confidence_score=0.6,
                promotion_reason="manual_approval",
                supporting_event_ids=[],
            )
            db.close()
            payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "tool_response": {"stderr": "auth middleware session rejected", "exit_code": 1},
            }

            with io.StringIO() as out, redirect_stdout(out):
                code = handle_hook_payload(payload)
                text = out.getvalue()

            response = json.loads(text)
            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            db.close()

            self.assertEqual(code, 0)
            self.assertEqual(events[0]["event_type"], "failed_command")
            self.assertIn("Memory recall", response["hookSpecificOutput"]["additionalContext"])
            self.assertIn(lesson_id, response["hookSpecificOutput"]["additionalContext"])

    def test_post_tool_use_failure_ignores_agent_memory_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            payloads = [
                {
                    "session_id": "claude-session",
                    "cwd": str(root),
                    "hook_event_name": "PostToolUseFailure",
                    "tool_name": "Bash",
                    "tool_input": {"command": 'memory why ""'},
                    "tool_response": {"stderr": "No lesson found", "exit_code": 1},
                },
                {
                    "session_id": "claude-session",
                    "cwd": str(root),
                    "hook_event_name": "PostToolUseFailure",
                    "tool_name": "Bash",
                    "tool_input": {"command": "python -m agent_memory review"},
                    "tool_response": {"stderr": "module failed", "exit_code": 1},
                },
            ]

            for payload in payloads:
                with io.StringIO() as out, redirect_stdout(out):
                    code = handle_hook_payload(payload)
                    text = out.getvalue()
                self.assertEqual(code, 0)
                self.assertEqual(text, "")

            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            candidates = db.list_candidates(config["project_id"])
            db.close()

            self.assertEqual(events, [])
            self.assertEqual(candidates, [])

    def test_repeated_bash_failure_without_file_changes_is_marked_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth" / "middleware.ts"
            source.parent.mkdir(parents=True)
            source.write_text("export const value = 1\n", encoding="utf-8")
            config = init_project(root)
            edit_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/auth/middleware.ts"},
            }
            failure_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "tool_response": {"stderr": "auth middleware session rejected", "exit_code": 1},
            }

            handle_hook_payload(edit_payload)
            with io.StringIO() as out, redirect_stdout(out):
                handle_hook_payload(failure_payload)
                handle_hook_payload(failure_payload)

            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            candidates = db.list_candidates(config["project_id"])
            lessons = db.enabled_lessons(config["project_id"], 10)
            db.close()

            self.assertEqual(events[0]["file_change_state"], "unchanged")
            self.assertEqual(events[1]["file_change_state"], "unknown")
            self.assertEqual(len(candidates), 1)
            self.assertEqual(len(lessons), 0)

    def test_repeated_bash_failure_after_file_change_is_marked_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth" / "middleware.ts"
            source.parent.mkdir(parents=True)
            source.write_text("export const value = 1\n", encoding="utf-8")
            config = init_project(root)
            edit_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/auth/middleware.ts"},
            }
            failure_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "tool_response": {"stderr": "auth middleware session rejected", "exit_code": 1},
            }

            handle_hook_payload(edit_payload)
            with io.StringIO() as out, redirect_stdout(out):
                handle_hook_payload(failure_payload)
            source.write_text("export const value = 2\n", encoding="utf-8")
            with io.StringIO() as out, redirect_stdout(out):
                handle_hook_payload(failure_payload)

            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            db.close()

            self.assertEqual(events[0]["file_change_state"], "changed_since_last_failure")

    def test_repeated_command_only_failure_without_edits_is_marked_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            failure_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "tool_response": {"stderr": "database timeout on startup", "exit_code": 1},
            }

            with io.StringIO() as out, redirect_stdout(out):
                handle_hook_payload(failure_payload)
                handle_hook_payload(failure_payload)

            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            candidates = db.list_candidates(config["project_id"])
            lessons = db.enabled_lessons(config["project_id"], 10)
            db.close()

            self.assertEqual(events[0]["file_change_state"], "unchanged")
            self.assertEqual(events[1]["file_change_state"], "unknown")
            self.assertEqual(len(candidates), 1)
            self.assertEqual(len(lessons), 0)

    def test_repeated_command_only_failure_after_edit_is_marked_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            failure_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "tool_response": {"stderr": "database timeout on startup", "exit_code": 1},
            }
            edit_payload = {
                "session_id": "other-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/config.ts"},
            }

            with io.StringIO() as out, redirect_stdout(out):
                handle_hook_payload(failure_payload)
            handle_hook_payload(edit_payload)
            with io.StringIO() as out, redirect_stdout(out):
                handle_hook_payload(failure_payload)

            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            db.close()

            self.assertEqual(events[0]["file_change_state"], "changed_since_last_failure")

    def test_user_prompt_submit_records_correction_like_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "No, that is wrong. Do not use cached session state.",
            }

            with io.StringIO() as out, redirect_stdout(out):
                code = handle_hook_payload(payload)
                text = out.getvalue()

            db = MemoryDb.open(root)
            events = db.list_events(init_project(root)["project_id"], 20)
            db.close()

            self.assertEqual(code, 0)
            self.assertEqual(text, "")
            self.assertEqual(events[0]["event_type"], "user_correction")

    def test_post_tool_use_tracks_recent_edited_files_for_later_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            edit_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/auth/middleware.ts"},
            }
            correction_payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "No, that is wrong. Do not trust cached session state.",
            }

            handle_hook_payload(edit_payload)
            handle_hook_payload(correction_payload)

            config = init_project(root)
            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            db.close()
            self.assertEqual(events[0]["event_type"], "user_correction")
            self.assertIn("src/auth/middleware.ts", events[0]["files_touched_json"])

    def test_repeated_hook_only_corrections_promote_without_file_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "No, that is wrong. Do not trust cached session state in auth middleware.",
            }

            handle_hook_payload(payload)
            handle_hook_payload(payload)

            config = init_project(root)
            db = MemoryDb.open(root)
            lessons = db.enabled_lessons(config["project_id"], 10)
            db.close()
            self.assertEqual(len(lessons), 1)
            self.assertIn("cached session", lessons[0]["lesson"])

    def test_session_start_regenerates_context_and_returns_additional_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            db.insert_lesson(
                project_id=config["project_id"],
                title="Auth lesson",
                lesson="Do not trust cached session state.",
                scope={"files": ["src/auth/middleware.ts"]},
                trigger={"terms": ["cached", "session"], "commands": []},
                project_type=None,
                confidence="medium",
                confidence_score=0.6,
                promotion_reason="manual_approval",
                supporting_event_ids=[],
            )
            db.close()
            payload = {
                "session_id": "claude-session",
                "cwd": str(root),
                "hook_event_name": "SessionStart",
            }

            with io.StringIO() as out, redirect_stdout(out):
                code = handle_hook_payload(payload)
                text = out.getvalue()

            response = json.loads(text)
            self.assertEqual(code, 0)
            self.assertIn("Do not trust cached session state", response["hookSpecificOutput"]["additionalContext"])
            self.assertIn("Do not trust cached session state", (root / ".agent-memory" / "claude-context.md").read_text())


    def test_handle_stdin_decodes_utf8_payload_with_bom(self):
        # Reproduces the Windows failure mode: the spawned hook process reads
        # stdin under a legacy code page (cp1252) and some shells prepend a
        # UTF-8 BOM. handle_stdin must read raw bytes, strip the BOM, and decode
        # real UTF-8 instead of silently dropping the payload.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            payload = {
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "cwd": str(root),
                "session_id": "s",
                "tool_input": {"command": "npm test"},
                "tool_response": {"stderr": "auth rejected — session → db", "exit_code": 1},
            }
            raw = ("\ufeff" + json.dumps(payload, ensure_ascii=False)).encode("utf-8")
            fake_stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252")
            with patch.object(sys, "stdin", fake_stdin):
                code = handle_stdin()
            self.assertEqual(code, 0)
            db = MemoryDb.open(root)
            events = db.list_events(config["project_id"], 20)
            db.close()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "failed_command")
            # The em dash / arrow survive => decoded as UTF-8, not mojibake.
            self.assertIn("→", events[0]["stderr_excerpt"])

    def test_handle_stdin_ignores_blank_input(self):
        fake_stdin = io.TextIOWrapper(io.BytesIO(b""), encoding="cp1252")
        with patch.object(sys, "stdin", fake_stdin):
            self.assertEqual(handle_stdin(), 0)

    def test_hook_command_pins_absolute_interpreter_for_venv_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "Scripts"
            scripts.mkdir()
            (Path(tmp) / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
            py = scripts / "python.exe"
            py.write_text("", encoding="utf-8")
            mem = scripts / "memory.exe"
            mem.write_text("", encoding="utf-8")
            with patch.object(hooks_module.shutil, "which", return_value=str(mem)):
                command = _hook_command(str(py))
            self.assertTrue(command.endswith("-m agent_memory hook"))
            self.assertIn(str(py), command)

    def test_default_shell_matches_host_os(self):
        with patch.object(hooks_module.os, "name", "nt"):
            self.assertEqual(hooks_module._default_shell(), "powershell")
        with patch.object(hooks_module.os, "name", "posix"):
            self.assertEqual(hooks_module._default_shell(), "bash")

    def test_installed_skills_use_os_appropriate_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            with patch.dict("os.environ", {"USERPROFILE": str(home)}), \
                    patch("shutil.which", return_value="memory"), \
                    patch("agent_memory.hooks._default_shell", return_value="bash"):
                install_claude_global(python_executable="python")
            txt = (home / ".claude" / "skills" / "memory-status" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("shell: bash", txt)
            self.assertNotIn("shell: powershell", txt)

    def test_hook_command_keeps_portable_form_for_global_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "venv" / "Scripts"
            scripts.mkdir(parents=True)
            (Path(tmp) / "venv" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
            py = scripts / "python.exe"
            py.write_text("", encoding="utf-8")
            global_bin = Path(tmp) / "bin"
            global_bin.mkdir()
            global_mem = global_bin / "memory.exe"
            global_mem.write_text("", encoding="utf-8")
            with patch.object(hooks_module.shutil, "which", return_value=str(global_mem)):
                command = _hook_command(str(py))
            self.assertEqual(command, "memory hook")


if __name__ == "__main__":
    unittest.main()
