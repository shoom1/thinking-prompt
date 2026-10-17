"""
On-demand redraws.

The screen is redrawn when something changes or an animation asks for its
next frame, never on a fixed timer: an idle prompt isn't redrawn at all.
"""
from __future__ import annotations

import asyncio
from typing import Callable

# How often text that can't say when it changes (a content callback, a
# callable prompt message or status) is re-read while it's drawn.
POLL_INTERVAL = 0.1


class FrameScheduler:
    """Asks the app for redraws: now, or in a while.

    Writes call ``redraw()``. Whatever changes with time (a spinner, a box
    polling its content callback) calls ``redraw_in()`` each time it's
    drawn. One timer is kept, at the earliest time asked for, so every
    animation shares each redraw, and nothing ticks once nothing animated
    is drawn.
    """

    def __init__(self, invalidate: Callable[[], None]) -> None:
        """
        Args:
            invalidate: Redraws the app soon; thread-safe, and calls made
                before the redraw merge into it (``Application.invalidate``).
        """
        self._invalidate = invalidate
        self._handle: asyncio.TimerHandle | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def redraw(self) -> None:
        """Redraw as soon as possible.

        Thread-safe when ``invalidate`` is: ``Application.invalidate`` hands
        the redraw to the event loop with ``call_soon_threadsafe``.
        """
        self._invalidate()

    def redraw_in(self, delay: float) -> None:
        """Redraw in ``delay`` seconds, unless a redraw is already due sooner.

        Called while drawing, on the event loop; outside one it's ignored.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        when = loop.time() + max(0.0, delay)
        if self._handle is not None:
            # A redraw already due by then covers this request: whoever asked
            # is drawn in it and asks again from there. A timer on another
            # (finished) loop will never fire, though: replace it.
            if self._loop is loop and self._handle.when() <= when:
                return
            self._handle.cancel()
        self._loop = loop
        self._handle = loop.call_at(when, self._fire)

    def cancel(self) -> None:
        """Drop the pending redraw (e.g. when the app exits)."""
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _fire(self) -> None:
        self._handle = None
        self._invalidate()
