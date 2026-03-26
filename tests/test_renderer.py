"""Tests for org_taube.renderer."""

import unittest
from datetime import datetime

from org_taube import Attachment, CaptureEntry, TypeConfig
from org_taube.renderer import (
    _build_heading,
    _build_properties,
    _format_active_timestamp,
    _format_attachments,
    _format_tags,
    _format_timestamp,
    render_entry,
)


class TestFormatTimestamp(unittest.TestCase):
    def test_timestamp_format(self):
        dt = datetime(2026, 3, 23, 10, 15)
        self.assertEqual(_format_timestamp(dt), "[2026-03-23 Mon 10:15]")


class TestFormatTags(unittest.TestCase):
    def test_no_tags(self):
        self.assertEqual(_format_tags([]), "")

    def test_single_tag(self):
        self.assertEqual(_format_tags(["work"]), ":work:")

    def test_multiple_tags(self):
        self.assertEqual(_format_tags(["work", "urgent"]), ":work:urgent:")


class TestBuildHeading(unittest.TestCase):
    def test_plain_heading(self):
        result = _build_heading(keyword=None, title="My Note", tags=[], depth=1)
        self.assertEqual(result, "* My Note")

    def test_todo_heading(self):
        result = _build_heading(keyword="TODO", title="Buy milk", tags=[], depth=1)
        self.assertEqual(result, "* TODO Buy milk")

    def test_heading_with_tags(self):
        result = _build_heading(keyword="TODO", title="Fix bug", tags=["work"], depth=1)
        self.assertEqual(result, "* TODO Fix bug  :work:")

    def test_heading_depth_2(self):
        result = _build_heading(keyword=None, title="Sub heading", tags=[], depth=2)
        self.assertEqual(result, "** Sub heading")

    def test_heading_depth_3(self):
        result = _build_heading(keyword=None, title="Deep heading", tags=[], depth=3)
        self.assertEqual(result, "*** Deep heading")


class TestBuildProperties(unittest.TestCase):
    def test_standard_properties(self):
        entry = CaptureEntry(
            title="Test",
            body="",
            type_name="note",
            keyword=None,
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
        )
        tc = TypeConfig(name="note")
        result = _build_properties(entry, tc)
        self.assertIn(":PROPERTIES:", result)
        self.assertIn(":CREATED:", result)
        self.assertIn(":FROM:", result)
        self.assertIn(":MESSAGE_ID:", result)
        self.assertIn(":END:", result)

    def test_source_included(self):
        entry = CaptureEntry(
            title="Test",
            body="",
            type_name="note",
            keyword=None,
            source="https://example.com",
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
        )
        tc = TypeConfig(name="note")
        result = _build_properties(entry, tc)
        self.assertIn(":SOURCE:", result)

    def test_custom_properties(self):
        entry = CaptureEntry(
            title="Test",
            body="",
            type_name="workout",
            keyword=None,
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
            extra_properties={"duration": "30min"},
        )
        tc = TypeConfig(name="workout", properties=["DURATION"])
        result = _build_properties(entry, tc)
        self.assertIn(":DURATION:", result)
        self.assertIn("30min", result)


