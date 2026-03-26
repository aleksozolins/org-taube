"""File writing for org-taube."""

import re
from pathlib import Path

from org_taube import Attachment


def save_attachments(attachments: list[Attachment], save_dir: Path,
                     prefix: str) -> list[Path]:
    """Save attachments to disk with a timestamp prefix.

    Parameters
    ----------
    attachments:
        The list of attachments to persist.
    save_dir:
        Directory where files are saved.  Created if it does not exist.
    prefix:
        A timestamp string (e.g. ``"20260324"``) prepended to each
        filename for collision avoidance.

    Returns
    -------
    list[Path]
        The saved file paths, one per attachment in the same order.
    """
    save_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    for att in attachments:
        dest = save_dir / f"{prefix}-{att.filename}"
        dest.write_bytes(att.content)
        saved.append(dest)

    return saved


# ------------------------------------------------------------------
# Heading parsing helpers
# ------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(\*+)\s")


def _heading_depth(line: str) -> int | None:
    """Return the depth of an Org heading line, or *None* if not a heading."""
    m = _HEADING_RE.match(line)
    return len(m.group(1)) if m else None


def _find_insertion_point(lines: list[str], parent: str) -> tuple[int, int] | None:
    """Locate where to insert a child entry under *parent*.

    Parameters
    ----------
    lines:
        The full file split into lines.
    parent:
        Exact text of the parent heading (e.g. ``"* Tasks"``).

    Returns
    -------
    tuple[int, int] | None
        ``(insert_index, parent_depth)`` — the line index at which the
        new entry should be inserted and the depth of the parent heading.
        Returns *None* when the parent heading is not found.
    """
    parent_idx: int | None = None
    parent_depth: int = 0

    for i, line in enumerate(lines):
        depth = _heading_depth(line)
        if depth is not None:
            # Match against the heading text (without leading stars and space).
            heading_text = line.lstrip("*").strip()
            parent_text = parent.lstrip("*").strip()
            if heading_text == parent_text:
                parent_idx = i
                parent_depth = depth
                break

    if parent_idx is None:
        return None

    # Walk forward from the line after the parent heading to find the
    # next sibling (same depth or shallower) or EOF.
    for i in range(parent_idx + 1, len(lines)):
        depth = _heading_depth(lines[i])
        if depth is not None and depth <= parent_depth:
            return i, parent_depth

    return len(lines), parent_depth


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def write_entry(rendered: str, file: Path,
                parent: str | None = None) -> None:
    """Append a rendered Org entry to the target file.

    Parameters
    ----------
    rendered:
        The fully rendered Org entry string (as produced by
        ``renderer.render_entry``).
    file:
        The Org file to write to.
    parent:
        Optional parent heading to insert under.
    """
    file.parent.mkdir(parents=True, exist_ok=True)

    if not file.exists():
        file.write_text("")

    if parent:
        _insert_under_parent(rendered, file, parent)
    else:
        _append_to_file(rendered, file)


def _append_to_file(rendered: str, file: Path) -> None:
    """Append *rendered* at the end of the target file."""
    existing = file.read_text()

    # Ensure a blank line separates the new entry from existing content.
    if existing and not existing.endswith("\n\n"):
        if existing.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
    else:
        separator = ""

    with open(file, "a") as fh:
        fh.write(separator + rendered)


def _insert_under_parent(rendered: str, file: Path, parent: str) -> None:
    """Insert *rendered* under the specified parent heading.

    If the parent heading does not exist in the file, it is created as a
    depth-1 heading at the end of the file before inserting the entry.
    """
    content = file.read_text()
    lines = content.splitlines(keepends=True)

    result = _find_insertion_point(
        [l.rstrip("\n") for l in lines],  # noqa: E741
        parent,
    )

    if result is None:
        # Parent heading not found — create it at the end of the file.
        parent_text = parent.lstrip("*").strip()
        heading_line = f"* {parent_text}\n"
        if content and not content.endswith("\n"):
            heading_line = "\n" + heading_line
        file.write_text(content + heading_line)
        # Re-read and find the insertion point now that the heading exists.
        content = file.read_text()
        lines = content.splitlines(keepends=True)
        result = _find_insertion_point(
            [l.rstrip("\n") for l in lines],  # noqa: E741
            parent,
        )
        assert result is not None

    insert_idx, parent_depth = result

    # Re-indent the entry heading to parent_depth + 1.
    child_depth = parent_depth + 1
    rendered_lines = rendered.splitlines(keepends=True)
    if rendered_lines:
        # Adjust only the first line (the heading) to the correct depth.
        first = rendered_lines[0]
        m = _HEADING_RE.match(first)
        if m:
            old_stars = m.group(1)
            new_stars = "*" * child_depth
            rendered_lines[0] = new_stars + first[len(old_stars):]

    # Ensure blank-line separation before and after the inserted block.
    block = "".join(rendered_lines)

    before = "".join(lines[:insert_idx])
    after = "".join(lines[insert_idx:])

    # Blank line before the inserted entry.
    if before and not before.endswith("\n\n"):
        if before.endswith("\n"):
            before += "\n"
        else:
            before += "\n\n"

    # Ensure the block itself ends with a newline.
    if block and not block.endswith("\n"):
        block += "\n"

    # Blank line after the inserted entry (before the next sibling).
    if after and not after.startswith("\n"):
        block += "\n"

    file.write_text(before + block + after)
