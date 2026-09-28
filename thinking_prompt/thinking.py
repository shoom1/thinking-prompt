"""
Thinking box control for ThinkingPromptSession.

A FormattedTextControl that manages thinking box state and content formatting.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from prompt_toolkit.formatted_text import (
    ANSI,
    FormattedText,
    StyleAndTextTuples,
    fragment_list_to_text,
    to_formatted_text,
)
from prompt_toolkit.formatted_text.utils import fragment_list_width, split_lines
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent

from .types import ContentFormat, Overflow

logger = logging.getLogger(__name__)

# Width assumed when formatting before the first render (size unknown).
_DEFAULT_WIDTH = 80


def _format_key_for_display(key: str) -> str:
    """
    Format a prompt_toolkit key binding for display.

    Converts key binding syntax to human-readable format.
    Examples: "c-t" → "ctrl-t", "c-e" → "ctrl-e", "escape" → "escape"

    Args:
        key: Key binding in prompt_toolkit format.

    Returns:
        Human-readable key representation.
    """
    if key.startswith("c-"):
        return f"ctrl-{key[2:]}"
    return key


class ThinkingBoxControl(FormattedTextControl):
    """
    A FormattedTextControl that displays thinking box content.

    Manages:
    - Active/inactive state (thinking or not)
    - Expanded/collapsed state
    - Content retrieval via callback
    - Fitting content to the rows it gets: when it overflows, one end is
      kept (``overflow``: "tail" = newest lines, "head" = first lines) and a
      hint names the hidden lines. Collapsed, the rows are capped at
      ``max_collapsed_lines``; expanded, only by the window's height.

    Created once and passed directly to Window(content=...).
    Use start() to begin thinking and finish() to end.

    Example:
        control = ThinkingBoxControl(max_collapsed_lines=10)

        # Use directly in layout
        Window(content=control, ...)

        # Start thinking with content callback
        chunks = []
        control.start(lambda: ''.join(chunks))

        chunks.append("Processing...\\n")
        # UI automatically updates via content_callback

        control.expand()  # User pressed Ctrl+E

        content, was_expanded, fmt = control.finish()
    """

    def __init__(
        self,
        max_collapsed_lines: int = 15,
        style: str = "class:thinking-box",
        expand_key: str = "c-t",
        overflow: Overflow = "tail",
    ) -> None:
        """
        Initialize the thinking box control.

        Args:
            max_collapsed_lines: Max lines when collapsed (must be >= 2).
            style: Style class for the content.
            expand_key: Key binding for expand/collapse (prompt_toolkit format).
            overflow: Which end of overflowing content stays visible:
                "tail" (newest lines, default) or "head" (first lines).
        """
        self._content_callback: Callable[[], str] | None = None
        self._max_collapsed_lines = max_collapsed_lines
        self._box_style = style
        self._expand_key = expand_key
        self._overflow: Overflow = overflow
        # Width of the last render, for wrap-aware checks made between
        # renders (e.g. whether the expand key applies).
        self._last_width = _DEFAULT_WIDTH
        self._is_expanded = False
        self._content_format: ContentFormat = "plain"
        self._lock = threading.RLock()

        # Pass our formatting function to parent
        super().__init__(
            text=self._get_formatted_text,
            style=style,
            focusable=False,
            show_cursor=False,
        )

    def start(
        self,
        content_callback: Callable[[], str],
        content_format: ContentFormat = "plain",
    ) -> None:
        """
        Start thinking with the given content callback.

        Args:
            content_callback: Callable that returns the current content.
            content_format: Format for rendering content ("plain" or "ansi").
        """
        with self._lock:
            self._content_callback = content_callback
            self._is_expanded = False
            self._content_format = content_format

    def finish(self) -> tuple[str, bool, ContentFormat]:
        """
        Finish thinking and reset state.

        Returns:
            Tuple of (full_content, was_expanded, content_format).
        """
        with self._lock:
            content = self.content
            was_expanded = self._is_expanded
            fmt = self._content_format
            # Reset state
            self._content_callback = None
            self._is_expanded = False
            self._content_format = "plain"
            return content, was_expanded, fmt

    @property
    def is_active(self) -> bool:
        """Check if thinking is active (has a content callback)."""
        with self._lock:
            return self._content_callback is not None

    @property
    def content_format(self) -> ContentFormat:
        """Get the current content format."""
        with self._lock:
            return self._content_format

    def set_content_format(self, fmt: ContentFormat) -> None:
        """Set the content format (e.g. to switch to ANSI mode dynamically)."""
        with self._lock:
            self._content_format = fmt

    def _get_formatted_text(self) -> FormattedText:
        """
        Get content as FormattedText, fitted as if rendered at the last
        known width with no height limit beyond the collapsed cap.

        Rendering goes through create_content(), which knows the real size;
        this is FormattedTextControl's text callable (and a test hook).
        """
        return self._format(self._last_width, None)

    def create_content(self, width: int, height: int | None) -> UIContent:
        """Render content fitted to the window's actual width and height.

        Bypasses FormattedTextControl's per-render text cache: the fit
        depends on the size, which its text callable can't see.
        """
        self._last_width = width
        fragments = to_formatted_text(self._format(width, height), style=self.style)
        lines = [list(line) for line in split_lines(fragments)]
        return UIContent(
            get_line=lambda i: lines[i], line_count=len(lines), show_cursor=False
        )

    def _format(self, width: int, height: int | None) -> FormattedText:
        """Fit the current content into ``height`` rows of ``width`` columns."""
        if self._content_callback is None:
            return FormattedText([])

        try:
            content = self._content_callback()
        except Exception:
            logger.exception("Error in content callback")
            return FormattedText([])

        if not content:
            return FormattedText([])

        with self._lock:
            limit = height
            if not self._is_expanded:
                limit = (
                    self._max_collapsed_lines
                    if limit is None
                    else min(limit, self._max_collapsed_lines)
                )
            return self._fit(self._content_lines(content), width, limit)

    def _content_lines(self, content: str) -> list[StyleAndTextTuples]:
        """Split content into display lines of fragments.

        ANSI content is parsed as a whole before splitting, so a style
        opened on an earlier line still applies to later lines even when
        the earlier ones are cut off. Trailing blank lines are not content
        (a trailing newline ends the last line), as in split_content_lines.
        """
        if self._content_format == "ansi":
            fragments = to_formatted_text(ANSI(content))
        else:
            fragments = to_formatted_text([(self._box_style, content)])
        lines = [list(line) for line in split_lines(fragments)]
        while len(lines) > 1 and not fragment_list_to_text(lines[-1]).strip():
            lines.pop()
        return lines

    @staticmethod
    def _rows(line: StyleAndTextTuples, width: int) -> int:
        """Rows a line occupies when wrapped at ``width`` columns."""
        if width <= 0:
            return 1
        return max(1, -(-fragment_list_width(line) // width))

    def _fit(
        self, lines: list[StyleAndTextTuples], width: int, limit: int | None
    ) -> FormattedText:
        """Keep the lines that fit in ``limit`` rows (None = no limit).

        On overflow one row goes to the hint and the rest to lines from the
        ``overflow`` end — at least one line, even if it alone overflows.
        """
        rows = [self._rows(line, width) for line in lines]
        if limit is None or sum(rows) <= limit:
            return self._join(lines)

        tail = self._overflow == "tail"
        order = range(len(lines) - 1, -1, -1) if tail else range(len(lines))
        budget = max(1, limit - 1)
        kept: list[int] = []
        used = 0
        for i in order:
            if kept and used + rows[i] > budget:
                break
            kept.append(i)
            used += rows[i]
        body = [lines[i] for i in sorted(kept)]
        if limit < 2:
            return self._join(body)  # no room for a hint

        hint: StyleAndTextTuples = [
            ("class:thinking-box.hint", self._hint(len(lines) - len(kept)))
        ]
        return self._join([hint, *body] if tail else [*body, hint])

    def _hint(self, hidden: int) -> str:
        """The line naming how many lines are hidden, and the toggle key."""
        noun = "line" if hidden == 1 else "lines"
        earlier = "earlier " if self._overflow == "tail" else ""
        action = "collapse" if self._is_expanded else "expand"
        key = _format_key_for_display(self._expand_key)
        return f"+{hidden} {earlier}{noun}... {key} to {action}"

    @staticmethod
    def _join(lines: list[StyleAndTextTuples]) -> FormattedText:
        """Join fragment lines with newlines."""
        out: StyleAndTextTuples = []
        for i, line in enumerate(lines):
            if i:
                out.append(("", "\n"))
            out.extend(line)
        return FormattedText(out)

    @property
    def content(self) -> str:
        """Get raw content from callback."""
        if self._content_callback is None:
            return ""
        try:
            return self._content_callback()
        except Exception:
            logger.exception("Error in content callback")
            return ""

    @property
    def is_expanded(self) -> bool:
        """Check if thinking box is expanded."""
        with self._lock:
            return self._is_expanded

    @property
    def max_collapsed_lines(self) -> int:
        """Get max lines for collapsed state."""
        return self._max_collapsed_lines

    @property
    def overflow(self) -> Overflow:
        """Which end of overflowing content stays visible."""
        return self._overflow

    def expand(self) -> None:
        """Expand the thinking box."""
        with self._lock:
            self._is_expanded = True

    def collapse(self) -> None:
        """Collapse the thinking box."""
        with self._lock:
            self._is_expanded = False

    def toggle_expanded(self) -> None:
        """Toggle expanded/collapsed state."""
        with self._lock:
            self._is_expanded = not self._is_expanded

    @property
    def can_toggle_expanded(self) -> bool:
        """
        Check if expand toggle should be available.

        Returns True when:
        - Already expanded (can collapse), OR
        - Active and content overflows the collapsed rows (hint is visible)
        """
        with self._lock:
            if self._is_expanded:
                return True

            if not self.is_active:
                return False

            return self.get_line_count(self._last_width) > self._max_collapsed_lines

    def get_line_count(self, width: int = _DEFAULT_WIDTH) -> int:
        """
        Count display rows of the content, wrapped at ``width`` columns.

        Args:
            width: Terminal width for wrapping calculation.

        Returns:
            Number of display rows (0 when there is no content).
        """
        content = self.content
        if not content:
            return 0

        with self._lock:
            return sum(self._rows(line, width) for line in self._content_lines(content))
