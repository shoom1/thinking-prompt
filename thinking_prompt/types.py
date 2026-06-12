"""
Type definitions for thinking_prompt.

This module provides type aliases, protocols, and typed dictionaries
for better type safety throughout the package.
"""
from __future__ import annotations

import threading
from collections.abc import Awaitable
from typing import (
    Any,
    Callable,
    Literal,
    Union,
)

# =============================================================================
# Type Aliases
# =============================================================================

# Message roles supported by add_message()
MessageRole = Literal["user", "assistant", "thinking", "system"]

# Content format for thinking box rendering
ContentFormat = Literal["plain", "ansi"]

# Content callback type for thinking box
ContentCallback = Callable[[], str]

# Input handler types - can be sync or async
SyncInputHandler = Callable[[str], None]
AsyncInputHandler = Callable[[str], Awaitable[None]]
InputHandler = Union[SyncInputHandler, AsyncInputHandler]

# Default spinner animation frames for the thinking header.
# Single source of truth — referenced by layout.ThinkingHeader and
# app_info.AppInfo.
DEFAULT_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


# =============================================================================
# Utility Functions
# =============================================================================

def truncate_to_lines(content: str, max_lines: int, suffix: str = "...") -> str:
    """
    Truncate content to max_lines, appending suffix if truncated.

    Args:
        content: The content to truncate.
        max_lines: Maximum number of lines to keep.
        suffix: Suffix to append when truncated (default: "...").

    Returns:
        Truncated content with suffix if over limit, otherwise content.rstrip().
    """
    lines = content.split('\n')
    if len(lines) > max_lines:
        return '\n'.join(lines[:max_lines]) + '\n' + suffix
    return content.rstrip()


def truncate_ansi_to_lines(content: str, max_lines: int) -> str:
    """
    Truncate ANSI-formatted content to max_lines with a reset suffix.

    Inserts an ANSI reset (``\\033[0m``) before the ``...`` suffix to
    prevent style leakage into subsequent output.

    Args:
        content: The ANSI-formatted content to truncate.
        max_lines: Maximum number of lines to keep.

    Returns:
        Truncated content with ANSI reset + ``...`` if over limit,
        otherwise content.rstrip().
    """
    return truncate_to_lines(content, max_lines, suffix="\033[0m...")


# =============================================================================
# Helper Classes
# =============================================================================

class StreamingContent:
    """
    Thread-safe helper for streaming content to thinking box.

    This class provides a convenient way to accumulate content
    for the thinking box in a thread-safe manner.

    Example:
        content = StreamingContent()
        ctx = session.start_thinking(content.get_content)

        async for chunk in llm_stream():
            content.append(chunk)

        ctx.finish()
    """

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._lock = threading.Lock()

    def append(self, chunk: str) -> None:
        """Append a chunk of content (thread-safe)."""
        with self._lock:
            self._chunks.append(chunk)

    def get_content(self) -> str:
        """Get the accumulated content (thread-safe)."""
        with self._lock:
            return "".join(self._chunks)

    def clear(self) -> None:
        """Clear all accumulated content (thread-safe)."""
        with self._lock:
            self._chunks.clear()

    def __len__(self) -> int:
        """Return the number of chunks."""
        with self._lock:
            return len(self._chunks)

    def set_line(self, index: int, text: str) -> None:
        """Set the content of a specific line (thread-safe).

        Supports negative indices (-1 is last non-empty line).
        If index is beyond current line count, extends with empty lines.
        """
        with self._lock:
            current = "".join(self._chunks)
            # Split preserving trailing newline awareness
            has_trailing_newline = current.endswith("\n")
            lines = current.split("\n")
            # Remove trailing empty string from split if content ended with \n
            if has_trailing_newline and lines and lines[-1] == "":
                lines.pop()

            # Handle negative indices
            if index < 0:
                index = len(lines) + index

            # Extend if needed
            while index >= len(lines):
                lines.append("")

            lines[index] = text

            self._chunks.clear()
            self._chunks.append("\n".join(lines) + ("\n" if has_trailing_newline else ""))

    def append_rich(self, renderable: Any, *, theme: Any = None) -> None:
        """Append a Rich renderable or markup string, converted to ANSI.

        Args:
            renderable: Rich markup string or Rich renderable object.
            theme: Optional Rich Theme for styling.
        """
        from .rich_utils import _renderable_to_ansi
        self.append(_renderable_to_ansi(renderable, theme=theme))

    def set_line_rich(self, index: int, renderable: Any, *, theme: Any = None) -> None:
        """Set a line from a Rich renderable or markup string.

        Args:
            index: Line index (supports negative indices).
            renderable: Rich markup string or Rich renderable object.
            theme: Optional Rich Theme for styling.
        """
        from .rich_utils import _renderable_to_ansi
        ansi = _renderable_to_ansi(renderable, theme=theme)
        self.set_line(index, ansi.split('\n')[0])

    @property
    def text(self) -> str:
        """Alias for get_content() for convenience."""
        return self.get_content()


