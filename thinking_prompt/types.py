"""
Type definitions for thinking_prompt.

This module provides type aliases, protocols, and typed dictionaries
for better type safety throughout the package.
"""
from __future__ import annotations

import threading
from typing import (
    Any,
    Awaitable,
    Callable,
    List,
    Literal,
    Tuple,
    Union,
)

from prompt_toolkit.formatted_text import FormattedText


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

# Style fragment tuple (style_class, text)
StyleFragment = Tuple[str, str]

# List of style fragments
StyleFragments = List[StyleFragment]

# Welcome message types
WelcomeContent = Union[str, FormattedText, Any]  # Any for Rich renderables
WelcomeMessage = Union[WelcomeContent, Callable[[], WelcomeContent], None]


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

    @property
    def text(self) -> str:
        """Alias for get_content() for convenience."""
        return self.get_content()