class TestRenderEntry(unittest.TestCase):
    def test_full_note_entry(self):
        entry = CaptureEntry(
            title="My Note",
            body="Some body text.",
            type_name="note",
            keyword=None,
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
        )
        tc = TypeConfig(name="note")
        result = render_entry(entry, tc)
        self.assertTrue(result.startswith("* My Note\n"))
        self.assertIn(":PROPERTIES:", result)
        self.assertIn(":END:", result)
        # Blank line between :END: and body
        self.assertIn(":END:\n\nSome body text.", result)

    def test_full_task_entry(self):
        entry = CaptureEntry(
            title="Buy milk",
            body="",
            type_name="task",
            keyword="TODO",
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
        )
        tc = TypeConfig(name="task")
        result = render_entry(entry, tc)
        self.assertTrue(result.startswith("* TODO Buy milk\n"))

    def test_tag_merge_dedup(self):
        entry = CaptureEntry(
            title="Test",
            body="",
            type_name="note",
            keyword=None,
            tags=["a", "b"],
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
        )
        tc = TypeConfig(name="note", tags=["b", "c"])
        result = render_entry(entry, tc)
        self.assertIn(":a:b:c:", result)

    def test_no_body(self):
        entry = CaptureEntry(
            title="Empty",
            body="",
            type_name="note",
            keyword=None,
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
        )
        tc = TypeConfig(name="note")
        result = render_entry(entry, tc)
        # No blank line after :END: when body is empty
        self.assertIn(":END:\n", result)
        self.assertNotIn(":END:\n\n", result)

    def test_with_attachments(self):
        entry = CaptureEntry(
            title="With files",
            body="",
            type_name="note",
            keyword=None,
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
            attachments=[
                Attachment(filename="doc.pdf", content=b"fake"),
                Attachment(filename="img.png", content=b"fake"),
            ],
        )
        tc = TypeConfig(name="note")
        saved = ["/tmp/doc.pdf", "/tmp/img.png"]
        result = render_entry(entry, tc, saved_attachment_paths=saved)
        self.assertIn("[[file:/tmp/doc.pdf][doc.pdf]]", result)
        self.assertIn("[[file:/tmp/img.png][img.png]]", result)

    def test_trailing_newline(self):
        entry = CaptureEntry(
            title="Trailing",
            body="Some text.",
            type_name="note",
            keyword=None,
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="user@example.com",
            message_id="abc123",
        )
        tc = TypeConfig(name="note")
        result = render_entry(entry, tc)
        self.assertTrue(result.endswith("\n"))
        self.assertFalse(result.endswith("\n\n"))


class TestActiveTimestamp(unittest.TestCase):
    def test_date_only(self):
        dt = datetime(2026, 3, 28)
        self.assertEqual(_format_active_timestamp(dt), "<2026-03-28 Sat>")

    def test_date_and_time(self):
        dt = datetime(2026, 3, 28, 14, 30)
        self.assertEqual(_format_active_timestamp(dt), "<2026-03-28 Sat 14:30>")


class TestPlanningLine(unittest.TestCase):
    def test_scheduled_only(self):
        entry = CaptureEntry(
            title="Do thing",
            body="",
            type_name="task",
            keyword="TODO",
            scheduled=datetime(2026, 3, 28),
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="u@e.com",
            message_id="x",
        )
        result = render_entry(entry, TypeConfig(name="task"))
        lines = result.splitlines()
        self.assertEqual(lines[1], "SCHEDULED: <2026-03-28 Sat>")
        self.assertEqual(lines[2], ":PROPERTIES:")

    def test_deadline_only(self):
        entry = CaptureEntry(
            title="Do thing",
            body="",
            type_name="task",
            keyword="TODO",
            deadline=datetime(2026, 4, 1),
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="u@e.com",
            message_id="x",
        )
        result = render_entry(entry, TypeConfig(name="task"))
        lines = result.splitlines()
        self.assertEqual(lines[1], "DEADLINE: <2026-04-01 Wed>")

    def test_both_scheduled_and_deadline(self):
        entry = CaptureEntry(
            title="Do thing",
            body="",
            type_name="task",
            keyword="TODO",
            scheduled=datetime(2026, 3, 28),
            deadline=datetime(2026, 4, 1),
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="u@e.com",
            message_id="x",
        )
        result = render_entry(entry, TypeConfig(name="task"))
        lines = result.splitlines()
        self.assertIn("SCHEDULED: <2026-03-28 Sat>", lines[1])
        self.assertIn("DEADLINE: <2026-04-01 Wed>", lines[1])
        self.assertEqual(lines[2], ":PROPERTIES:")

    def test_no_planning_line_when_absent(self):
        entry = CaptureEntry(
            title="Plain note",
            body="",
            type_name="note",
            keyword=None,
            created=datetime(2026, 3, 23, 10, 15),
            from_addr="u@e.com",
            message_id="x",
        )
        result = render_entry(entry, TypeConfig(name="note"))
        lines = result.splitlines()
        self.assertEqual(lines[0], "* Plain note")
        self.assertEqual(lines[1], ":PROPERTIES:")


if __name__ == "__main__":
    unittest.main()
