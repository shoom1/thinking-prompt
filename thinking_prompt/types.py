"""
Type definitions for thinking_prompt.

This module provides type aliases, protocols, and typed dictionaries
for better type safety throughout the package.
"""
from __future__ import annotations

import threading
from typing import (
    Awaitable,
    Callable,
    List,
    Literal,
    Optional,
    Union,
)


# =============================================================================
# Type Aliases
# =============================================================================

# Message roles supported by add_message()
MessageRole = Literal["user", "assistant", "thinking", "system"]

# Content callback type for thinking box
ContentCallback = Callable[[], str]

# Input handler types - can be sync or async
SyncInputHandler = Callable[[str], None]
AsyncInputHandler = Callable[[str], Awaitable[None]]
InputHandler = Union[SyncInputHandler, AsyncInputHandler]


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
        session.start_thinking(content.get_content)

        async for chunk in llm_stream():
            content.append(chunk)

        session.finish_thinking()
    """

    def __init__(self) -> None:
        self._chunks: List[str] = []
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
        content: Optional[StreamingContent],
        set_title: Callable[[str], None],
        get_title: Callable[[], str],
    ) -> None:
        self._content = content
        self._set_title = set_title
        self._get_title = get_title

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

    # -- Title control --------------------------------------------------------

    def set_title(self, text: str) -> None:
        """Set the thinking separator title."""
        self._set_title(text)

    @property
    def title(self) -> str:
        """Get the current separator title."""
        return self._get_title()
