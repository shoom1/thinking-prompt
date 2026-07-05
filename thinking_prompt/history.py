"""
Typed transcript history for ThinkingPromptSession.

Stores typed entries (styled text, explicit fragments, markdown/code
sources, baked ANSI) with per-entry render caches so theme switches can
re-render markdown/code from source. Public method names are unchanged
from the original fragment-list implementation; layout.py consumes
get_formatted_text() as before.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Callable, Optional

from prompt_toolkit.formatted_text import ANSI, FormattedText, to_formatted_text
from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple


def _coalesce(fragments: list[OneStyleAndTextTuple]) -> list[OneStyleAndTextTuple]:
    """Merge adjacent fragments with identical style; drop empty text.

    ANSI parsing produces ~one fragment per character; coalescing keeps
    memory and repaint cost proportional to styled runs instead.
    """
    out: list[OneStyleAndTextTuple] = []
    for frag in fragments:  # tolerate 3-tuples (mouse handlers)
        style, text = frag[0], frag[1]
        has_handler = len(frag) > 2
        if not text:
            continue
        if out and len(out[-1]) == 2 and out[-1][0] == style and not has_handler:
            out[-1] = (style, out[-1][1] + text)
        elif has_handler:
            out.append((style, text, frag[2]))  # type: ignore[misc]
        else:
            out.append((style, text))
    return out


@dataclass
class _Entry:
    """One transcript entry. kind: styled|formatted|markdown|code|ansi."""

    kind: str
    style: str = ""
    text: str = ""
    fragments: list[OneStyleAndTextTuple] = field(default_factory=list)
    source: str = ""
    language: str = ""
    # Deliberately `Optional[...]` rather than `X | None`: annotations are
    # deferred (PEP 563 future import) so `X | None` would define fine, but
    # resolving this dataclass's hints at runtime on the Python 3.9 floor
    # (typing.get_type_hints(), dataclass introspection tooling) raises
    # TypeError for `X | None` pre-3.10; Optional stays resolvable.
    truncate_lines: Optional[int] = None  # noqa: UP045
    cache: Optional[list[OneStyleAndTextTuple]] = None  # noqa: UP045


class FormattedTextHistory:
    """
    Thread-safe typed transcript of display output.

    Stores typed entries (styled text, explicit fragments, markdown/code
    sources, baked ANSI) to mimic console output in fullscreen mode.
    Markdown and code entries keep their source and a render cache so a
    theme switch can re-render them via ``invalidate_render_caches()``;
    ANSI entries are baked once and never re-themed.

    Example:
        history = FormattedTextHistory()

        # Add styled text
        history.append("class:user", ">>> hello\\n")
        history.append("class:response", "Hi there!\\n")

        # Get as FormattedText for display
        formatted = history.get_formatted_text()
    """

    def __init__(
        self,
        max_entries: int | None = None,
        render_markdown: Callable[[str], str] | None = None,
        render_code: Callable[[str, str], str] | None = None,
    ) -> None:
        self._entries: list[_Entry] = []
        self._max_entries = max_entries
        self._render_markdown = render_markdown
        self._render_code = render_code
        self._lock = threading.RLock()
        self._on_change: Callable[[], None] | None = None

    def set_on_change(self, callback: Callable[[], None]) -> None:
        """Set callback to trigger when history changes."""
        self._on_change = callback

    def _notify_change(self) -> None:
        """Notify that history has changed."""
        if self._on_change:
            self._on_change()

    def _append_entry(self, entry: _Entry) -> None:
        with self._lock:
            self._entries.append(entry)
            if self._max_entries is not None:
                while len(self._entries) > self._max_entries:
                    self._entries.pop(0)
            self._notify_change()

    def append(
        self, style: str, text: str, truncate_lines: int | None = None
    ) -> None:
        """
        Append a styled text fragment (re-themes via live Style).

        Args:
            style: Style class (e.g., "class:history.user-message").
            text: Text content.
            truncate_lines: Optional cap on rendered lines for this entry.
        """
        self._append_entry(
            _Entry(kind="styled", style=style, text=text, truncate_lines=truncate_lines)
        )

    def append_formatted(
        self, formatted: Iterable[OneStyleAndTextTuple]
    ) -> None:
        """
        Append caller-supplied fragments as a single entry (class: fragments re-theme).

        Args:
            formatted: FormattedText object or iterable of (style, text[, handler]) tuples.
        """
        self._append_entry(_Entry(kind="formatted", fragments=list(formatted)))

    def append_markdown(self, source: str) -> None:
        """Append markdown by source; re-rendered on theme change."""
        self._append_entry(_Entry(kind="markdown", source=source))

    def append_code(self, source: str, language: str) -> None:
        """Append code by source; re-rendered on theme change."""
        self._append_entry(_Entry(kind="code", source=source, language=language))

    def append_ansi(self, raw: str, truncate_lines: int | None = None) -> None:
        """Append pre-rendered ANSI (baked; never re-themed)."""
        self._append_entry(
            _Entry(kind="ansi", source=raw, truncate_lines=truncate_lines)
        )

    def _render_entry(self, entry: _Entry) -> list[OneStyleAndTextTuple]:
        if entry.kind == "styled":
            return [(entry.style, entry.text)]
        if entry.kind == "formatted":
            return entry.fragments
        if entry.cache is not None:
            return entry.cache
        if entry.kind == "markdown":
            ansi = (
                self._render_markdown(entry.source)
                if self._render_markdown
                else entry.source
            )
        elif entry.kind == "code":
            ansi = (
                self._render_code(entry.source, entry.language)
                if self._render_code
                else entry.source
            )
        else:  # ansi
            ansi = entry.source
        entry.cache = _coalesce(list(to_formatted_text(ANSI(ansi))))
        return entry.cache

    def get_formatted_text(self) -> FormattedText:
        """
        Get all entries rendered as FormattedText.

        Returns:
            FormattedText containing all stored fragments.
        """
        with self._lock:
            frags: list[OneStyleAndTextTuple] = []
            for entry in self._entries:
                frags.extend(self._render_entry(entry))
            return FormattedText(frags)

    def invalidate_render_caches(self) -> None:
        """Drop caches of re-renderable entries (markdown/code) on theme change."""
        with self._lock:
            for entry in self._entries:
                if entry.kind in ("markdown", "code"):
                    entry.cache = None
            self._notify_change()

    def iter_entries(self) -> list[_Entry]:
        """Snapshot of entries (for transcript repaint)."""
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._entries.clear()
            self._notify_change()

    @property
    def is_empty(self) -> bool:
        """Check if history is empty."""
        with self._lock:
            return len(self._entries) == 0

    def __len__(self) -> int:
        """Number of transcript entries."""
        with self._lock:
            return len(self._entries)
