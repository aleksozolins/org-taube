"""Tests for org_taube.types.TypeEngine."""

import unittest
from pathlib import Path

from org_taube import Config, TypeConfig
from org_taube.config import BUILTIN_TYPES
from org_taube.types import TypeEngine


class TestSubjectPrefixResolution(unittest.TestCase):
    """Subject-prefix resolution via resolve_subject_prefix."""

    def setUp(self) -> None:
        self.engine = TypeEngine(dict(BUILTIN_TYPES))

    def test_keyword_match_todo(self) -> None:
        title, tc, kw = self.engine.resolve_subject_prefix("TODO Buy groceries")
        self.assertEqual(title, "Buy groceries")
        self.assertEqual(tc.name, "task")
        self.assertEqual(kw, "TODO")

    def test_keyword_match_done(self) -> None:
        title, tc, kw = self.engine.resolve_subject_prefix("DONE Fix the leak")
        self.assertEqual(tc.name, "task")
        self.assertEqual(kw, "DONE")

    def test_keyword_case_insensitive(self) -> None:
        title, tc, kw = self.engine.resolve_subject_prefix("todo something")
        self.assertEqual(tc.name, "task")
        self.assertEqual(kw, "TODO")

    def test_no_match_note_fallback(self) -> None:
        title, tc, kw = self.engine.resolve_subject_prefix("Meeting notes")
        self.assertEqual(title, "Meeting notes")
        self.assertEqual(tc.name, "note")
        self.assertIsNone(kw)

    def test_empty_subject(self) -> None:
        title, tc, kw = self.engine.resolve_subject_prefix("")
        self.assertEqual(title, "")
        self.assertEqual(tc.name, "note")
        self.assertIsNone(kw)

    def test_keyword_only_no_rest(self) -> None:
        title, tc, kw = self.engine.resolve_subject_prefix("TODO")
        self.assertEqual(title, "")
        self.assertEqual(tc.name, "task")
        self.assertEqual(kw, "TODO")

    def test_type_name_not_matched_in_subject(self) -> None:
        types = dict(BUILTIN_TYPES)
        types["workout"] = TypeConfig(name="workout")
        engine = TypeEngine(types)
        title, tc, kw = engine.resolve_subject_prefix("workout ran 5k")
        self.assertEqual(tc.name, "note")
        self.assertEqual(title, "workout ran 5k")
        self.assertIsNone(kw)

    def test_custom_type_keyword_routes_without_rendering(self) -> None:
        types = dict(BUILTIN_TYPES)
        types["txn"] = TypeConfig(name="txn", keywords=["TXN"])
        engine = TypeEngine(types)
        title, tc, kw = engine.resolve_subject_prefix("TXN Coffee 4.50")
        self.assertEqual(tc.name, "txn")
        self.assertEqual(title, "Coffee 4.50")
        self.assertIsNone(kw)  # not rendered — no default_keyword

    def test_custom_type_keyword_case_insensitive(self) -> None:
        types = dict(BUILTIN_TYPES)
        types["txn"] = TypeConfig(name="txn", keywords=["TXN"])
        engine = TypeEngine(types)
        title, tc, kw = engine.resolve_subject_prefix("txn Coffee 4.50")
        self.assertEqual(tc.name, "txn")
        self.assertEqual(title, "Coffee 4.50")
        self.assertIsNone(kw)


class TestResolveType(unittest.TestCase):
    """Body-header type resolution via resolve_type."""

    def setUp(self) -> None:
        self.engine = TypeEngine(dict(BUILTIN_TYPES))

    def test_resolve_known_type(self) -> None:
        tc, kw = self.engine.resolve_type("task", None)
        self.assertEqual(tc.name, "task")
        self.assertEqual(kw, "TODO")

    def test_resolve_with_valid_keyword(self) -> None:
        tc, kw = self.engine.resolve_type("task", "DONE")
        self.assertEqual(kw, "DONE")

    def test_resolve_with_invalid_keyword(self) -> None:
        tc, kw = self.engine.resolve_type("task", "INVALID")
        self.assertEqual(kw, "TODO")

    def test_resolve_unknown_type(self) -> None:
        tc, kw = self.engine.resolve_type("nonexistent", None)
        self.assertEqual(tc.name, "note")

    def test_resolve_none_type(self) -> None:
        tc, kw = self.engine.resolve_type(None, None)
        self.assertEqual(tc.name, "note")

    def test_resolve_type_case_insensitive(self) -> None:
        tc, kw = self.engine.resolve_type("TASK", None)
        self.assertEqual(tc.name, "task")

    def test_resolve_keyword_case_insensitive(self) -> None:
        tc, kw = self.engine.resolve_type("task", "done")
        self.assertEqual(kw, "DONE")


class TestTargetResolution(unittest.TestCase):
    """Target resolution via get_target."""

    def setUp(self) -> None:
        self.engine = TypeEngine(dict(BUILTIN_TYPES))
        self.config = Config(
            maildir_path=Path("/tmp/mail"),
            default_file=Path("/tmp/default.org"),
        )

    def test_explicit_target_wins(self) -> None:
        tc = BUILTIN_TYPES["task"]
        explicit = Path("/tmp/explicit.org")
        result = self.engine.get_target(tc, self.config, explicit)
        self.assertEqual(result, explicit)

    def test_type_file_used(self) -> None:
        tc = TypeConfig(name="journal", file=Path("/tmp/journal.org"))
        result = self.engine.get_target(tc, self.config, None)
        self.assertEqual(result, Path("/tmp/journal.org"))

    def test_default_target_fallback(self) -> None:
        tc = TypeConfig(name="bare")
        result = self.engine.get_target(tc, self.config, None)
        self.assertEqual(result, Path("/tmp/default.org"))

    def test_no_target_raises(self) -> None:
        config_no_default = Config(maildir_path=Path("/tmp/mail"))
        tc = TypeConfig(name="bare")
        with self.assertRaises(ValueError):
            self.engine.get_target(tc, config_no_default, None)


class TestParentResolution(unittest.TestCase):
    """Parent resolution via get_parent."""

    def setUp(self) -> None:
        self.engine = TypeEngine(dict(BUILTIN_TYPES))
        self.config = Config(maildir_path=Path("/tmp/mail"))

    def test_explicit_parent_wins(self) -> None:
        tc = TypeConfig(name="task", parent="Type Parent")
        result = self.engine.get_parent(tc, self.config, "Explicit Parent")
        self.assertEqual(result, "Explicit Parent")

    def test_type_parent_fallback(self) -> None:
        tc = TypeConfig(name="task", parent="Type Parent")
        result = self.engine.get_parent(tc, self.config, None)
        self.assertEqual(result, "Type Parent")

    def test_no_parent_returns_none(self) -> None:
        tc = TypeConfig(name="task")
        result = self.engine.get_parent(tc, self.config, None)
        self.assertIsNone(result)


class TestNoteTypeAlwaysPresent(unittest.TestCase):
    """TypeEngine always provides a note type, even with empty input."""

    def test_note_type_always_present(self) -> None:
        engine = TypeEngine({})
        self.assertEqual(engine.note_type.name, "note")


if __name__ == "__main__":
    unittest.main()
