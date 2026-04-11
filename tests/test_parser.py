"""Tests for org_taube.parser — body-header parsing, HTML stripping,
sender trust, and full email parsing."""

import email
import mailbox
import shutil
import tempfile
import unittest
from pathlib import Path

from org_taube import Config, TypeConfig
from org_taube.parser import (
    _parse_body_headers,
    _strip_html,
    is_trusted,
    mark_processed,
    parse_email,
    scan_unread,
)


def _minimal_config(**overrides) -> Config:
    """Return a Config with only the required fields, plus *overrides*."""
    defaults = dict(
        maildir_path=Path("/tmp/fake-maildir"),
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_maildir_message(raw: str) -> mailbox.MaildirMessage:
    """Build a MaildirMessage from a raw RFC-2822 string."""
    msg = email.message_from_string(raw)
    return mailbox.MaildirMessage(msg)


# ── _parse_body_headers ────────────────────────────────────────────────


class TestParseBodyHeaders(unittest.TestCase):
    """Tests for _parse_body_headers."""

    def test_standard_headers_parsed(self):
        body = "TYPE: task\nKEYWORD: TODO\nTAGS: work, urgent\n\nBody text"
        config = _minimal_config()
        headers, remaining = _parse_body_headers(body, config)

        self.assertEqual(headers["type"], "task")
        self.assertEqual(headers["keyword"], "TODO")
        self.assertEqual(headers["tags"], "work, urgent")
        self.assertEqual(remaining, "Body text")

    def test_blank_line_terminates(self):
        body = "TYPE: task\n\nKEYWORD: TODO"
        config = _minimal_config()
        headers, remaining = _parse_body_headers(body, config)

        self.assertIn("type", headers)
        self.assertNotIn("keyword", headers)
        self.assertIn("KEYWORD: TODO", remaining)

    def test_non_header_line_terminates(self):
        body = "TYPE: task\nThis is text\nKEYWORD: TODO"
        config = _minimal_config()
        headers, remaining = _parse_body_headers(body, config)

        self.assertIn("type", headers)
        self.assertNotIn("keyword", headers)
        self.assertIn("This is text", remaining)

    def test_case_insensitive_keys(self):
        body = "Type: task\nKeyword: DONE"
        config = _minimal_config()
        headers, remaining = _parse_body_headers(body, config)

        self.assertEqual(headers["type"], "task")
        self.assertEqual(headers["keyword"], "DONE")
        # Keys must be stored lowercase.
        for key in headers:
            self.assertEqual(key, key.lower())

    def test_unknown_key_stops_parsing(self):
        body = "TYPE: task\nFOOBAR: baz\nTITLE: hello"
        config = _minimal_config()
        headers, remaining = _parse_body_headers(body, config)

        self.assertIn("type", headers)
        self.assertNotIn("foobar", headers)
        self.assertNotIn("title", headers)

    def test_custom_property_allowed(self):
        config = _minimal_config(
            types={
                "workout": TypeConfig(
                    name="workout",
                    properties=["DURATION"],
                ),
            },
        )
        body = "TYPE: workout\nDURATION: 30min\n\nRan"
        headers, remaining = _parse_body_headers(body, config)

        self.assertEqual(headers["type"], "workout")
        self.assertEqual(headers["duration"], "30min")
        self.assertEqual(remaining, "Ran")

    def test_empty_body(self):
        config = _minimal_config()
        headers, remaining = _parse_body_headers("", config)

        self.assertEqual(headers, {})
        self.assertEqual(remaining, "")

    def test_empty_value_skipped(self):
        body = "TYPE: task\nSCHEDULED:\nTITLE:\n\nBody text"
        config = _minimal_config()
        headers, remaining = _parse_body_headers(body, config)

        self.assertEqual(headers["type"], "task")
        self.assertNotIn("scheduled", headers)
        self.assertNotIn("title", headers)
        self.assertEqual(remaining, "Body text")

    def test_all_headers_no_body(self):
        body = "TYPE: note\nTITLE: test"
        config = _minimal_config()
        headers, remaining = _parse_body_headers(body, config)

        self.assertEqual(headers["type"], "note")
        self.assertEqual(headers["title"], "test")
        self.assertEqual(remaining, "")


# ── _strip_html ────────────────────────────────────────────────────────


class TestStripHtml(unittest.TestCase):
    """Tests for _strip_html."""

    def test_basic_html(self):
        result = _strip_html("<p>Hello</p><p>World</p>")
        self.assertNotIn("<p>", result)
        self.assertNotIn("</p>", result)
        self.assertIn("Hello", result)
        self.assertIn("World", result)

    def test_script_removal(self):
        result = _strip_html("<script>alert(1)</script>text")
        self.assertNotIn("alert", result)
        self.assertIn("text", result)

    def test_br_to_newline(self):
        result = _strip_html("line1<br>line2")
        self.assertIn("line1\nline2", result)

    def test_entity_unescape(self):
        result = _strip_html("&amp; &lt;")
        self.assertIn("& <", result)


# ── is_trusted ─────────────────────────────────────────────────────────


class TestIsTrusted(unittest.TestCase):
    """Tests for is_trusted."""

    def test_trust_all(self):
        config = _minimal_config(trust_all=True)
        self.assertTrue(is_trusted("stranger@unknown.org", config))

    def test_exact_match(self):
        config = _minimal_config(trusted_senders=["me@example.com"])
        self.assertTrue(is_trusted("me@example.com", config))

    def test_wildcard_domain(self):
        config = _minimal_config(trusted_senders=["*@example.com"])
        self.assertTrue(is_trusted("anyone@example.com", config))

    def test_case_insensitive_trust(self):
        config = _minimal_config(trusted_senders=["Me@Example.COM"])
        self.assertTrue(is_trusted("me@example.com", config))

    def test_untrusted(self):
        config = _minimal_config(trusted_senders=["me@example.com"])
        self.assertFalse(is_trusted("stranger@evil.org", config))

    def test_display_name_form(self):
        config = _minimal_config(trusted_senders=["alice@example.com"])
        self.assertTrue(is_trusted('"Alice" <alice@example.com>', config))


# ── parse_email ────────────────────────────────────────────────────────


class TestParseEmail(unittest.TestCase):
    """Tests for parse_email."""

    def test_parse_plain_email(self):
        raw = (
            "Subject: Test Subject\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Message-ID: <abc@example.com>\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "Hello, world!\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)

        self.assertEqual(entry.title, "Test Subject")
        self.assertEqual(entry.from_addr, "sender@example.com")
        self.assertEqual(entry.message_id, "<abc@example.com>")
        self.assertIn("Hello, world!", entry.body)

    def test_parse_with_body_headers(self):
        raw = (
            "Subject: Ignored\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "TYPE: task\r\n"
            "TAGS: work, urgent\r\n"
            "\r\n"
            "Do the thing\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)

        self.assertEqual(entry.type_name, "task")
        self.assertEqual(entry.tags, ["work", "urgent"])
        self.assertIn("Do the thing", entry.body)

    def test_signature_stripping(self):
        raw = (
            "Subject: Sig test\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "Main body\r\n"
            "-- \r\n"
            "My Signature\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)

        self.assertIn("Main body", entry.body)
        self.assertNotIn("My Signature", entry.body)

    def test_title_override(self):
        raw = (
            "Subject: Original Subject\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "TITLE: Overridden Title\r\n"
            "\r\n"
            "Body here\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)

        self.assertEqual(entry.title, "Overridden Title")

    def test_scheduled_and_deadline(self):
        raw = (
            "Subject: Task with dates\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "SCHEDULED: 2026-03-28\r\n"
            "DEADLINE: 2026-04-01\r\n"
            "\r\n"
            "Do it\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)

        self.assertIsNotNone(entry.scheduled)
        self.assertEqual(entry.scheduled.year, 2026)
        self.assertEqual(entry.scheduled.month, 3)
        self.assertEqual(entry.scheduled.day, 28)
        self.assertIsNotNone(entry.deadline)
        self.assertEqual(entry.deadline.month, 4)
        self.assertEqual(entry.deadline.day, 1)


class TestSubjectTags(unittest.TestCase):
    """Tags extracted from subject-line Org-style tag suffix."""

    def test_tags_extracted_from_subject(self):
        raw = (
            "Subject: TODO Buy milk :errands:\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)
        self.assertIn("errands", entry.tags)
        self.assertNotIn(":errands:", entry.title)

    def test_multiple_tags_from_subject(self):
        raw = (
            "Subject: Walk the dog :errands:health:\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)
        self.assertEqual(entry.tags, ["errands", "health"])
        self.assertEqual(entry.title, "Walk the dog")

    def test_subject_tags_merge_with_body_tags(self):
        raw = (
            "Subject: Buy milk :errands:\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "TAGS: groceries\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)
        self.assertIn("errands", entry.tags)
        self.assertIn("groceries", entry.tags)

    def test_duplicate_tags_deduplicated(self):
        raw = (
            "Subject: Buy milk :errands:\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "TAGS: errands,groceries\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)
        self.assertEqual(entry.tags.count("errands"), 1)
        self.assertIn("groceries", entry.tags)

    def test_no_tags_in_subject(self):
        raw = (
            "Subject: Just a plain subject\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)
        self.assertEqual(entry.tags, [])
        self.assertEqual(entry.title, "Just a plain subject")


class TestSubjectFolding(unittest.TestCase):
    """Subject lines with RFC 2822 folding are unfolded."""

    def test_folded_subject_unfolded(self):
        raw = (
            "Subject: TODO Action on Slack thread about Discussing\r\n"
            " changes to Dev Esc tickets, boundary review\r\n"
            "From: sender@example.com\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = _make_maildir_message(raw)
        config = _minimal_config()
        entry = parse_email(msg, config)
        self.assertNotIn("\n", entry.title)
        self.assertIn("tickets", entry.title)


class TestMarkProcessed(unittest.TestCase):
    """Tests for mark_processed — flags and subdir."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.maildir_path = Path(self.tmpdir) / "testmail"
        self.md = mailbox.Maildir(str(self.maildir_path), create=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _add_message(self):
        raw = (
            "Subject: Test\r\n"
            "From: sender@example.com\r\n"
            "Message-ID: <test123@example.com>\r\n"
            "Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "body\r\n"
        )
        msg = mailbox.MaildirMessage(email.message_from_string(raw))
        self.md.add(msg)
        self.md.flush()
        return msg

    def test_mark_read_moves_to_cur(self):
        msg = self._add_message()
        mark_processed(msg, self.maildir_path, "read")
        cur_files = list((self.maildir_path / "cur").iterdir())
        new_files = list((self.maildir_path / "new").iterdir())
        self.assertEqual(len(new_files), 0)
        self.assertEqual(len(cur_files), 1)

    def test_mark_read_adds_seen_flag(self):
        msg = self._add_message()
        mark_processed(msg, self.maildir_path, "read")
        cur_files = list((self.maildir_path / "cur").iterdir())
        self.assertTrue(cur_files[0].name.endswith("S"))

    def test_mark_delete_removes_message(self):
        msg = self._add_message()
        mark_processed(msg, self.maildir_path, "delete")
        cur_files = list((self.maildir_path / "cur").iterdir())
        new_files = list((self.maildir_path / "new").iterdir())
        self.assertEqual(len(cur_files) + len(new_files), 0)


class TestScanUnread(unittest.TestCase):
    """Tests for scan_unread."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.maildir_path = Path(self.tmpdir) / "testmail"
        self.md = mailbox.Maildir(str(self.maildir_path), create=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_new_messages_are_unread(self):
        raw = (
            "Subject: Test\r\nFrom: s@e.com\r\n"
            "Message-ID: <a@e.com>\r\n"
            "Content-Type: text/plain\r\n\r\nbody\r\n"
        )
        msg = mailbox.MaildirMessage(email.message_from_string(raw))
        self.md.add(msg)
        self.md.flush()
        self.assertEqual(len(scan_unread(self.maildir_path)), 1)

    def test_seen_messages_excluded(self):
        raw = (
            "Subject: Test\r\nFrom: s@e.com\r\n"
            "Message-ID: <a@e.com>\r\n"
            "Content-Type: text/plain\r\n\r\nbody\r\n"
        )
        msg = mailbox.MaildirMessage(email.message_from_string(raw))
        msg.add_flag("S")
        msg.set_subdir("cur")
        self.md.add(msg)
        self.md.flush()
        self.assertEqual(len(scan_unread(self.maildir_path)), 0)


if __name__ == "__main__":
    unittest.main()
