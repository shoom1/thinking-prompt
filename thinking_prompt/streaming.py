"""
StreamingContent: thread-safe text for a thinking box.
"""
from __future__ import annotations

import threading
from typing import Any, Callable


class StreamingContent:
    """
    Thread-safe helper for streaming content to thinking box.

    This class provides a convenient way to accumulate content
    for the thinking box in a thread-safe manner.

    Example:
        content = StreamingContent()
        box = session.start_thinking(content.get_content)

        async for chunk in llm_stream():
            content.append(chunk)

        box.finish()

    ``on_change`` is called after every change, from the writing thread
    (the thinking box's own content uses it to redraw).

    A box's own content (the one ``start_thinking()`` makes when given no
    content callback) is closed when the box finishes (``_close()``): later
    writes change nothing, so the box's text stays what it was. A buffer
    passed in as a callback is never closed by the box.
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._chunks: list[str] = []
        self._lock = threading.Lock()
        self._closed = False
        self._on_change = on_change

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def append(self, chunk: str) -> None:
        """Append a chunk of content (thread-safe)."""
        with self._lock:
            if self._closed:
                return
            self._chunks.append(chunk)
        self._changed()

    def get_content(self) -> str:
        """Get the accumulated content (thread-safe)."""
        with self._lock:
            return "".join(self._chunks)

    def clear(self) -> None:
        """Clear all accumulated content (thread-safe)."""
        with self._lock:
            if self._closed:
                return
            self._chunks.clear()
        self._changed()

    def _close(self) -> str:
        """Stop taking writes and return the final text.

        Under the lock, so a write racing this either lands before it (and
        is in the returned text) or changes nothing.
        """
        with self._lock:
            self._closed = True
            return "".join(self._chunks)

    def __len__(self) -> int:
        """Return the number of chunks."""
        with self._lock:
            return len(self._chunks)

    def set_line(self, index: int, text: str) -> None:
        """Set the content of a specific line (thread-safe).

        Supports negative indices (-1 is last non-empty line).
        If index is beyond current line count, extends with empty lines.

        Raises:
            ValueError: If ``text`` holds a newline: it would add lines,
                shifting every line after it.
        """
        if "\n" in text:
            raise ValueError(f"set_line() takes one line of text, got {text!r}")
        with self._lock:
            if self._closed:
                return
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
                if index < 0:
                    # Still negative after normalization: out of range.
                    # Without this check the list assignment below would
                    # raise an IndexError with the normalized (confusing)
                    # index instead of the one the caller passed.
                    raise IndexError(
                        f"line index {index - len(lines)} out of range "
                        f"for {len(lines)} line(s)"
                    )

            # Extend if needed
            lines.extend([""] * (index + 1 - len(lines)))

            lines[index] = text

            self._chunks.clear()
            self._chunks.append("\n".join(lines) + ("\n" if has_trailing_newline else ""))
        self._changed()

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

        Raises:
            ValueError: If it renders to more than one line (e.g. markup
                with a newline, or a Panel).
        """
        from .rich_utils import _renderable_to_ansi
        ansi = _renderable_to_ansi(renderable, theme=theme)
        rows = ansi.count("\n") + 1
        if rows > 1:
            raise ValueError(
                f"set_line_rich() takes one line; {renderable!r} renders to {rows}"
            )
        self.set_line(index, ansi)

    @property
    def text(self) -> str:
        """Alias for get_content() for convenience."""
        return self.get_content()