class ThinkingContext:
    """Context for a thinking session — content accumulation + title control.

    Wraps an optional StreamingContent with title control callbacks.
    When used via the ``thinking()`` context manager, content is wired up
    automatically.  When used via ``start_thinking()`` (low-level API),
    content is None and content methods raise AttributeError.
    """

    def __init__(
        self,
        content: StreamingContent | None,
        set_title: Callable[[str], None],
        get_title: Callable[[], str],
        set_format: Callable[[ContentFormat], None] | None = None,
        rich_theme: Any = None,
        finish: Callable[..., str] | None = None,
    ) -> None:
        self._content = content
        self._set_title = set_title
        self._get_title = get_title
        self._set_format = set_format
        self._format_set = False
        self._rich_theme = rich_theme
        self._finish = finish

    # -- StreamingContent delegation ------------------------------------------

    def _require_content(self) -> StreamingContent:
        if self._content is None:
            raise AttributeError(
                "ThinkingContext has no content — use the thinking() "
                "context manager for automatic content management."
            )
        return self._content

    def append(self, chunk: str) -> None:
        """Append a chunk of content (thread-safe)."""
        self._require_content().append(chunk)

    def get_content(self) -> str:
        """Get the accumulated content (thread-safe)."""
        return self._require_content().get_content()

    def clear(self) -> None:
        """Clear all accumulated content (thread-safe)."""
        self._require_content().clear()

    def set_line(self, index: int, text: str) -> None:
        """Set the content of a specific line (thread-safe)."""
        self._require_content().set_line(index, text)

    def __len__(self) -> int:
        """Return the number of chunks."""
        return len(self._require_content())

    @property
    def text(self) -> str:
        """Get the accumulated content as a string."""
        return self._require_content().text

    # -- Rich convenience methods ---------------------------------------------

    def _ensure_ansi_format(self) -> None:
        """Switch content format to ANSI once (idempotent)."""
        if self._set_format is not None and not self._format_set:
            self._set_format("ansi")
            self._format_set = True

    def append_rich(self, renderable: Any, *, theme: Any = None) -> None:
        """Append a Rich renderable or markup string, auto-switching to ANSI format.

        Args:
            renderable: Rich markup string or Rich renderable object.
            theme: Optional Rich Theme override (defaults to session theme).
        """
        self._ensure_ansi_format()
        self._require_content().append_rich(
            renderable, theme=theme or self._rich_theme
        )

    def set_line_rich(self, index: int, renderable: Any, *, theme: Any = None) -> None:
        """Set a line from a Rich renderable, auto-switching to ANSI format.

        Args:
            index: Line index (supports negative indices).
            renderable: Rich markup string or Rich renderable object.
            theme: Optional Rich Theme override (defaults to session theme).
        """
        self._ensure_ansi_format()
        self._require_content().set_line_rich(
            index, renderable, theme=theme or self._rich_theme
        )

    # -- Title control --------------------------------------------------------

    def set_title(self, text: str) -> None:
        """Set the thinking separator title."""
        self._set_title(text)

    @property
    def title(self) -> str:
        """Get the current separator title."""
        return self._get_title()

    # -- Finish control -------------------------------------------------------

    def finish(
        self,
        add_to_history: bool = True,
        echo_to_console: bool | None = None,
    ) -> str:
        """Finish this thinking box and remove it from display.

        Args:
            add_to_history: If True, add content to chat history.
            echo_to_console: If True, print content to console.

        Returns:
            The full content that was displayed.

        Raises:
            RuntimeError: If no finish callback was provided.
        """
        if self._finish is None:
            raise RuntimeError(
                "No finish callback — use the thinking() context "
                "manager for automatic lifecycle management."
            )
        return self._finish(
            add_to_history=add_to_history, echo_to_console=echo_to_console
        )
