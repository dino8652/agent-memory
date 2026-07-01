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
            db.close()

            self.assertIn("projects", tables)
            self.assertIn("sessions", tables)
            self.assertIn("raw_events", tables)
            self.assertIn("candidate_patterns", tables)
            self.assertIn("lessons", tables)
            self.assertIn("injections", tables)

    def test_open_sets_busy_timeout_for_concurrent_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            db = MemoryDb.open(root)
            timeout = db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
            db.close()
            self.assertGreaterEqual(timeout, 10000)

    def test_session_lifecycle_marks_previous_started_failed_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            first = db.start_session(config["project_id"], "claude")

            closed = db.cleanup_open_sessions(config["project_id"])

            row = db.get_session(first)
            db.close()
            self.assertEqual(row["status"], "failed_open")
            self.assertIsNotNone(row["ended_at"])
            self.assertEqual(closed, 1)

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
            db.close()
            self.assertEqual(event["event_type"], "failed_command")
            self.assertEqual(event["command"], "npm test")

    def test_insert_raw_event_redacts_before_storage(self):
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
                summary="secret failure",
                command="npm test",
                exit_code=1,
                stderr_excerpt="Bearer abc password=hunter2",
                user_text="secret=value",
                files_touched=[],
                file_change_state="unknown",
            )

            event = db.get_raw_event(event_id)
            db.close()
            self.assertNotIn("Bearer abc", event["stderr_excerpt"])
            self.assertNotIn("password=hunter2", event["stderr_excerpt"])
            self.assertNotIn("secret=value", event["user_text"])


if __name__ == "__main__":
    unittest.main()
