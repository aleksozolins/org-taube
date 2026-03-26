"""org-taube: Email-first capture pipeline for Org mode."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Attachment:
    """An email attachment."""

    filename: str
    content: bytes


@dataclass
class CaptureEntry:
    """Parsed email data ready for rendering."""

    title: str
    body: str
    type_name: str  # type name (e.g., "task", "note", "workout")
    keyword: str | None  # org heading keyword (e.g., "TODO", "NEXT", None)
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    from_addr: str = ""
    message_id: str = ""
    created: datetime | None = None
    scheduled: datetime | None = None
    deadline: datetime | None = None
    target: Path | None = None  # explicit target file override
    parent: str | None = None  # explicit parent heading override
    extra_properties: dict[str, str] = field(default_factory=dict)  # custom type properties
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class TypeConfig:
    """Configuration for a capture type (e.g., task, note, workout)."""

    name: str
    keywords: list[str] = field(default_factory=list)
    default_keyword: str | None = None
    tags: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    attachment_path: Path | None = None
    file: Path | None = None
    parent: str | None = None


@dataclass
class Config:
    """Full application config."""

    maildir_path: Path
    default_file: Path | None = None
    default_attachment_path: Path | None = None
    types: dict[str, TypeConfig] = field(default_factory=dict)
    trusted_senders: list[str] = field(default_factory=list)
    trust_all: bool = False
    post_process: str = "read"  # "read" or "delete"
    signature_separator: str = "-- "
