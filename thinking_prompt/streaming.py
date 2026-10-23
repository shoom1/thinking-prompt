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

    The text is kept as lines, so ``set_line()`` replaces one line in place
    and ``len()`` is the number of lines.

    ``on_change`` is called after every change, from the writing thread
    (the thinking box's own content uses it to redraw).

    A box's own content (the one ``start_thinking()`` makes when given no
    content callback) is closed when the box finishes (``_close()``): later
    writes change nothing, so the box's text stays what it was. A buffer
    passed in as a callback is never closed by the box.
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        # The text is "\n".join(self._lines). The last entry is the line
        # still being written: "" after a trailing newline, and for no text.
        self._lines: list[str] = [""]
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
            first, *rest = chunk.split("\n")
            self._lines[-1] += first
            self._lines.extend(rest)
        self._changed()

    def get_content(self) -> str:
        """Get the accumulated content (thread-safe)."""
        with self._lock:
            return "\n".join(self._lines)

    def clear(self) -> None:
        """Clear all accumulated content (thread-safe)."""
        with self._lock:
            if self._closed:
                return
            self._lines = [""]
        self._changed()

    def _close(self) -> str:
        """Stop taking writes and return the final text.

        Under the lock, so a write racing this either lands before it (and
        is in the returned text) or changes nothing.
        """
        with self._lock:
            self._closed = True
            return "\n".join(self._lines)

    def _line_count(self) -> int:
        # An empty last line is the one still being written (after a
        # trailing newline, or when there is no text): not yet a line.
        count = len(self._lines)
        return count - 1 if self._lines[-1] == "" else count

    def __len__(self) -> int:
        """Return the number of lines (thread-safe).

        A trailing newline ends the last line rather than starting another:
        ``"a"`` and ``"a\\n"`` are one line, ``""`` is none.
        """
        # Locked: the count reads the list twice, and a write between the
        # reads could give a number the text never had.
        with self._lock:
            return self._line_count()

    def set_line(self, index: int, text: str) -> None:
        """Set the content of a specific line (thread-safe).

        Lines are numbered as ``len()`` counts them, so -1 is the last line.
        An index past the end adds empty lines up to it; a trailing newline
        stays trailing.

        Raises:
            ValueError: If ``text`` holds a newline: it would add lines,
                shifting every line after it.
            IndexError: If a negative index is before the first line
                (any negative index, when there is no text).
        """
        if "\n" in text:
            raise ValueError(f"set_line() takes one line of text, got {text!r}")
        with self._lock:
            if self._closed:
                return
            count = self._line_count()
            if index < -count:
                raise IndexError(f"line index {index} out of range for {count} line(s)")
            if index < 0:
                index += count
            if index < count:
                self._lines[index] = text
            else:
                added = [""] * (index - count) + [text]
                if self._lines == [""]:
                    self._lines = added
                else:
                    # Before the line still being written, so a trailing
                    # newline stays trailing.
                    self._lines[count:count] = added
        self._changed()

    def append_rich(
        self, renderable: Any, *, theme: Any = None, width: int | None = None
    ) -> None:
        """Append a Rich renderable or markup string, converted to ANSI.

        Text isn't wrapped (where it's shown wraps it); a Panel or Table is
        laid out ``width`` columns wide.

        Args:
            renderable: Rich markup string or Rich renderable object.
            theme: Optional Rich Theme for styling.
            width: Columns to lay a Panel or Table out in (None: the
                terminal's, as Rich finds it).
        """
        from .rich_utils import _renderable_to_ansi
        self.append(_renderable_to_ansi(renderable, theme=theme, width=width))

    def set_line_rich(
        self, index: int, renderable: Any, *, theme: Any = None, width: int | None = None
    ) -> None:
        """Set a line from a Rich renderable or markup string.

        Args:
            index: Line index (supports negative indices).
            renderable: Rich markup string or Rich renderable object.
            theme: Optional Rich Theme for styling.
            width: Columns to lay a renderable such as a Rule out in (None:
                the terminal's, as Rich finds it).

        Raises:
            ValueError: If it renders to more than one line (e.g. markup
                with a newline, or a Panel).
        """
        from .rich_utils import _renderable_to_ansi
        # The newline that ends the line isn't a second line.
        ansi = _renderable_to_ansi(renderable, theme=theme, width=width).rstrip("\n")
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
