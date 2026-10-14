"""
A repaint after the terminal gets smaller.

When its window gets narrower, a terminal re-wraps every line now too long
for it, the live UI's full-width rows (separators, the status bar, box
borders) included; when it gets shorter than the UI, the UI's top scrolls
into scrollback. prompt_toolkit erases its last frame by moving the cursor
up the rows it drew above it, so either way part of that frame stays
behind, and comes back as the window grows. Once resizing stops, the
session repaints: it clears the screen and scrollback and prints the
transcript again.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from prompt_toolkit.data_structures import Size

# Seconds the terminal keeps its size before the repaint: a window being
# dragged changes size many times a second.
REPAINT_DELAY = 0.25


class ShrinkRepaint:
    """Calls ``repaint`` once the terminal has kept its size for ``delay``
    seconds after getting narrower or shorter. ``seen()`` is told the
    terminal's size at each draw."""

    def __init__(self, repaint: Callable[[], None], delay: float = REPAINT_DELAY) -> None:
        self._repaint = repaint
        self._delay = delay
        self._size: Size | None = None
        self._shrunk = False
        self._handle: asyncio.TimerHandle | None = None

    def seen(self, size: Size) -> None:
        """The terminal is ``size`` now. Called on the event loop."""
        last, self._size = self._size, size
        if last is None or size == last:
            return
        if size.columns < last.columns or size.rows < last.rows:
            self._shrunk = True
        if self._shrunk:
            # Every change restarts the wait, growing too: the rows left
            # behind are repainted once, after the last.
            if self._handle is not None:
                self._handle.cancel()
            self._handle = asyncio.get_running_loop().call_later(self._delay, self._fire)

    def cancel(self) -> None:
        """Drop the repaint waiting, if any, and the size seen: the next
        size is a first sighting (a new run of the app starts with a fresh
        frame)."""
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None
        self._shrunk = False
        self._size = None

    def _fire(self) -> None:
        self._handle = None
        self._shrunk = False
        self._repaint()
