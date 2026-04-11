"""Type matching and routing for org-taube."""

from pathlib import Path

from org_taube import Config, TypeConfig
from org_taube.config import BUILTIN_TYPES


class TypeEngine:
    """Holds all types and resolves subjects, types, and targets.

    Parameters
    ----------
    types:
        Mapping of type name to TypeConfig.  Typically comes straight
        from ``Config.types`` which already includes built-ins.
    """

    def __init__(self, types: dict[str, TypeConfig]) -> None:
        self._types = dict(types)

        # Ensure the built-in note type is always available as a
        # fallback, even if the caller passes an empty dict.
        for name, builtin in BUILTIN_TYPES.items():
            self._types.setdefault(name, builtin)

        # Pre-build a keyword → type lookup (lowercase keyword →
        # (type_config, original-case keyword)).  If the same keyword
        # appears in multiple types the first one wins.
        self._keyword_map: dict[str, tuple[TypeConfig, str]] = {}
        for tc in self._types.values():
            for kw in tc.keywords:
                kw_lower = kw.lower()
                if kw_lower not in self._keyword_map:
                    self._keyword_map[kw_lower] = (tc, kw)

    @property
    def note_type(self) -> TypeConfig:
        """Return the note type (always present)."""
        return self._types["note"]

    # ------------------------------------------------------------------ #
    #  Subject-prefix resolution
    # ------------------------------------------------------------------ #

    def resolve_subject_prefix(
        self, subject: str
    ) -> tuple[str, TypeConfig, str | None]:
        """Resolve a subject line to (cleaned_title, type_config, keyword).

        Match logic (case-insensitive on the first word of the subject):

        1. First word matches a **keyword** in any type -> use that
           type with that keyword; the rest is the title.
        2. No match -> note type, full subject as title.

        For types without a ``default_keyword``, matched keywords are
        used for routing only — they are not returned as the keyword
        so they don't appear in the heading.
        """
        stripped = subject.strip()
        if not stripped:
            return ("", self.note_type, None)

        parts = stripped.split(None, 1)
        first_word = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        first_lower = first_word.lower()

        # 1. Keyword match
        if first_lower in self._keyword_map:
            tc, matched_kw = self._keyword_map[first_lower]
            # If the type has no default_keyword, the keyword is only
            # for routing — don't render it in the heading.
            effective_kw = matched_kw if tc.default_keyword is not None else None
            return (rest, tc, effective_kw)

        # 2. No match -> note
        return (stripped, self.note_type, None)

    # ------------------------------------------------------------------ #
    #  Body-header type resolution
    # ------------------------------------------------------------------ #

    def resolve_type(
        self,
        type_name: str | None,
        keyword: str | None,
    ) -> tuple[TypeConfig, str | None]:
        """Resolve explicit TYPE / KEYWORD from body headers.

        Returns (type_config, effective_keyword).

        - If *type_name* matches a known type, use it.
        - If *keyword* is valid for that type, keep it; otherwise
          fall back to the type's ``default_keyword``.
        - Unknown *type_name* -> note type.
        - *type_name* is ``None`` -> note type.
        """
        if type_name is not None:
            type_lower = type_name.lower()
            tc = self._types.get(type_lower)
        else:
            tc = None

        if tc is None:
            tc = self.note_type

        effective_kw = self._resolve_keyword(tc, keyword)
        return (tc, effective_kw)

    # ------------------------------------------------------------------ #
    #  Target / parent routing
    # ------------------------------------------------------------------ #

    def get_target(
        self,
        type_config: TypeConfig,
        config: Config,
        explicit_target: Path | None,
    ) -> Path:
        """Return the target file path for an entry.

        Resolution order:
        1. *explicit_target* (from the email).
        2. ``type_config.file`` (from ``[types.*]``).
        3. ``config.default_file`` (from ``[defaults]``).

        Raises ``ValueError`` if no target can be determined.
        """
        if explicit_target is not None:
            return explicit_target

        if type_config.file is not None:
            return type_config.file

        if config.default_file is not None:
            return config.default_file

        raise ValueError(
            f"No target configured for type '{type_config.name}' "
            "and no default file is set."
        )

    def get_parent(
        self,
        type_config: TypeConfig,
        config: Config,
        explicit_parent: str | None,
    ) -> str | None:
        """Return the parent heading for filing an entry.

        Resolution order:
        1. *explicit_parent* (from the email).
        2. ``type_config.parent`` (from ``[types.*]``).
        3. ``None`` (file at top-level).
        """
        if explicit_parent is not None:
            return explicit_parent

        if type_config.parent is not None:
            return type_config.parent

        return None

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _resolve_keyword(
        self, type_config: TypeConfig, keyword: str | None
    ) -> str | None:
        """Return *keyword* if it is valid for *type_config*, else default."""
        if keyword is not None:
            # Case-insensitive check against the type's keyword list.
            kw_upper = keyword.upper()
            for valid_kw in type_config.keywords:
                if valid_kw.upper() == kw_upper:
                    return valid_kw
        return type_config.default_keyword
