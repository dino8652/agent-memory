import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from agent_memory import wrapper as wrapper_module
from agent_memory.config import init_project
from agent_memory.db import MemoryDb
from agent_memory.wrapper import discover_claude_command, effective_root, prepare_session, run_claude


class WrapperTests(unittest.TestCase):
    def test_prepare_session_cleans_previous_open_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            old_session = db.start_session(config["project_id"], "claude")

            session_id = prepare_session(root, claude_command="claude")

            reopened = MemoryDb.open(root)
            self.assertEqual(reopened.get_session(old_session)["status"], "failed_open")
            self.assertEqual(reopened.get_session(session_id)["status"], "started")
            reopened.close()
            db.close()

    def test_run_claude_marks_session_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = init_project(root)
            db = MemoryDb.open(root)
            db.ensure_project(config["project_id"], root)
            session_id = db.start_session(config["project_id"], "claude")

            with patch("subprocess.call", return_value=0) as call:
                code = run_claude(root, session_id, ["claude"])

            self.assertEqual(code, 0)
            call.assert_called_once_with(["claude"], cwd=root)
            reopened = MemoryDb.open(root)
            self.assertEqual(reopened.get_session(session_id)["status"], "completed")
            reopened.close()
            db.close()

    def test_discover_claude_command_uses_path_first(self):
        with patch("shutil.which", return_value="C:\\Tools\\claude.exe"):
            self.assertEqual(discover_claude_command(), "C:\\Tools\\claude.exe")

    def test_discover_claude_command_finds_native_windows_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = (
                root
                / "Packages"
                / "Claude_test"
                / "LocalCache"
                / "Roaming"
                / "Claude"
                / "claude-code"
                / "2.1.187"
                / "claude.exe"
            )
            exe.parent.mkdir(parents=True)
            exe.write_text("", encoding="utf-8")

            with patch("shutil.which", return_value=None), patch.dict("os.environ", {"LOCALAPPDATA": str(root)}), \
                    patch.object(wrapper_module.os, "name", "nt"):
                self.assertEqual(discover_claude_command(), str(exe))

    def test_discover_claude_command_skips_windows_glob_on_unix(self):
        with patch("shutil.which", return_value=None), patch.object(wrapper_module.os, "name", "posix"):
            self.assertIsNone(discover_claude_command())

    def test_effective_root_uses_default_project_from_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "project"
            home.mkdir()
            project.mkdir()
            default_dir = home / ".agent-memory"
            default_dir.mkdir()
            (default_dir / "default-project.json").write_text(json.dumps({"path": str(project)}), encoding="utf-8")

            with patch.dict("os.environ", {"USERPROFILE": str(home)}):
                self.assertEqual(effective_root(home), project)


if __name__ == "__main__":
    unittest.main()
