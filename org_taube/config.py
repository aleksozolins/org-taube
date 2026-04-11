"""Config loading for org-taube."""

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Python < 3.11 requires the 'tomli' package: pip install tomli"
        ) from exc

from org_taube import Config, TypeConfig

DEFAULT_CONFIG_PATH = Path("~/.config/org-taube/config.toml").expanduser()

# Built-in types always available, even without config.
BUILTIN_TYPES: dict[str, TypeConfig] = {
    "task": TypeConfig(
        name="task",
        keywords=["TODO", "DONE"],
        default_keyword="TODO",
    ),
    "note": TypeConfig(
        name="note",
        keywords=[],
        default_keyword=None,
    ),
}


def _expand(p: str) -> Path:
    """Expand ~ and return a resolved Path."""
    return Path(p).expanduser()



def _parse_type(name: str, data: dict) -> TypeConfig:
    """Parse a single [types.*] section into a TypeConfig.

    For built-in type names (task, note), the config overlays onto
    the built-in so keywords are preserved.  The task type also
    supports an optional ``keywords`` list in config — these are
    merged with the built-in TODO and DONE (duplicates removed).

    Custom types can also define keywords for subject-line matching.
    These keywords are used for routing only — they are not rendered
    in the heading unless the type has a default_keyword.
    """
    attachment_path = None
    if "attachment_path" in data:
        attachment_path = _expand(data["attachment_path"])
    file_path = None
    if "file" in data:
        file_path = _expand(data["file"])

    # Start from built-in if this is a known type.
    builtin = BUILTIN_TYPES.get(name)

    # Merge user-supplied keywords with built-in keywords (if any).
    if builtin:
        keywords = list(builtin.keywords)
        seen = {kw.upper() for kw in keywords}
    else:
        keywords = []
        seen = set()
    for kw in data.get("keywords", []):
        if kw.upper() not in seen:
            keywords.append(kw)
            seen.add(kw.upper())

    return TypeConfig(
        name=name,
        keywords=keywords,
        default_keyword=builtin.default_keyword if builtin else None,
        tags=data.get("tags", []),
        properties=data.get("properties", []),
        attachment_path=attachment_path,
        file=file_path,
        parent=data.get("parent"),
    )


def load_config(path: Path | None = None) -> Config:
    """Load and parse the org-taube TOML config.

    Parameters
    ----------
    path:
        Explicit config file path.  Falls back to
        ``~/.config/org-taube/config.toml`` when *None*.

    Returns
    -------
    Config
        Fully parsed configuration with all paths expanded.

    Raises
    ------
    FileNotFoundError
        When the config file does not exist.
    ValueError
        When required keys are missing or values are invalid.
    """
    config_path = path or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Copy config.toml.example to ~/.config/org-taube/config.toml "
            "and edit it for your setup."
        )

    with open(config_path, "rb") as fh:
        raw = tomllib.load(fh)

    # --- maildir (required) ---
    maildir_section = raw.get("maildir", {})
    maildir_path_str = maildir_section.get("path")
    if not maildir_path_str:
        raise ValueError("[maildir] section must include 'path'")
    maildir_path = _expand(maildir_path_str)

    # --- post_process and signature_separator ---
    # Check top-level first, then maildir section.
    post_process = raw.get(
        "post_process",
        maildir_section.get("post_process", "read"),
    )
    if post_process not in ("read", "delete"):
        raise ValueError(
            f"post_process must be 'read' or 'delete', got '{post_process}'"
        )

    signature_separator = raw.get(
        "signature_separator",
        maildir_section.get("signature_separator", "-- "),
    )

    # --- trust ---
    trust_section = raw.get("trust", {})
    trusted_senders = trust_section.get("senders", [])
    trust_all = trust_section.get("trust_all", False)

    # --- defaults ---
    defaults_section = raw.get("defaults", {})
    default_file = None
    if "file" in defaults_section:
        default_file = _expand(defaults_section["file"])
    default_attachment_path = None
    if "attachment_path" in defaults_section:
        default_attachment_path = _expand(defaults_section["attachment_path"])

    # --- types (built-ins first, config overrides) ---
    types: dict[str, TypeConfig] = dict(BUILTIN_TYPES)

    types_section = raw.get("types", {})
    for name, data in types_section.items():
        types[name] = _parse_type(name, data)

    return Config(
        maildir_path=maildir_path,
        default_file=default_file,
        default_attachment_path=default_attachment_path,
        types=types,
        trusted_senders=trusted_senders,
        trust_all=trust_all,
        post_process=post_process,
        signature_separator=signature_separator,
    )
