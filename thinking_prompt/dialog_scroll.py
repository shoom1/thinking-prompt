"""
Scrolling for dialogs, box and inline.

AtMost caps how tall a container gets. ScrollRegion scrolls what doesn't
fit: it follows the cursor while a window inside it has focus (settings
rows, lists, actions), and otherwise scrolls by keys (a text body).
"""
from __future__ import annotations

from typing import Callable, Optional, Union

from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import Container, ScrollablePane, ScrollOffsets, Window
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import walk
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition

# Rows a dialog leaves free: the prompt, its two separators and the status bar.
TERMINAL_BUFFER_ROWS = 4

# A cap on rows: a number, a function of the width, or None for no cap.
Cap = Union[int, Callable[[int], Optional[int]], None]


def dialog_cap(max_height: int | None, terminal_rows: int) -> int:
    """The most rows a dialog may take: the terminal's rows less
    TERMINAL_BUFFER_ROWS, and ``max_height`` if set. At least 1."""
    rows = terminal_rows - TERMINAL_BUFFER_ROWS
    if max_height is not None:
        rows = min(rows, max_height)
    return max(1, rows)


def terminal_rows() -> int:
    """The running app's terminal height."""
    return get_app().output.get_size().rows


def focusable_windows(container: Container) -> list[Container]:
    """The windows under ``container`` that can take focus, top to bottom."""
    return [
        c for c in walk(container, skip_hidden=True)
        if isinstance(c, Window) and c.content.is_focusable()
    ]


class AtMost(Container):
    """``content`` no taller than it prefers, and than ``cap`` if given.

    ``cap`` is a number of rows, or a function of the width giving one (or
    None for no cap). ScrollablePane alone either prefers its content's full
    height or, given a height, prefers none at all.
    """

    def __init__(self, content: Container, cap: Cap = None) -> None:
        self.content = content
        self.cap = cap

    def reset(self) -> None:
        self.content.reset()

    def preferred_width(self, max_available_width: int) -> Dimension:
        return self.content.preferred_width(max_available_width)

    def preferred_height(self, width: int, max_available_height: int) -> Dimension:
        wanted = self.content.preferred_height(width, max_available_height)
        cap = self.cap(width) if callable(self.cap) else self.cap
        # max is capped at the capped preferred (not the cap): otherwise
        # HSplit would offer this container spare layout height, and it
        # would pad with blank rows up to the cap instead of its content.
        limit = wanted.preferred if cap is None else min(wanted.preferred, cap)
        return Dimension(min=min(wanted.min, limit), max=limit, preferred=limit)

    def write_to_screen(
        self,
        screen: Screen,
        mouse_handlers: MouseHandlers,
        write_position: WritePosition,
        parent_style: str,
        erase_bg: bool,
        z_index: int | None,
    ) -> None:
        self.content.write_to_screen(
            screen, mouse_handlers, write_position, parent_style, erase_bg, z_index
        )

    def get_children(self) -> list[Container]:
        return [self.content]


class ScrollRegion(ScrollablePane):
    """Scrolls ``content`` within the rows it's given.

    While a window inside has focus it follows the cursor, as ScrollablePane
    does, with no scroll offsets (squeezed to one row, it shows the cursor
    row itself), and it goes back to its top when the cursor arrives at the
    first stop (``at_top()``), so rows above that stop show again. With
    nothing inside focused (a text body) it scrolls by keys: scroll() and
    page(). With ``scrollbar``, a scrollbar shows while the content overflows.
    """

    def __init__(
        self,
        content: Container,
        at_top: Callable[[], bool] = lambda: False,
        *,
        scrollbar: bool = False,
    ) -> None:
        self._scrollbar = scrollbar
        self._overflowing = False
        super().__init__(
            content,
            scroll_offsets=ScrollOffsets(top=0, bottom=0),
            show_scrollbar=Condition(lambda: self._scrollbar and self._overflowing),
        )
        self._at_top = at_top
        # The window focused at the last render.
        self._focused: Window | None = None
        # As last drawn: the content's rows, and the rows shown.
        self._content_rows = 0
        self._visible_rows = 0

    @property
    def overflows(self) -> bool:
        """True if the content didn't fit at the last render."""
        return self._overflowing

    def scroll(self, lines: int) -> None:
        """Scroll ``lines`` down (up if negative), within the content."""
        last = max(0, self._content_rows - self._visible_rows)
        self.vertical_scroll = max(0, min(last, self.vertical_scroll + lines))

    def page(self, pages: int) -> None:
        """Scroll ``pages`` pages down (up if negative); a page is the
        visible rows less one."""
        self.scroll(pages * max(1, self._visible_rows - 1))

    def preferred_height(self, width: int, max_available_height: int) -> Dimension:
        wanted = super().preferred_height(width, max_available_height)
        # At least one row: squeezed by a short terminal, the region still
        # shows the cursor row (no scroll offsets) instead of vanishing.
        return Dimension(min=min(1, wanted.preferred), preferred=wanted.preferred)

    def write_to_screen(
        self,
        screen: Screen,
        mouse_handlers: MouseHandlers,
        write_position: WritePosition,
        parent_style: str,
        erase_bg: bool,
        z_index: int | None,
    ) -> None:
        focused = get_app().layout.current_window
        # Only on arriving at the first stop (or opening on it): while the
        # cursor stays there, a tall stop such as a text field scrolls with
        # its own cursor. The pane scrolls down from the top only if the
        # first stop wouldn't fit.
        if focused is not self._focused and self._at_top():
            self.vertical_scroll = 0
        self._focused = focused
        self._measure(write_position)
        # ScrollablePane only clamps its scroll around a focused window:
        # nothing else would clamp a text body's.
        self.scroll(0)
        super().write_to_screen(
            screen, mouse_handlers, write_position, parent_style, erase_bg, z_index
        )

    def _measure(self, write_position: WritePosition) -> None:
        """Record the content's rows and the rows shown, for scroll() and the scrollbar."""
        width = write_position.width
        self._visible_rows = write_position.height
        rows = self.content.preferred_height(width, self.max_available_height).preferred
        overflowing = rows > self._visible_rows
        if overflowing != self._overflowing:
            # What depends on overflow is sized before the region draws (the
            # inline hint, the box scrollbar's column), so the next render
            # picks it up.
            get_app().invalidate()
        self._overflowing = overflowing
        if self._scrollbar and self._overflowing:
            # The scrollbar takes a column, so the content may wrap to more rows.
            rows = self.content.preferred_height(width - 1, self.max_available_height).preferred
        self._content_rows = min(rows, self.max_available_height)
