"""Email parsing module for org-taube.

Scans a Maildir for unread messages, parses email headers and body into
CaptureEntry objects, checks sender trust, and marks messages as processed.
"""

from __future__ import annotations

import email.utils
import fnmatch
import html
import mailbox
import re
from datetime import datetime, timezone
from pathlib import Path

from . import Attachment, CaptureEntry, Config

# Body-header keys recognised during metadata parsing (case-insensitive).
_BODY_HEADER_KEYS: set[str] = {
    "type",
    "keyword",
    "tags",
    "source",
    "created",
    "scheduled",
    "deadline",
    "title",
    "target",
    "parent",
}

# ---------------------------------------------------------------------------
# Maildir scanning
# ---------------------------------------------------------------------------


def scan_unread(maildir_path: Path) -> list[mailbox.MaildirMessage]:
    """Return every unread message in *maildir_path*.

    Messages in the ``new/`` subdirectory are always unread.  Messages in
    ``cur/`` are unread only when the 'S' (seen) flag is absent from the
    Maildir info string.
    """
    md = mailbox.Maildir(str(maildir_path), create=False)
    unread: list[mailbox.MaildirMessage] = []
    for _key, msg in md.iteritems():
        flags = msg.get_flags()
        if "S" not in flags:
            unread.append(msg)
    return unread


# ---------------------------------------------------------------------------
# Email parsing
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Crudely convert HTML to plain text using only stdlib."""
    # Remove script/style blocks entirely.
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    # Replace <br> / <p> / <div> with newlines before stripping tags.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|tr|li)>", "\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return text


def _extract_text(msg: mailbox.MaildirMessage) -> str:
    """Extract the best plain-text body from *msg*.

    Prefers ``text/plain``; falls back to stripped ``text/html``.
    """
    if not msg.is_multipart():
        ct = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        charset = msg.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if ct == "text/html":
            return _strip_html(text)
        return text

    plain_part: str | None = None
    html_part: str | None = None

    for part in msg.walk():
        ct = part.get_content_type()
        disp = str(part.get("Content-Disposition", ""))
        if "attachment" in disp:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")
        if ct == "text/plain" and plain_part is None:
            plain_part = decoded
        elif ct == "text/html" and html_part is None:
            html_part = decoded

    if plain_part is not None:
        return plain_part
    if html_part is not None:
        return _strip_html(html_part)
    return ""


def _extract_attachments(msg: mailbox.MaildirMessage) -> list[Attachment]:
    """Return a list of :class:`Attachment` for every attachment MIME part."""
    attachments: list[Attachment] = []
    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        disp = str(part.get("Content-Disposition", ""))
        if "attachment" not in disp:
            continue
        filename = part.get_filename() or "untitled"
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        attachments.append(Attachment(filename=filename, content=payload))

    return attachments


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse an RFC-2822 Date header into a :class:`datetime`."""
    if not date_str:
        return None
    parsed = email.utils.parsedate_to_datetime(date_str)
    return parsed


def _parse_body_headers(
    body: str, config: Config
) -> tuple[dict[str, str], str]:
    """Split *body* into metadata key/value pairs and the remaining freeform text.

    Lines at the top of the body that match ``KEY: value`` (case-insensitive
    key) are consumed as metadata.  Parsing stops at the first blank line or
    the first line that does not match the pattern.

    Returns ``(headers_dict, remaining_body)``.
    """
    # Build the set of allowed keys (standard + custom type properties).
    allowed_keys: set[str] = set(_BODY_HEADER_KEYS)
    for tc in config.types.values():
        for prop in tc.properties:
            allowed_keys.add(prop.lower())

    header_re = re.compile(r"^([A-Za-z_-]+):\s*(.*)")
    headers: dict[str, str] = {}
    lines = body.split("\n")
    idx = 0
    for idx, line in enumerate(lines):
        if line.strip() == "":
            # Blank line terminates the header block.
            idx += 1  # skip the blank line itself
            break
        m = header_re.match(line)
        if m and m.group(1).lower() in allowed_keys:
            value = m.group(2).strip()
            if value:
                headers[m.group(1).lower()] = value
        else:
            # Non-matching line means no (more) headers.
            break
    else:
        # We consumed every line without hitting a break.
        idx = len(lines)

    remaining = "\n".join(lines[idx:])
    return headers, remaining


