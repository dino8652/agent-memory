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
            lesson_id = db.insert_lesson(
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

            path = render_context(root, db, config, session_id="ses_1")
            text = path.read_text(encoding="utf-8")

            self.assertIn("Learned Failure Patterns", text)
            self.assertIn("Auth Middleware", text)
            self.assertIn("Verify the user directly", text)
            self.assertIn(f"Lesson ID: {lesson_id}", text)
            self.assertEqual(len(db.injection_history(lesson_id)), 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
