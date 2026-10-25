"""
ThinkingBox: one thinking box, and the handle your code holds for it.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from prompt_toolkit.layout.containers import Container

    from .layout import ThinkingHeader
    from .manager import ThinkingBoxManager
    from .streaming import StreamingContent
    from .thinking_control import ThinkingBoxControl

logger = logging.getLogger(__name__)


def _no_content(what: str) -> TypeError:
    return TypeError(
        f"{what}(): this box shows a content callback's text; it has no content of its own"
    )


class ThinkingBox:
    """One thinking box: what ``start_thinking()`` returns and ``thinking()`` yields.

    Write to it (``append``, ``set_line``, the ``_rich`` variants,
    ``clear``), retitle it, and finish it. Writes, the title and reads work
    from any thread; ``finish()`` runs on the event loop (it prints the
    echo; see the README's "Threads"). A box started with a content
    callback (``start_thinking(callback)``) shows that callback's text: you
    can read it (``text``), but writing raises TypeError.

    Once the box is finished (by ``finish()``, the end of a ``thinking()``
    block, or the session: when its handler ends, at Ctrl+C, or on exit; see
    the README's "When a Box Ends"), ``is_finished`` is True and its text is
    final: writes are dropped (the first logs a warning), and ``finish()``
    returns the same text again without echoing it twice.

    ThinkingBoxManager.create_box() makes boxes; the constructor and the
    underscore attributes are internal.
    """

    def __init__(
        self,
        manager: ThinkingBoxManager,
        *,
        content: StreamingContent | None,
        control: ThinkingBoxControl,
        header: ThinkingHeader | None,
        container: Container,
        order: int,
        owner: asyncio.Task[Any] | None,
    ) -> None:
        self._manager = manager
        self._content = content  # None: the box shows a content callback's text
        self._control = control
        self._header = header
        self._container = container
        self._order = order
        self._owner = owner
        self._final_text = ""
        self._finished = False
        self._warn_lock = threading.Lock()
        self._warned = False

    # -- state -----------------------------------------------------------------

    @property
    def is_finished(self) -> bool:
        """True once the box is finished and no longer shown."""
        return self._finished

    def _close(self) -> None:
        """Freeze the final text and mark the box finished.

        ThinkingBoxManager calls this once, under its lock, when it ends
        the box. Closing the content means a write racing this either
        lands in the final text or is dropped.
        """
        if self._content is not None:
            self._final_text = self._content._close()
        else:
            self._final_text = self._control.content
        self._finished = True

    def _writable(self, what: str) -> StreamingContent | None:
        """The content ``what`` writes to; None once the box is finished.

        Raises:
            TypeError: The box shows a content callback's text.
        """
        if self._content is None:
            raise _no_content(what)
        if self._finished:
            self._warn_finished(what)
            return None
        return self._content

    def _warn_finished(self, what: str) -> None:
        """Warn (once per box) that a write to a finished box was dropped."""
        with self._warn_lock:
            if self._warned:
                return
            self._warned = True
        logger.warning(
            "thinking box already finished: %s() and later writes have no effect", what
        )

    # -- content ---------------------------------------------------------------

    def append(self, chunk: str) -> None:
        """Append a chunk of text (thread-safe)."""
        content = self._writable("append")
        if content is not None:
            content.append(chunk)

    def set_line(self, index: int, text: str) -> None:
        """Replace one line (thread-safe).

        Lines are numbered as ``len()`` counts them, so -1 is the last line;
        indices past the end add empty lines up to it.

        Raises:
            ValueError: If ``text`` holds a newline (it's one line).
            IndexError: If a negative index is out of range (any negative
                index, on an empty box).
        """
        content = self._writable("set_line")
        if content is not None:
            content.set_line(index, text)

    def clear(self) -> None:
        """Remove all text (thread-safe)."""
        content = self._writable("clear")
        if content is not None:
            content.clear()

    def append_rich(self, renderable: Any, *, theme: Any = None) -> None:
        """Append a Rich renderable or markup string; the box switches to ANSI
        (thread-safe).

        Text keeps its whitespace and wraps in the box like plain text; a
        Panel or Table is laid out at the session's width.

        Args:
            renderable: Rich markup string or Rich renderable object.
            theme: Rich Theme for this write (default: the session's
                current theme).
        """
        content = self._writable("append_rich")
        if content is not None:
            self._control.set_content_format("ansi")
            content.append_rich(
                renderable,
                theme=theme or self._manager.rich_theme,
                width=self._manager.output_width,
            )

    def set_line_rich(self, index: int, renderable: Any, *, theme: Any = None) -> None:
        """Replace one line with a Rich renderable; the box switches to ANSI
        (thread-safe).

        Args:
            index: Line index (negative counts from the end).
            renderable: Rich markup string or Rich renderable object.
            theme: Rich Theme for this write (default: the session's
                current theme).

        Raises:
            ValueError: If it renders to more than one line.
        """
        content = self._writable("set_line_rich")
        if content is not None:
            self._control.set_content_format("ansi")
            content.set_line_rich(
                index,
                renderable,
                theme=theme or self._manager.rich_theme,
                width=self._manager.output_width,
            )

    @property
    def text(self) -> str:
        """What the box shows; once finished, its final text. Read-only:
        write with ``append``, ``set_line`` and ``clear``.

        For a box fed by a content callback: the callback's text ("" if it
        raises; logged once).
        """
        if self._finished:
            return self._final_text
        if self._content is not None:
            return self._content.get_content()
        return self._control.content

    def __len__(self) -> int:
        """Number of lines (thread-safe).

        A trailing newline ends the last line rather than starting another:
        ``"a"`` and ``"a\\n"`` are one line, ``""`` is none.

        Raises:
            TypeError: The box shows a content callback's text.
        """
        if self._content is None:
            raise _no_content("len")
        return len(self._content)

    def __bool__(self) -> bool:
        """Always True: a box is a handle, not a collection.

        Without this, truthiness would fall back to ``__len__``: ``if box:``
        would be False for a fresh (empty) box and raise for a box fed by a
        content callback.
        """
        return True

    # -- title -----------------------------------------------------------------

    @property
    def title(self) -> str:
        """The title on the box's header line ("" for a box without one)."""
        return self._header.text if self._header is not None else ""

    def set_title(self, text: str) -> None:
        """Set the title on the box's header line (thread-safe)."""
        if self._finished:
            self._warn_finished("set_title")
            return
        if self._header is not None:
            self._header.text = text
            self._manager.redraw()

    # -- finishing -------------------------------------------------------------

    def finish(self, echo: bool | None = None) -> str:
        """Finish the box: remove it from the screen and echo its text. Call
        it on the event loop: the echo prints above the UI from there.

        Args:
            echo: If True, print the text to the console (and keep
                it for repaints); if False, drop it. None follows the
                session's ``thinking_echo``.

        Returns:
            The box's final text. Finishing again (or after the session
            finished the box) returns it again and echoes nothing.
        """
        self._manager.finish(self, echo=echo)
        return self._final_text
