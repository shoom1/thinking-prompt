"""
Thinking box control for ThinkingPromptSession.

A FormattedTextControl that manages thinking box state and content formatting.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional, Tuple

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.controls import FormattedTextControl

from .types import truncate_to_lines

logger = logging.getLogger(__name__)


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
    - Formatting with expand hint when collapsed and overflowing
    - Truncation with "..." for console output

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

        content, was_expanded = control.finish()
    """

    def __init__(
        self,
        max_collapsed_lines: int = 15,
        style: str = "class:thinking-box",
        expand_key: str = "c-t",
    ) -> None:
        """
        Initialize the thinking box control.

        Args:
            max_collapsed_lines: Max lines when collapsed (must be >= 2).
            style: Style class for the content.
            expand_key: Key binding for expand/collapse (prompt_toolkit format).
        """
        self._content_callback: Optional[Callable[[], str]] = None
        self._max_collapsed_lines = max_collapsed_lines
        self._box_style = style
        self._expand_key = expand_key
        self._is_expanded = False
        self._lock = threading.RLock()

        # Pass our formatting function to parent
        super().__init__(
            text=self._get_formatted_text,
            style=style,
            focusable=False,
            show_cursor=False,
        )

    def start(self, content_callback: Callable[[], str]) -> None:
        """
        Start thinking with the given content callback.

        Args:
            content_callback: Callable that returns the current content.
        """
        with self._lock:
            self._content_callback = content_callback
            self._is_expanded = False

    def finish(self) -> Tuple[str, bool]:
        """
        Finish thinking and reset state.

        Returns:
            Tuple of (full_content, was_expanded).
        """
        with self._lock:
            content = self.content
            was_expanded = self._is_expanded
            # Reset state
            self._content_callback = None
            self._is_expanded = False
            return content, was_expanded
    
    @property
    def is_active(self) -> bool:
        """Check if thinking is active (has a content callback)."""
        with self._lock:
            return self._content_callback is not None

    def _get_formatted_text(self) -> FormattedText:
        """
        Get content as FormattedText for display.

        Transforms the raw content from callback, adding expand hint
        when collapsed and content overflows.
        """
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
            lines = content.split('\n')

            # When collapsed and overflowing, truncate to make room for hint
            if not self._is_expanded and len(lines) > self._max_collapsed_lines - 1:
                # Show max_collapsed_lines - 1 lines of content + hint line
                truncated_lines = lines[:self._max_collapsed_lines - 1]
                truncated_content = '\n'.join(truncated_lines)

                fragments: List[Tuple[str, str]] = [
                    (self._box_style, truncated_content + '\n'),
                    ("class:thinking-box.hint", f"+{len(lines) - (self._max_collapsed_lines - 1)} lines... {_format_key_for_display(self._expand_key)} to expand"),
                ]
            else:
                fragments = [(self._box_style, content)]

            return FormattedText(fragments)

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
        - Active and content overflows (hint is visible, can expand)
        """
        with self._lock:
            if self._is_expanded:
                return True

            if not self.is_active:
                return False

            # Check if content overflows (same condition as showing hint)
            content = self.content
            if not content:
                return False

            lines = content.split('\n')
            return len(lines) > self._max_collapsed_lines - 1

    def get_key_bindings(
        self,
        is_fullscreen: Optional[Callable[[], bool]] = None,
    ) -> KeyBindings:
        """
        Get key bindings for this control.

        Args:
            is_fullscreen: Optional callback that returns True if in fullscreen mode.
                          Expand key is disabled in fullscreen mode.

        Returns:
            KeyBindings with expand/collapse key (prompt mode only).
        """
        kb = KeyBindings()

        # Expand key only available when:
        # - Can toggle expanded (content overflows or already expanded)
        # - Not in fullscreen mode
        def can_toggle() -> bool:
            if not self.can_toggle_expanded:
                return False
            if is_fullscreen and is_fullscreen():
                return False
            return True

        @kb.add(self._expand_key, filter=Condition(can_toggle))
        def toggle_expand(event) -> None:
            self.toggle_expanded()

        return kb

    def get_console_output(self) -> str:
        """
        Get content formatted for console output.

        When collapsed and content exceeds max_collapsed_lines, returns
        truncated content with "..." appended.

        Returns:
            Content string, possibly truncated with "...".
        """
        content = self.content
        if not content or not content.strip():
            return ""

        with self._lock:
            if self._is_expanded:
                return content.rstrip()

            # Same logic as _get_formatted_text: max_height - 1 lines + "..."
            return truncate_to_lines(content, self._max_collapsed_lines - 1)

    def get_line_count(self, width: int = 80) -> int:
        """
        Count display lines in content (accounting for wrapping).

        Args:
            width: Terminal width for wrapping calculation.

        Returns:
            Number of display lines.
        """
        content = self.content
        if not content:
            return 0

        lines = content.split('\n')
        total = 0
        for line in lines:
            if not line:
                total += 1
            else:
                # Account for wrapping
                total += max(1, (len(line) + width - 1) // width)
        return total

