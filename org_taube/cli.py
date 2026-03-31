"""CLI entry point for org-taube."""

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from org_taube import Config
from org_taube.config import load_config
from org_taube.parser import is_trusted, mark_processed, parse_email, scan_unread
from org_taube.renderer import render_entry
from org_taube.types import TypeEngine
from org_taube.writer import save_attachments, write_entry


def _setup_logging(config: Config) -> logging.Logger:
    """Configure logging to the XDG data directory."""
    log_dir = Path("~/.local/state/org-taube").expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "org-taube.log"

    logger = logging.getLogger("org-taube")
    logger.setLevel(logging.DEBUG)

    handler = logging.FileHandler(log_file)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)

    return logger


# ── ANSI coloring for interactive preview ─────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"

# Keyword → color mapping (mirrors common Org faces).
_KW_COLORS = {
    "TODO": _RED,
    "NEXT": _YELLOW,
    "WAITING": _YELLOW,
    "DONE": _GREEN,
}


def _color_timestamps(line: str) -> str:
    """Color active and inactive Org timestamps (org-date face)."""
    # Active: <2026-03-28 Sat> or <2026-03-28 Sat 14:30>
    line = re.sub(
        r"(<\d{4}-\d{2}-\d{2}[^>]*>)",
        f"{_CYAN}\\1{_RESET}",
        line,
    )
    # Inactive: [2026-03-28 Sat 10:15]
    line = re.sub(
        r"(\[\d{4}-\d{2}-\d{2}[^\]]*\])",
        f"{_CYAN}\\1{_RESET}",
        line,
    )
    return line


def _colorize(rendered: str) -> str:
    """Apply ANSI colors to an Org entry for terminal preview."""
    out: list[str] = []
    in_drawer = False

    for line in rendered.splitlines():
        if line.startswith("*"):
            # Heading line: bold, with keyword colored.
            colored = _BOLD
            # Color the keyword if present.
            m = re.match(r"^(\*+ )(TODO|DONE|NEXT|WAITING)\b(.*)", line)
            if m:
                stars, kw, tail = m.groups()
                kw_color = _KW_COLORS.get(kw, "")
                colored += f"{stars}{kw_color}{kw}{_RESET}{_BOLD}{tail}"
            else:
                colored += line
            # Color tags at end of heading (e.g. :@out:inbox:).
            colored = re.sub(
                r"((?::[a-zA-Z0-9_@]+)+:)$",
                f"{_RESET}{_CYAN}\\1{_RESET}",
                colored,
            )
            out.append(colored + _RESET)
        elif line.startswith(":PROPERTIES:") or line.startswith(":END:"):
            out.append(f"{_DIM}{line}{_RESET}")
            in_drawer = line.startswith(":PROPERTIES:")
        elif in_drawer:
            # Property lines: key in cyan, value normal, timestamps cyan.
            colored = re.sub(
                r"^(:[A-Z_]+:)",
                f"{_CYAN}\\1{_RESET}",
                line,
            )
            colored = _color_timestamps(colored)
            out.append(colored)
            if line.startswith(":END:"):
                in_drawer = False
        elif line.startswith("SCHEDULED:") or line.startswith("DEADLINE:"):
            # Planning line — highlight keywords and timestamps.
            colored = re.sub(
                r"(SCHEDULED:|DEADLINE:)",
                f"{_MAGENTA}\\1{_RESET}",
                line,
            )
            colored = _color_timestamps(colored)
            out.append(colored)
        elif line.startswith("[[file:"):
            out.append(f"{_CYAN}{line}{_RESET}")
        else:
            out.append(_color_timestamps(line))

    return "\n".join(out)


def _resolve_entry(entry, engine, config):
    """Resolve type, keyword, title, target, and parent for an entry.

    Applies subject-line prefix matching and body header overrides.
    Returns (entry, type_config, target_file, parent).
    """
    # Always strip a keyword prefix from the subject (e.g. "TODO Buy milk"
    # → "Buy milk") so the title is clean regardless of which branch below
    # determines the type.
    cleaned_title, prefix_tc, prefix_kw = engine.resolve_subject_prefix(entry.title)
    entry.title = cleaned_title

    if entry.type_name:
        # Body header TYPE: takes precedence.
        type_config, keyword = engine.resolve_type(entry.type_name, entry.keyword)
    elif entry.keyword:
        # Body header KEYWORD: without TYPE: — resolve keyword to a type.
        type_config, keyword = engine.resolve_type(None, entry.keyword)
    else:
        # No body headers — use whatever the subject prefix matched.
        type_config, keyword = prefix_tc, prefix_kw

    entry.keyword = keyword
    entry.type_name = type_config.name

    # Resolve target and parent.
    target_file = engine.get_target(type_config, config, entry.target)
    parent = engine.get_parent(type_config, config, entry.parent)

    return entry, type_config, target_file, parent


