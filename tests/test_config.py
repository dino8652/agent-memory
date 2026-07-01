import json
import tempfile
import unittest
from pathlib import Path

from agent_memory.config import DEFAULT_CONFIG, init_project, load_config
from agent_memory.paths import config_path, context_path, db_path, memory_dir, project_root


class ConfigTests(unittest.TestCase):
    def test_default_config_has_expected_keys_and_values(self):
        self.assertEqual(
            sorted(DEFAULT_CONFIG.keys()),
            [
                "git_mode",
                "max_context_tokens",
                "max_lessons_injected",
                "min_signal_threshold",
                "project_id",
                "repeat_threshold",
                "version",
            ],
        )
        self.assertEqual(DEFAULT_CONFIG["version"], 1)
        self.assertEqual(DEFAULT_CONFIG["project_id"], "")
        self.assertEqual(DEFAULT_CONFIG["git_mode"], "local_only")
        self.assertEqual(DEFAULT_CONFIG["repeat_threshold"], 2)
        self.assertEqual(DEFAULT_CONFIG["max_lessons_injected"], 10)
        self.assertEqual(DEFAULT_CONFIG["max_context_tokens"], 800)
        self.assertEqual(DEFAULT_CONFIG["min_signal_threshold"], 0.4)

    def test_path_helpers_resolve_agent_memory_files(self):
        root = Path("project")

        self.assertEqual(project_root(root), root)
        self.assertEqual(memory_dir(root), root / ".agent-memory")
        self.assertEqual(config_path(root), root / ".agent-memory" / "config.json")
        self.assertEqual(db_path(root), root / ".agent-memory" / "index.sqlite")
        self.assertEqual(context_path(root), root / ".agent-memory" / "claude-context.md")

    def test_init_project_writes_default_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            config = init_project(root)

            self.assertTrue(config_path(root).exists())
            self.assertIn(".agent-memory/", (root / ".gitignore").read_text(encoding="utf-8"))
            self.assertEqual(config["git_mode"], "local_only")
            self.assertEqual(config["repeat_threshold"], 2)
            self.assertEqual(config["max_lessons_injected"], 10)
            self.assertEqual(config["max_context_tokens"], 800)
            self.assertEqual(config["min_signal_threshold"], 0.4)
            self.assertRegex(config["project_id"], r"^proj_[0-9a-f]{12}$")
            self.assertEqual(load_config(root), config)

    def test_init_project_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            first = init_project(root, git_mode="commit_lessons")
            second = init_project(root)

            self.assertEqual(second, first)
            self.assertEqual(second["git_mode"], "commit_lessons")

    def test_init_project_gitignore_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            init_project(root)
            init_project(root)

            text = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(text.count(".agent-memory/"), 1)

    def test_load_config_fills_missing_keys_from_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            # Simulate an older on-disk config predating newer keys.
            config_path(root).write_text(
                json.dumps({"version": 1, "project_id": "proj_old", "git_mode": "local_only"}),
                encoding="utf-8",
            )

            config = load_config(root)

            self.assertEqual(config["project_id"], "proj_old")
            self.assertEqual(config["min_signal_threshold"], DEFAULT_CONFIG["min_signal_threshold"])
            self.assertEqual(config["repeat_threshold"], DEFAULT_CONFIG["repeat_threshold"])
            self.assertEqual(config["max_context_tokens"], DEFAULT_CONFIG["max_context_tokens"])

    def test_init_project_rewrites_corrupt_config_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            config_path(root).write_text("{ this is not valid json", encoding="utf-8")

            config = init_project(root)

            self.assertRegex(config["project_id"], r"^proj_[0-9a-f]{12}$")
            self.assertEqual(load_config(root)["project_id"], config["project_id"])


if __name__ == "__main__":
    unittest.main()
