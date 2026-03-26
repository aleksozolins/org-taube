"""Tests for org_taube.writer."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from org_taube import Attachment
from org_taube.writer import (
    _find_insertion_point,
    _heading_depth,
    save_attachments,
    write_entry,
)


class TestHeadingDepth(unittest.TestCase):
    """Tests for _heading_depth."""

    def test_depth_one(self):
        self.assertEqual(_heading_depth("* Heading"), 1)

    def test_depth_two(self):
        self.assertEqual(_heading_depth("** Heading"), 2)

    def test_depth_three(self):
        self.assertEqual(_heading_depth("*** Heading"), 3)

    def test_not_a_heading(self):
        self.assertIsNone(_heading_depth("Just text"))

    def test_no_space_after_stars(self):
        self.assertIsNone(_heading_depth("**Heading"))


class TestFindInsertionPoint(unittest.TestCase):
    """Tests for _find_insertion_point."""

    def test_find_parent_end_of_file(self):
        lines = ["* Tasks", "** Existing"]
        idx, depth = _find_insertion_point(lines, "Tasks")
        self.assertEqual(idx, len(lines))
        self.assertEqual(depth, 1)

    def test_find_parent_before_sibling(self):
        lines = ["* Tasks", "** Existing", "* Notes"]
        idx, depth = _find_insertion_point(lines, "Tasks")
        self.assertEqual(idx, 2)

    def test_parent_not_found_returns_none(self):
        lines = ["* Tasks", "** Existing"]
        self.assertIsNone(_find_insertion_point(lines, "Missing"))

    def test_parent_match_ignores_stars(self):
        lines = ["* Tasks", "** Existing"]
        idx, depth = _find_insertion_point(lines, "* Tasks")
        self.assertEqual(idx, len(lines))
        self.assertEqual(depth, 1)

    def test_deeper_children_skipped(self):
        lines = ["* Tasks", "** Sub", "*** Deep", "* Notes"]
        idx, depth = _find_insertion_point(lines, "Tasks")
        self.assertEqual(idx, 3)


class TestWriteEntryAppend(unittest.TestCase):
    """Tests for write_entry without a parent heading (append mode)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_append_to_empty_file(self):
        filepath = Path(self.tmpdir) / "empty.org"
        filepath.write_text("")
        write_entry("* TODO Task\n", filepath)
        self.assertEqual(filepath.read_text(), "* TODO Task\n")

    def test_append_to_existing(self):
        filepath = Path(self.tmpdir) / "existing.org"
        filepath.write_text("* First\n")
        write_entry("* Second\n", filepath)
        content = filepath.read_text()
        self.assertIn("\n\n* Second\n", content)

    def test_creates_parent_dirs(self):
        filepath = Path(self.tmpdir) / "a" / "b" / "c" / "test.org"
        write_entry("* Entry\n", filepath)
        self.assertTrue(filepath.exists())
        self.assertIn("* Entry", filepath.read_text())

    def test_creates_file_if_missing(self):
        filepath = Path(self.tmpdir) / "new.org"
        self.assertFalse(filepath.exists())
        write_entry("* Entry\n", filepath)
        self.assertTrue(filepath.exists())


class TestWriteEntryParent(unittest.TestCase):
    """Tests for write_entry with a parent heading (insertion mode)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_insert_under_parent(self):
        filepath = Path(self.tmpdir) / "test.org"
        filepath.write_text("* Inbox\n")
        write_entry("* TODO Something\n", filepath, parent="Inbox")
        content = filepath.read_text()
        self.assertIn("** TODO Something", content)

    def test_insert_adjusts_heading_depth(self):
        filepath = Path(self.tmpdir) / "test.org"
        filepath.write_text("* Inbox\n")
        write_entry("* TODO Something\n", filepath, parent="Inbox")
        content = filepath.read_text()
        # The rendered "* TODO Something" should become "** TODO Something"
        self.assertIn("** TODO Something", content)
        # Should NOT contain a depth-1 heading for TODO Something
        self.assertNotIn("\n* TODO Something", content)

    def test_insert_before_sibling(self):
        filepath = Path(self.tmpdir) / "test.org"
        filepath.write_text("* Inbox\n* Archive\n")
        write_entry("* TODO Task\n", filepath, parent="Inbox")
        content = filepath.read_text()
        # Entry should appear between Inbox and Archive
        inbox_pos = content.index("* Inbox")
        task_pos = content.index("** TODO Task")
        archive_pos = content.index("* Archive")
        self.assertLess(inbox_pos, task_pos)
        self.assertLess(task_pos, archive_pos)

    def test_auto_creates_missing_parent(self):
        filepath = Path(self.tmpdir) / "test.org"
        filepath.write_text("")
        write_entry("* TODO Task\n", filepath, parent="Tasks")
        content = filepath.read_text()
        self.assertIn("* Tasks", content)
        self.assertIn("** TODO Task", content)

    def test_auto_creates_parent_in_new_file(self):
        filepath = Path(self.tmpdir) / "new.org"
        write_entry("* Note\n", filepath, parent="Inbox")
        content = filepath.read_text()
        self.assertIn("* Inbox", content)
        self.assertIn("** Note", content)


class TestSaveAttachments(unittest.TestCase):
    """Tests for save_attachments."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_saves_with_prefix(self):
        save_dir = Path(self.tmpdir) / "attachments"
        attachments = [Attachment(filename="report.pdf", content=b"data")]
        save_attachments(attachments, save_dir, "20260327")
        expected = save_dir / "20260327-report.pdf"
        self.assertTrue(expected.exists())
        self.assertEqual(expected.read_bytes(), b"data")

    def test_creates_save_directory(self):
        save_dir = Path(self.tmpdir) / "new" / "dir"
        self.assertFalse(save_dir.exists())
        attachments = [Attachment(filename="file.txt", content=b"hello")]
        save_attachments(attachments, save_dir, "20260327")
        self.assertTrue(save_dir.exists())

    def test_returns_correct_paths(self):
        save_dir = Path(self.tmpdir) / "attachments"
        attachments = [
            Attachment(filename="a.txt", content=b"aaa"),
            Attachment(filename="b.txt", content=b"bbb"),
        ]
        paths = save_attachments(attachments, save_dir, "20260327")
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], save_dir / "20260327-a.txt")
        self.assertEqual(paths[1], save_dir / "20260327-b.txt")


if __name__ == "__main__":
    unittest.main()
