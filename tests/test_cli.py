import io
import sys
import tempfile
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_memory.cli import _since_value, build_parser, main
from agent_memory.config import init_project
from agent_memory.db import MemoryDb


class CliParserTests(unittest.TestCase):
    def test_events_prints_unicode_under_legacy_codepage(self):
        # On Windows a redirected/piped CLI gets a legacy code page (cp1252) for
        # stdout. Printing a stored non-ASCII character must not crash with
        # UnicodeEncodeError; main() forces UTF-8 output.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="user_correction",
                source="manual",
                summary="verify user → db (café) — don’t cache",
                command=None,
                exit_code=None,
                stderr_excerpt=None,
                user_text="x",
                files_touched=[],
                file_change_state="unknown",
            )
            db.close()

            buffer = io.BytesIO()
            cp1252_stdout = io.TextIOWrapper(buffer, encoding="cp1252")
            with patch("pathlib.Path.cwd", return_value=root), patch.object(sys, "stdout", cp1252_stdout):
                code = main(["events"])
                sys.stdout.flush()

            output = buffer.getvalue().decode("utf-8")
            self.assertEqual(code, 0)
            self.assertIn("→", output)
            self.assertIn("café", output)

    def test_parser_supports_core_commands(self):
        parser = build_parser()

        for command in ("init", "status", "config"):
            with self.subTest(command=command):
                args = parser.parse_args([command])
                self.assertEqual(args.command, command)

        args = parser.parse_args(["install-claude", "--global"])
        self.assertEqual(args.command, "install-claude")
        self.assertTrue(args.global_install)

        args = parser.parse_args(["doctor", "--fix", "--json"])
        self.assertEqual(args.command, "doctor")
        self.assertTrue(args.fix)
        self.assertTrue(args.json)

        args = parser.parse_args(["review", "--json", "--limit", "3"])
        self.assertEqual(args.command, "review")
        self.assertTrue(args.json)
        self.assertEqual(args.limit, 3)

    def test_parser_supports_list_commands_with_filters(self):
        parser = build_parser()

        for command in ("lessons", "events"):
            with self.subTest(command=command):
                args = parser.parse_args([command])
                self.assertEqual(args.command, command)
                self.assertFalse(args.all)
                self.assertIsNone(args.since)
                self.assertEqual(args.limit, 20)

                args = parser.parse_args([command, "--all", "--since", "7d", "--limit", "5"])
                self.assertTrue(args.all)
                self.assertEqual(args.since, "7d")
                self.assertEqual(args.limit, 5)

    def test_parser_supports_recall_query(self):
        parser = build_parser()

        args = parser.parse_args(["recall", "auth middleware JWT failure"])

        self.assertEqual(args.command, "recall")
        self.assertEqual(args.query, "auth middleware JWT failure")

    def test_since_value_accepts_duration(self):
        value = _since_value("7d")

        self.assertIsNotNone(value)
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T")

    def test_parser_supports_id_commands(self):
        parser = build_parser()

        for command in ("approve", "reject", "forget", "why"):
            with self.subTest(command=command):
                args = parser.parse_args([command, "item_123"])
                self.assertEqual(args.command, command)
                self.assertEqual(args.id, "item_123")

    def test_cli_init_prints_initialized_project_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["init"])
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("initialized project", text)
            self.assertIn("proj_", text)

    def test_status_prints_project_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["status"])
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn(config["project_id"], text)

    def test_doctor_json_reports_global_install_and_project_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            root.mkdir()
            home.mkdir()
            config = init_project(root)

            from agent_memory.hooks import install_claude_global, install_hooks
            from agent_memory.context import render_context

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_claude_global(python_executable="python")
                install_hooks(root, python_executable="python")
                db = MemoryDb.open(root)
                try:
                    db.ensure_project(config["project_id"], root)
                    render_context(root, db, config)
                finally:
                    db.close()
                with patch("pathlib.Path.cwd", return_value=root):
                    with io.StringIO() as out, redirect_stdout(out):
                        code = main(["doctor", "--json"])
                        payload = json.loads(out.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["project_id"], config["project_id"])
            checks = {check["id"]: check for check in payload["checks"]}
            self.assertEqual(checks["memory_on_path"]["status"], "ok")
            self.assertEqual(checks["global_settings"]["status"], "ok")
            self.assertEqual(checks["global_skills"]["status"], "ok")
            self.assertEqual(checks["default_project"]["status"], "ok")
            self.assertEqual(checks["project_memory"]["status"], "ok")

    def test_doctor_warns_when_default_project_points_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            other = Path(tmp) / "other"
            home = Path(tmp) / "home"
            root.mkdir()
            other.mkdir()
            home.mkdir()

            from agent_memory.hooks import install_claude_global, install_hooks

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_claude_global(python_executable="python")
                install_hooks(other, python_executable="python")
                with patch("pathlib.Path.cwd", return_value=root):
                    with io.StringIO() as out, redirect_stdout(out):
                        code = main(["doctor", "--json"])
                        payload = json.loads(out.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "warning")
            checks = {check["id"]: check for check in payload["checks"]}
            self.assertEqual(checks["default_project"]["status"], "warning")
            self.assertIn(str(other), checks["default_project"]["message"])

    def test_doctor_warns_for_stale_project_local_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            root.mkdir()
            home.mkdir()

            from agent_memory.hooks import install_claude_global, install_hooks

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_claude_global(python_executable="python")
                install_hooks(root, python_executable="python")
                local_settings = root / ".claude" / "settings.local.json"
                local_settings.write_text(
                    json.dumps(
                        {
                            "hooks": {
                                "SessionStart": [
                                    {"hooks": [{"type": "command", "command": '"python" -m agent_memory hook'}]}
                                ]
                            },
                            "permissions": {
                                "allow": [
                                    "Bash(& 'C:\\Users\\old\\python.exe' -m agent_memory *)",
                                ]
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                with patch("pathlib.Path.cwd", return_value=root):
                    with io.StringIO() as out, redirect_stdout(out):
                        code = main(["doctor", "--json"])
                        payload = json.loads(out.getvalue())

            self.assertEqual(code, 1)
            self.assertEqual(payload["status"], "error")
            checks = {check["id"]: check for check in payload["checks"]}
            self.assertEqual(checks["project_local_hooks"]["status"], "error")
            self.assertEqual(checks["project_local_permissions"]["status"], "warning")

    def test_doctor_fix_repairs_stale_project_local_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            root.mkdir()
            home.mkdir()

            from agent_memory.hooks import install_claude_global, install_hooks

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_claude_global(python_executable="python")
                install_hooks(root, python_executable="python")
                local_settings = root / ".claude" / "settings.local.json"
                local_settings.write_text(
                    json.dumps(
                        {
                            "hooks": {
                                "SessionStart": [
                                    {"hooks": [{"type": "command", "command": '"python" -m agent_memory hook'}]}
                                ]
                            },
                            "permissions": {
                                "allow": [
                                    "Bash(& 'C:\\Users\\old\\python.exe' -m agent_memory *)",
                                ]
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                with patch("pathlib.Path.cwd", return_value=root):
                    with io.StringIO() as out, redirect_stdout(out):
                        code = main(["doctor", "--fix", "--json"])
                        payload = json.loads(out.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "ok")
            checks = {check["id"]: check for check in payload["checks"]}
            self.assertEqual(checks["project_local_hooks"]["status"], "ok")
            self.assertEqual(checks["project_local_permissions"]["status"], "ok")
            settings = json.loads(local_settings.read_text(encoding="utf-8"))
            self.assertEqual(settings["hooks"]["SessionStart"][0]["hooks"][0]["command"], "memory hook")
            self.assertIn("Bash(memory *)", settings["permissions"]["allow"])
            self.assertNotIn("Bash(& 'C:\\Users\\old\\python.exe' -m agent_memory *)", settings["permissions"]["allow"])

    def test_doctor_warns_when_generated_context_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            root.mkdir()
            home.mkdir()
            config = init_project(root)

            from agent_memory.hooks import install_claude_global, install_hooks

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
            context_path = root / ".agent-memory" / "claude-context.md"
            context_path.parent.mkdir(parents=True, exist_ok=True)
            context_path.write_text("No promoted lessons yet.\n", encoding="utf-8")

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                install_claude_global(python_executable="python")
                install_hooks(root, python_executable="python")
                context_path.write_text("No promoted lessons yet.\n", encoding="utf-8")
                with patch("pathlib.Path.cwd", return_value=root):
                    with io.StringIO() as out, redirect_stdout(out):
                        code = main(["doctor", "--json"])
                        payload = json.loads(out.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "warning")
            checks = {check["id"]: check for check in payload["checks"]}
            self.assertEqual(checks["generated_context"]["status"], "warning")

    def test_doctor_fix_regenerates_stale_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            root.mkdir()
            home.mkdir()
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
            context_path = root / ".agent-memory" / "claude-context.md"
            context_path.parent.mkdir(parents=True, exist_ok=True)
            context_path.write_text("No promoted lessons yet.\n", encoding="utf-8")

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                with patch("pathlib.Path.cwd", return_value=root):
                    with io.StringIO() as out, redirect_stdout(out):
                        code = main(["doctor", "--fix", "--json"])
                        payload = json.loads(out.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "ok")
            checks = {check["id"]: check for check in payload["checks"]}
            self.assertEqual(checks["generated_context"]["status"], "ok")
            self.assertIn("Do not trust cached session state", context_path.read_text(encoding="utf-8"))

    def test_doctor_fix_repairs_missing_global_and_project_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            home = Path(tmp) / "home"
            root.mkdir()
            home.mkdir()

            with patch.dict("os.environ", {"USERPROFILE": str(home)}), patch("shutil.which", return_value="memory"):
                with patch("pathlib.Path.cwd", return_value=root):
                    with io.StringIO() as out, redirect_stdout(out):
                        code = main(["doctor", "--fix", "--json"])
                        payload = json.loads(out.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["repairs"][0]["status"], "ok")
            self.assertTrue((home / ".claude" / "settings.json").exists())
            default_project = home / ".agent-memory" / "default-project.json"
            self.assertEqual(json.loads(default_project.read_text(encoding="utf-8"))["path"], str(root))
            self.assertTrue((home / ".claude" / "skills" / "memory-repair" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "settings.local.json").exists())
            self.assertTrue((root / ".claude" / "skills" / "memory-repair" / "SKILL.md").exists())

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
            db.close()

            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["events"])
                    lines = [line for line in out.getvalue().splitlines() if line.startswith("evt_")]

            self.assertEqual(code, 0)
            self.assertEqual(len(lines), 20)

    def test_record_failure_creates_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(
                        [
                            "record-failure",
                            "--command",
                            "npm test",
                            "--stderr",
                            "auth middleware session rejected",
                            "--file",
                            "src/auth/middleware.ts",
                        ]
                    )
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Recorded evt_", text)

    def test_approve_promotes_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            candidate_id = db.insert_candidate(
                project_id=config["project_id"],
                title="Auth lesson",
                failure_pattern="auth failed",
                suspected_cause="cached state",
                recommended_fix="Do not trust cached session state.",
                scope={"files": ["src/auth/middleware.ts"]},
                trigger={"terms": ["cached", "session"], "commands": ["npm test"]},
                supporting_event_ids=["evt_1"],
                repeat_count=1,
                confidence_score=0.5,
            )

            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["approve", candidate_id])
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Promoted", text)
            reopened = MemoryDb.open(root)
            self.assertEqual(len(reopened.enabled_lessons(config["project_id"], 10)), 1)
            reopened.close()
            db.close()

    def test_lessons_export_writes_generated_files(self):
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
                trigger={"terms": ["cached", "session"], "commands": ["npm test"]},
                project_type="next.js",
                confidence="medium",
                confidence_score=0.6,
                promotion_reason="manual_approval",
                supporting_event_ids=[],
            )
            db.close()

            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["lessons", "--export"])
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Exported memory", text)
            self.assertTrue((root / ".agent-memory" / "exports" / "lessons" / f"{lesson_id}.json").exists())

    def test_why_prints_candidate_and_raw_event_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="user_correction",
                source="manual",
                summary="Do not trust cached session state",
                command=None,
                exit_code=None,
                stderr_excerpt=None,
                user_text="Do not trust cached session state",
                files_touched=["src/auth/middleware.ts"],
                file_change_state="unknown",
            )
            candidate_id = db.insert_candidate(
                project_id=config["project_id"],
                title="Auth lesson",
                failure_pattern="auth failed",
                suspected_cause="cached state",
                recommended_fix="Do not trust cached session state.",
                scope={"files": ["src/auth/middleware.ts"]},
                trigger={"terms": ["cached", "session"], "commands": ["npm test"]},
                supporting_event_ids=[event_id],
                repeat_count=1,
                confidence_score=0.5,
            )
            lesson_id = db.insert_lesson(
                project_id=config["project_id"],
                title="Auth lesson",
                lesson="Do not trust cached session state.",
                scope={"files": ["src/auth/middleware.ts"]},
                trigger={"terms": ["cached", "session"], "commands": ["npm test"]},
                project_type=None,
                confidence="medium",
                confidence_score=0.6,
                promotion_reason="manual_approval",
                supporting_event_ids=[event_id],
            )
            db.mark_candidate_merged(candidate_id, lesson_id)
            db.close()

            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["why", lesson_id])
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn(candidate_id, text)
            self.assertIn(event_id, text)
            self.assertIn("Pattern: auth failed", text)

    def test_review_prints_actionable_candidate_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            event_id = db.insert_raw_event(
                project_id=config["project_id"],
                session_id=None,
                event_type="user_correction",
                source="manual",
                summary="Do not trust cached session state",
                command=None,
                exit_code=None,
                stderr_excerpt=None,
                user_text="Do not trust cached session state",
                files_touched=["src/auth/middleware.ts"],
                file_change_state="unknown",
            )
            candidate_id = db.insert_candidate(
                project_id=config["project_id"],
                title="Auth lesson",
                failure_pattern="auth failed",
                suspected_cause="cached state",
                recommended_fix="Remember this user correction before changing related code: do not trust cached session state.",
                scope={"files": ["src/auth/middleware.ts"]},
                trigger={"terms": ["cached", "session"], "commands": []},
                supporting_event_ids=[event_id],
                repeat_count=2,
                confidence_score=0.65,
            )
            db.close()

            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["review"])
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn(candidate_id, text)
            self.assertIn("Recommended: approve", text)
            self.assertIn(f"memory approve {candidate_id}", text)
            self.assertIn(f"memory reject {candidate_id}", text)
            self.assertIn("Do not trust cached session state", text)

    def test_review_json_includes_candidate_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            candidate_id = db.insert_candidate(
                project_id=config["project_id"],
                title="Test command lesson",
                failure_pattern="npm test failed",
                suspected_cause="wrong test runner",
                recommended_fix="Use python -m unittest discover -s tests.",
                scope={"files": []},
                trigger={"terms": ["python", "unittest"], "commands": ["npm test"]},
                supporting_event_ids=[],
                repeat_count=1,
                confidence_score=0.3,
            )
            db.close()

            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(["review", "--json"])
                    payload = json.loads(out.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "needs_review")
            self.assertEqual(payload["candidates"][0]["id"], candidate_id)
            self.assertEqual(payload["candidates"][0]["recommended_action"], "needs_more_evidence")
            self.assertEqual(payload["candidates"][0]["approve_command"], f"memory approve {candidate_id}")

    def test_record_failure_prints_recall_when_lesson_matches(self):
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

            with patch("pathlib.Path.cwd", return_value=root):
                with io.StringIO() as out, redirect_stdout(out):
                    code = main(
                        [
                            "record-failure",
                            "--command",
                            "npm test",
                            "--stderr",
                            "auth middleware session rejected",
                            "--file",
                            "src/auth/middleware.ts",
                        ]
                    )
                    text = out.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Memory recall:", text)
            self.assertIn(lesson_id, text)


if __name__ == "__main__":
    unittest.main()
