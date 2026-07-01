import json
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
            db.close()

            self.assertEqual(result, "skipped_low_signal")

    def test_repeat_threshold_promotes_candidate_to_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)

            result = None
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
            db.close()
            self.assertEqual(result, "promoted")
            self.assertEqual(len(lessons), 1)
            self.assertIn("cached session", lessons[0]["lesson"])

    def test_user_correction_merges_with_existing_failure_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)

            for stderr in ("auth middleware session rejected", "auth middleware session rejected"):
                event_id = db.insert_raw_event(
                    project_id=config["project_id"],
                    session_id=None,
                    event_type="failed_command",
                    source="claude_hook",
                    summary="npm test failed",
                    command="npm test",
                    exit_code=1,
                    stderr_excerpt=stderr,
                    user_text=None,
                    files_touched=["src/auth/middleware.ts"],
                    file_change_state="unknown",
                )
                process_raw_event(db, config, event_id)

            for correction in (
                "No, that is wrong. Do not trust cached session state in auth middleware.",
                "No, still wrong. Do not trust cached session state in auth middleware.",
            ):
                event_id = db.insert_raw_event(
                    project_id=config["project_id"],
                    session_id=None,
                    event_type="user_correction",
                    source="claude_hook",
                    summary=correction,
                    command=None,
                    exit_code=None,
                    stderr_excerpt=None,
                    user_text=correction,
                    files_touched=["src/auth/middleware.ts"],
                    file_change_state="unknown",
                )
                process_raw_event(db, config, event_id)

            lessons = db.enabled_lessons(config["project_id"], 10)
            db.close()
            self.assertEqual(len(lessons), 1)
            self.assertIn("Remember this user correction", lessons[0]["lesson"])
            self.assertIn("cached session", lessons[0]["lesson"])

    def test_identical_correction_on_different_files_merges_to_one_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)

            def failure_then_correction(filepath):
                fid = db.insert_raw_event(
                    project_id=config["project_id"], session_id=None,
                    event_type="failed_command", source="claude_hook",
                    summary="pytest failed", command="python -m pytest", exit_code=1,
                    stderr_excerpt="RuntimeError asyncio event loop already running in handler",
                    user_text=None, files_touched=[filepath],
                    file_change_state="changed_since_last_failure",
                )
                process_raw_event(db, config, fid)
                cid = db.insert_raw_event(
                    project_id=config["project_id"], session_id=None,
                    event_type="user_correction", source="claude_hook",
                    summary="never call asyncio run inside handler",
                    command=None, exit_code=None, stderr_excerpt=None,
                    user_text="never call asyncio run inside handler await the coroutine",
                    files_touched=[filepath], file_change_state="unknown",
                )
                return process_raw_event(db, config, cid)

            self.assertEqual(failure_then_correction("src/cmd_a.py"), "promoted")
            failure_then_correction("src/cmd_b.py")

            lessons = db.enabled_lessons(config["project_id"], 100)
            asyncio_lessons = [l for l in lessons if "asyncio" in l["lesson"].lower()]
            scope_files = json.loads(asyncio_lessons[0]["scope_json"]).get("files", []) if asyncio_lessons else []
            db.close()

            # identical advice at two files collapses into one lesson covering both
            self.assertEqual(len(asyncio_lessons), 1)
            self.assertIn("src/cmd_a.py", scope_files)
            self.assertIn("src/cmd_b.py", scope_files)


if __name__ == "__main__":
    unittest.main()
