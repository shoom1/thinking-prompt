"""
Type definitions for thinking_prompt.

This module provides type aliases, protocols, and typed dictionaries
for better type safety throughout the package.
"""
from __future__ import annotations

import logging
from collections.abc import Coroutine
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Literal,
    Union,
)

if TYPE_CHECKING:
    from .streaming import StreamingContent

logger = logging.getLogger(__name__)

# =============================================================================
# Type Aliases
# =============================================================================

# Content format for thinking box rendering
ContentFormat = Literal["plain", "ansi"]

# Which end of overflowing thinking-box content stays visible: "tail" keeps
# the newest lines (streaming), "head" the first lines (e.g. a task list).
Overflow = Literal["tail", "head"]

# How a dialog is drawn: "box" floats a framed dialog over the session;
# "inline" draws it as rows between the prompt and the status bar.
Placement = Literal["box", "inline"]


def check_placement(value: object, *, optional: bool = False) -> None:
    """Raise ValueError unless ``value`` is a Placement (or None, when ``optional``)."""
    if optional and value is None:
        return
    if value not in ("box", "inline"):
        raise ValueError(f"placement must be 'box' or 'inline', got {value!r}")

# Returns a thinking box's current content; the box re-reads it while drawn.
ContentCallback = Callable[[], str]

# Handles one line of submitted input: a function, or an async function
# (the session runs its coroutine as a task that Ctrl+C can cancel).
InputHandler = Union[
    Callable[[str], None], Callable[[str], Coroutine[Any, Any, None]]
]

# Default spinner animation frames for the thinking header.
# Single source of truth — referenced by layout.ThinkingHeader and
# app_info.AppInfo.
DEFAULT_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


# =============================================================================
# Helper Classes
# =============================================================================

class ThinkingContext:
    """Context for a thinking session — content accumulation + title control.

    Wraps an optional StreamingContent with title control callbacks.
    A box started with a content callback (``start_thinking(callback)``)
    has no content of its own: content methods raise AttributeError.

    Once the box is finished (by ``finish()``, or by the session on
    Ctrl+C or when its handler ends), ``is_finished`` is True: writes no
    longer show anywhere (the first one logs a warning), and ``finish()``
    returns the content again without echoing it twice.
    """

    def __init__(
        self,
        content: StreamingContent | None,
        set_title: Callable[[str], None],
        get_title: Callable[[], str],
        set_format: Callable[[ContentFormat], None] | None = None,
        rich_theme: Any = None,
        finish: Callable[..., str] | None = None,
        is_finished: Callable[[], bool] | None = None,
    ) -> None:
        self._content = content
        self._set_title = set_title
        self._get_title = get_title
        self._set_format = set_format
        self._format_set = False
        self._rich_theme = rich_theme
        self._finish = finish
        self._is_finished = is_finished
        self._warned_finished = False

    @property
    def is_finished(self) -> bool:
        """True once the box is finished and no longer displayed."""
        return self._is_finished() if self._is_finished is not None else False

    def _note_write(self, what: str) -> None:
        """Warn (once) that a write to a finished box shows nowhere."""
        if self._warned_finished or not self.is_finished:
            return
        self._warned_finished = True
        logger.warning(
            "thinking box already finished: %s() and later writes have no effect", what
        )

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
        self._note_write("append")
        self._require_content().append(chunk)

    def get_content(self) -> str:
        """Get the accumulated content (thread-safe)."""
        return self._require_content().get_content()

    def clear(self) -> None:
        """Clear all accumulated content (thread-safe)."""
        self._note_write("clear")
        self._require_content().clear()

    def set_line(self, index: int, text: str) -> None:
        """Set the content of a specific line (thread-safe).

        Raises:
            ValueError: If ``text`` holds a newline (it's one line).
        """
        self._note_write("set_line")
        self._require_content().set_line(index, text)

    def __len__(self) -> int:
        """Return the number of chunks."""
        return len(self._require_content())

    def __bool__(self) -> bool:
        """Always True: a context is a handle, not a collection.

        Without this, truthiness would fall back to ``__len__`` — ``if ctx:``
        would be False for a fresh (empty) box and raise for a context
        without content.
        """
        return True

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
        self._note_write("append_rich")
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

        Raises:
            ValueError: If it renders to more than one line.
        """
        self._note_write("set_line_rich")
        self._ensure_ansi_format()
        self._require_content().set_line_rich(
            index, renderable, theme=theme or self._rich_theme
        )

    # -- Title control --------------------------------------------------------

    def set_title(self, text: str) -> None:
        """Set the thinking separator title."""
        self._note_write("set_title")
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
            The full content that was displayed. Finishing again (or after
            the session finished the box) returns it again, echoing nothing.

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

    def _cancel(
        self,
        add_to_history: bool = True,
        echo_to_console: bool | None = None,
    ) -> str:
        """Finish as cancelled: echo the content, then "Operation cancelled..."."""
        if self._finish is None:
            return ""
        return self._finish(
            add_to_history=add_to_history, echo_to_console=echo_to_console, cancelled=True
        )