def parse_email(msg: mailbox.MaildirMessage, config: Config) -> CaptureEntry:
    """Parse *msg* into a :class:`CaptureEntry`."""
    _name, from_addr = email.utils.parseaddr(msg.get("From", ""))
    subject = msg.get("Subject", "")
    date = _parse_date(msg.get("Date"))
    message_id = msg.get("Message-ID", "")

    raw_body = _extract_text(msg)

    # Strip signature.
    sep = config.signature_separator
    if sep in raw_body:
        raw_body = raw_body.split(sep, 1)[0]

    # Parse body headers.
    headers, freeform = _parse_body_headers(raw_body, config)

    # Map body-header values into CaptureEntry fields.
    type_name = headers.get("type", "")
    keyword = headers.get("keyword")
    title = headers.get("title", subject)
    source = headers.get("source")
    parent = headers.get("parent")

    target: Path | None = None
    if "target" in headers:
        target = Path(headers["target"])

    tags: list[str] = []
    if "tags" in headers:
        tags = [t.strip() for t in headers["tags"].split(",") if t.strip()]

    created: datetime | None = date
    if "created" in headers:
        try:
            created = datetime.fromisoformat(headers["created"])
        except ValueError:
            pass  # keep the email Date if parsing fails

    scheduled: datetime | None = None
    if "scheduled" in headers:
        try:
            scheduled = datetime.fromisoformat(headers["scheduled"])
        except ValueError:
            pass

    deadline: datetime | None = None
    if "deadline" in headers:
        try:
            deadline = datetime.fromisoformat(headers["deadline"])
        except ValueError:
            pass

    # Collect custom type properties (anything not a standard key).
    extra_properties: dict[str, str] = {}
    for key, value in headers.items():
        if key not in _BODY_HEADER_KEYS:
            extra_properties[key] = value

    attachments = _extract_attachments(msg)

    return CaptureEntry(
        title=title,
        body=freeform.strip(),
        type_name=type_name,
        keyword=keyword,
        tags=tags,
        source=source,
        from_addr=from_addr,
        message_id=message_id,
        created=created,
        scheduled=scheduled,
        deadline=deadline,
        target=target,
        parent=parent,
        extra_properties=extra_properties,
        attachments=attachments,
    )


# ---------------------------------------------------------------------------
# Sender trust checking
# ---------------------------------------------------------------------------


def is_trusted(from_addr: str, config: Config) -> bool:
    """Return ``True`` if *from_addr* is trusted according to *config*.

    *from_addr* may be a bare address (``user@example.com``) or a display-name
    form (``"Alice" <alice@example.com>``).  The check is performed against the
    bare address.

    Supports exact matches and wildcard domain patterns such as
    ``*@example.com`` via :func:`fnmatch.fnmatch`.
    """
    if config.trust_all:
        return True

    # Extract the bare email address.
    _name, addr = email.utils.parseaddr(from_addr)
    addr = addr.lower()

    for pattern in config.trusted_senders:
        if fnmatch.fnmatch(addr, pattern.lower()):
            return True

    return False


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def mark_processed(
    msg: mailbox.MaildirMessage, maildir_path: Path, action: str
) -> None:
    """Mark *msg* as processed in the Maildir at *maildir_path*.

    *action* is one of:

    ``"read"``
        Add the 'S' (seen) flag to the message.
    ``"delete"``
        Remove the message from the Maildir entirely.
    """
    md = mailbox.Maildir(str(maildir_path), create=False)

    if action == "read":
        # Find the message key and update its flags.
        for key, m in md.iteritems():
            if m.get("Message-ID") == msg.get("Message-ID"):
                msg.add_flag("S")
                md[key] = msg
                break
        md.flush()

    elif action == "delete":
        for key, m in md.iteritems():
            if m.get("Message-ID") == msg.get("Message-ID"):
                md.remove(key)
                break
        md.flush()

    else:
        raise ValueError(f"Unknown post-process action: {action!r}")