def _process_message(msg, config, engine, logger, interactive=True):
    """Process a single email message. Returns True if processed."""
    # Check sender trust.
    from_addr = msg.get("From", "")
    if not is_trusted(from_addr, config):
        logger.info("Skipping untrusted sender: %s", from_addr)
        return False

    # Parse the email.
    try:
        entry = parse_email(msg, config)
    except Exception as exc:
        logger.error("Failed to parse email from %s: %s", from_addr, exc)
        if interactive:
            print(f"  Error parsing email: {exc}", file=sys.stderr)
        return False

    # Resolve type, target, parent.
    try:
        entry, type_config, target_file, parent = _resolve_entry(
            entry, engine, config
        )
    except Exception as exc:
        logger.error("Failed to resolve entry: %s", exc)
        if interactive:
            print(f"  Error resolving entry: {exc}", file=sys.stderr)
        return False

    # Handle attachments.
    saved_paths: list[str] = []
    if entry.attachments:
        att_dir = type_config.attachment_path or config.default_attachment_path
        if att_dir is None:
            att_dir = Path("~/.local/state/org-taube/attachments").expanduser()
        prefix = datetime.now().strftime("%Y%m%d")
        paths = save_attachments(entry.attachments, att_dir, prefix)
        saved_paths = [str(p) for p in paths]

    # Render the entry.
    rendered = render_entry(entry, type_config,
                            saved_attachment_paths=saved_paths or None)

    # Interactive mode: show preview and ask for confirmation.
    if interactive:
        print()
        print(f"{_DIM}{'─' * 60}{_RESET}")
        print(_colorize(rendered))
        print(f"{_DIM}{'─' * 60}{_RESET}")
        print(f"  Target: {_CYAN}{target_file}{_RESET}")
        if parent:
            print(f"  Parent: {_CYAN}{parent}{_RESET}")
        print()

        while True:
            response = input("  Write this entry? [Y/n/q] ").strip().lower()
            if response in ("", "y", "yes"):
                break
            elif response in ("n", "no"):
                logger.info("Skipped entry: %s", entry.title)
                print("  Skipped.")
                return False
            elif response in ("q", "quit"):
                print("  Quitting.")
                sys.exit(0)
            else:
                print("  Please enter y, n, or q.")

    # Write the entry.
    try:
        write_entry(rendered, target_file, parent)
    except Exception as exc:
        logger.error("Failed to write entry '%s': %s", entry.title, exc)
        if interactive:
            print(f"  Error writing entry: {exc}", file=sys.stderr)
        return False

    logger.info("Captured: %s → %s", entry.title, target_file)
    if interactive:
        print(f"  Captured: {entry.title}")

    return True


def main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="org-taube",
        description="Email-first capture pipeline for Org mode.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run in automatic mode (no prompts, for cron/plist).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config file (default: ~/.config/org-taube/config.toml).",
    )
    args = parser.parse_args(argv)
    interactive = not args.auto

    # Load config.
    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    logger = _setup_logging(config)

    # Build type engine.
    engine = TypeEngine(config.types)

    # Scan for unread messages.
    try:
        messages = scan_unread(config.maildir_path)
    except Exception as exc:
        logger.error("Failed to scan Maildir: %s", exc)
        print(f"Error scanning Maildir: {exc}", file=sys.stderr)
        sys.exit(1)

    if not messages:
        logger.debug("No unread messages")
        if interactive:
            print("No unread messages.")
        return

    if interactive:
        print(f"Found {len(messages)} unread message(s).")

    processed = 0
    for msg in messages:
        success = _process_message(msg, config, engine, logger, interactive)
        if success:
            try:
                mark_processed(msg, config.maildir_path, config.post_process)
            except Exception as exc:
                logger.error("Failed to mark message as processed: %s", exc)
                if interactive:
                    print(f"  Warning: could not mark as processed: {exc}",
                          file=sys.stderr)
            processed += 1

    if interactive:
        print(f"\nDone. Processed {processed}/{len(messages)} message(s).")
    logger.info("Run complete: %d/%d processed", processed, len(messages))
