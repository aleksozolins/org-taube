"""Org entry rendering for org-taube."""

from datetime import datetime

from org_taube import Attachment, CaptureEntry, TypeConfig


def _format_timestamp(dt: datetime) -> str:
    """Format a datetime as an Org inactive timestamp.

    Example: ``[2026-03-23 Mon 10:15]``
    """
    return dt.strftime("[%Y-%m-%d %a %H:%M]")


def _format_active_timestamp(dt: datetime) -> str:
    """Format a datetime as an Org active timestamp.

    Example: ``<2026-03-23 Mon>`` (date only) or ``<2026-03-23 Mon 10:15>``.
    Uses date-only when time is midnight.
    """
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.strftime("<%Y-%m-%d %a>")
    return dt.strftime("<%Y-%m-%d %a %H:%M>")


def _format_tags(tags: list[str]) -> str:
    """Format a tag list as an Org tag suffix.

    Returns an empty string when there are no tags, otherwise
    ``:tag1:tag2:``.
    """
    if not tags:
        return ""
    return ":" + ":".join(tags) + ":"


def _build_heading(keyword: str | None, title: str, tags: list[str],
                   depth: int) -> str:
    """Build a complete Org heading line.

    Parameters
    ----------
    keyword:
        An Org TODO keyword such as ``"TODO"`` or *None* for plain headings.
    title:
        The heading text.
    tags:
        Merged, deduplicated tag list.
    depth:
        Heading depth (number of leading ``*``).
    """
    stars = "*" * depth
    tag_suffix = _format_tags(tags)

    parts: list[str] = [stars]
    if keyword:
        parts.append(keyword)
    parts.append(title)

    heading = " ".join(parts)

    if tag_suffix:
        heading = f"{heading}  {tag_suffix}"

    return heading


def _build_properties(entry: CaptureEntry, type_config: TypeConfig) -> str:
    """Build an Org properties drawer.

    Always includes CREATED, FROM, and MESSAGE_ID.  Includes SOURCE when
    present.  Appends any custom property names listed in the type config.
    """
    props: list[tuple[str, str]] = []

    created_str = (
        _format_timestamp(entry.created) if entry.created
        else _format_timestamp(datetime.now())
    )
    props.append(("CREATED", created_str))
    props.append(("FROM", entry.from_addr))
    props.append(("MESSAGE_ID", entry.message_id))

    if entry.source:
        props.append(("SOURCE", entry.source))

    # Custom properties defined by the type, populated by the parser.
    for name in type_config.properties:
        value = entry.extra_properties.get(name.lower())
        if value:
            props.append((name.upper(), value))

    # Determine alignment width from the longest key.
    max_key = max(len(k) for k, _ in props) if props else 0

    lines = [":PROPERTIES:"]
    for key, value in props:
        lines.append(f":{key}:{' ' * (max_key - len(key) + 4)}{value}")
    lines.append(":END:")

    return "\n".join(lines)


def _format_attachments(attachments: list[Attachment],
                        saved_paths: list[str] | None = None) -> str:
    """Render attachment file links.

    When *saved_paths* is provided, each link uses the corresponding saved
    path.  Otherwise the original filename is used as-is (useful when paths
    are not yet known at render time — the caller can substitute later).
    """
    lines: list[str] = []
    for i, att in enumerate(attachments):
        if saved_paths and i < len(saved_paths):
            path = saved_paths[i]
        else:
            path = att.filename
        lines.append(f"[[file:{path}][{att.filename}]]")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def render_entry(entry: CaptureEntry, type_config: TypeConfig, depth: int = 1,
                 saved_attachment_paths: list[str] | None = None) -> str:
    """Render a CaptureEntry into a complete Org entry string.

    Parameters
    ----------
    entry:
        The parsed capture data.
    type_config:
        The type configuration controlling tags and extra properties.
    depth:
        Heading level (``1`` for ``*``, ``2`` for ``**``, etc.).
    saved_attachment_paths:
        Optional list of filesystem paths for saved attachments.  When
        supplied, attachment links use these paths instead of the raw
        filenames.

    Returns
    -------
    str
        A fully formatted Org entry ready to be written to a file.
    """
    # Merge and deduplicate tags, preserving order.
    seen: set[str] = set()
    merged_tags: list[str] = []
    for tag in entry.tags + type_config.tags:
        if tag not in seen:
            seen.add(tag)
            merged_tags.append(tag)

    heading = _build_heading(entry.keyword, entry.title, merged_tags, depth)
    properties = _build_properties(entry, type_config)

    sections: list[str] = [heading]

    # Planning line (SCHEDULED / DEADLINE) goes between heading and properties.
    planning_parts: list[str] = []
    if entry.scheduled:
        planning_parts.append(
            f"SCHEDULED: {_format_active_timestamp(entry.scheduled)}"
        )
    if entry.deadline:
        planning_parts.append(
            f"DEADLINE: {_format_active_timestamp(entry.deadline)}"
        )
    if planning_parts:
        sections.append(" ".join(planning_parts))

    sections.append(properties)

    if entry.body.strip():
        sections.append("")  # blank line after :END:
        sections.append(entry.body.rstrip())

    if entry.attachments:
        sections.append(
            _format_attachments(entry.attachments, saved_attachment_paths)
        )

    return "\n".join(sections) + "\n"
