"""Tests for org_taube.config."""

import os
import tempfile
import unittest
from pathlib import Path

from org_taube.config import BUILTIN_TYPES, load_config


class TestBuiltinTypes(unittest.TestCase):
    """Verify the hard-coded BUILTIN_TYPES dict."""

    def test_builtin_types_present(self):
        # task type
        task = BUILTIN_TYPES["task"]
        self.assertEqual(task.keywords, ["TODO", "DONE"])
        self.assertEqual(task.default_keyword, "TODO")

        # note type
        note = BUILTIN_TYPES["note"]
        self.assertEqual(note.keywords, [])
        self.assertIsNone(note.default_keyword)


class TestLoadConfig(unittest.TestCase):
    """Tests that exercise load_config with various TOML inputs."""

    def setUp(self):
        self._tmpfiles: list[str] = []

    def tearDown(self):
        for p in self._tmpfiles:
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass

    # -- helpers ----------------------------------------------------------

    def _write_toml(self, text: str) -> Path:
        """Write *text* to a temp .toml file and return its Path."""
        fd, name = tempfile.mkstemp(suffix=".toml")
        os.write(fd, text.encode())
        os.close(fd)
        self._tmpfiles.append(name)
        return Path(name)

    # -- tests ------------------------------------------------------------

    def test_load_minimal_config(self):
        """Only [maildir] with path; everything else should be defaults."""
        cfg = load_config(self._write_toml(
            '[maildir]\npath = "/var/mail/capture"\n'
        ))
        self.assertEqual(cfg.maildir_path, Path("/var/mail/capture"))
        self.assertIsNone(cfg.default_file)
        self.assertIn("task", cfg.types)
        self.assertIn("note", cfg.types)
        self.assertFalse(cfg.trust_all)
        self.assertEqual(cfg.post_process, "read")
        self.assertEqual(cfg.signature_separator, "-- ")

    def test_load_full_config(self):
        """All sections populated — verify every field round-trips."""
        toml = (
            '[maildir]\n'
            'path = "/var/mail/capture"\n'
            '\n'
            '[defaults]\n'
            'file = "/org/inbox.org"\n'
            'attachment_path = "/org/attachments"\n'
            '\n'
            '[types.task]\n'
            'file = "/org/tasks.org"\n'
            'parent = "Tasks"\n'
            '\n'
            '[types.workout]\n'
            'file = "/org/workout.org"\n'
            'tags = ["exercise", "health"]\n'
            'properties = ["duration", "distance"]\n'
            'attachment_path = "/org/attachments/workout"\n'
        )
        cfg = load_config(self._write_toml(toml))

        # maildir
        self.assertEqual(cfg.maildir_path, Path("/var/mail/capture"))

        # defaults
        self.assertEqual(cfg.default_file, Path("/org/inbox.org"))
        self.assertEqual(cfg.default_attachment_path, Path("/org/attachments"))

        # task type — file/parent from config, keywords from built-in
        task = cfg.types["task"]
        self.assertEqual(task.file, Path("/org/tasks.org"))
        self.assertEqual(task.parent, "Tasks")
        self.assertEqual(task.keywords, ["TODO", "DONE"])
        self.assertEqual(task.default_keyword, "TODO")

        # workout type — fully custom
        wo = cfg.types["workout"]
        self.assertEqual(wo.file, Path("/org/workout.org"))
        self.assertEqual(wo.tags, ["exercise", "health"])
        self.assertEqual(wo.properties, ["duration", "distance"])
        self.assertEqual(wo.attachment_path, Path("/org/attachments/workout"))
        self.assertEqual(wo.keywords, [])
        self.assertIsNone(wo.default_keyword)

    def test_missing_config_file(self):
        """A non-existent path must raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            load_config(Path("/tmp/does_not_exist_org_taube.toml"))

    def test_missing_maildir_path(self):
        """[maildir] present but no path key must raise ValueError."""
        with self.assertRaises(ValueError):
            load_config(self._write_toml("[maildir]\n"))

    def test_invalid_post_process(self):
        """post_process values other than 'read'/'delete' must raise."""
        toml = (
            '[maildir]\npath = "/m"\n'
            'post_process = "archive"\n'
        )
        with self.assertRaises(ValueError):
            load_config(self._write_toml(toml))

    def test_defaults_without_file(self):
        """[defaults] without file is valid — default_file stays None."""
        toml = (
            '[maildir]\npath = "/m"\n'
            '[defaults]\n'
            'attachment_path = "/org/att"\n'
        )
        cfg = load_config(self._write_toml(toml))
        self.assertIsNone(cfg.default_file)
        self.assertEqual(cfg.default_attachment_path, Path("/org/att"))

    def test_parse_type_builtin_overlay(self):
        """Configuring [types.task] preserves built-in keywords."""
        toml = (
            '[maildir]\npath = "/m"\n'
            '[types.task]\n'
            'file = "/org/tasks.org"\n'
            'parent = "Tasks"\n'
        )
        cfg = load_config(self._write_toml(toml))
        task = cfg.types["task"]
        self.assertEqual(task.keywords, ["TODO", "DONE"])
        self.assertEqual(task.default_keyword, "TODO")
        self.assertEqual(task.file, Path("/org/tasks.org"))
        self.assertEqual(task.parent, "Tasks")

    def test_task_extra_keywords_merged(self):
        """Extra keywords in [types.task] merge with built-in TODO/DONE."""
        toml = (
            '[maildir]\npath = "/m"\n'
            '[types.task]\n'
            'file = "/org/tasks.org"\n'
            'keywords = ["NEXT", "WAITING"]\n'
        )
        cfg = load_config(self._write_toml(toml))
        task = cfg.types["task"]
        self.assertEqual(task.keywords, ["TODO", "DONE", "NEXT", "WAITING"])
        self.assertEqual(task.default_keyword, "TODO")

    def test_task_duplicate_keywords_ignored(self):
        """Duplicate keywords (case-insensitive) are not added twice."""
        toml = (
            '[maildir]\npath = "/m"\n'
            '[types.task]\n'
            'keywords = ["todo", "NEXT"]\n'
        )
        cfg = load_config(self._write_toml(toml))
        task = cfg.types["task"]
        self.assertEqual(task.keywords, ["TODO", "DONE", "NEXT"])

    def test_parse_type_custom(self):
        """A custom type gets empty keywords and no default_keyword."""
        toml = (
            '[maildir]\npath = "/m"\n'
            '[types.workout]\n'
            'file = "/org/workout.org"\n'
        )
        cfg = load_config(self._write_toml(toml))
        wo = cfg.types["workout"]
        self.assertEqual(wo.keywords, [])
        self.assertIsNone(wo.default_keyword)

    def test_custom_type_with_keywords(self):
        """Custom types can define keywords for subject-line routing."""
        toml = (
            '[maildir]\npath = "/m"\n'
            '[types.txn]\n'
            'file = "/finance/captures.org"\n'
            'keywords = ["TXN"]\n'
        )
        cfg = load_config(self._write_toml(toml))
        txn = cfg.types["txn"]
        self.assertEqual(txn.keywords, ["TXN"])
        self.assertIsNone(txn.default_keyword)

    def test_tilde_expansion(self):
        """Paths containing ~ must be expanded to the real home dir."""
        home = Path.home()
        toml = (
            '[maildir]\npath = "~/mail"\n'
            '[defaults]\nfile = "~/org/inbox.org"\n'
            'attachment_path = "~/org/att"\n'
            '[types.task]\nfile = "~/org/tasks.org"\n'
        )
        cfg = load_config(self._write_toml(toml))
        self.assertEqual(cfg.maildir_path, home / "mail")
        self.assertEqual(cfg.default_file, home / "org" / "inbox.org")
        self.assertEqual(cfg.default_attachment_path, home / "org" / "att")
        self.assertEqual(cfg.types["task"].file, home / "org" / "tasks.org")


if __name__ == "__main__":
    unittest.main()
