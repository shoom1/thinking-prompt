"""
Scrolling for dialogs, box and inline.

AtMost caps how tall a container gets. ScrollRegion scrolls what doesn't
fit, a dialog's whole body: it follows the cursor, and keys scroll it past
the cursor to read what's around it (enclosing_region(), toward()).
"""
from __future__ import annotations

from typing import Callable, Optional, Union

from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import Container, ScrollablePane, ScrollOffsets, Window
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout, walk
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


def enclosing_region(layout: Layout, container: Container) -> ScrollRegion | None:
    """The ScrollRegion ``container`` is drawn in, if any (as of the last
    render, which sets the layout's parent links)."""
    parent = layout.get_parent(container)
    while parent is not None:
        if isinstance(parent, ScrollRegion):
            return parent
        parent = layout.get_parent(parent)
    return None


class ScrollRegion(ScrollablePane):
    """Scrolls ``content`` within the rows it's given.

    It follows the cursor while a window inside has focus, as ScrollablePane
    does, with no scroll offsets (squeezed to one row, it shows the cursor
    row itself), and it goes back to its top when the cursor arrives at the
    first stop (``at_top()``) or its rows change while there, so rows above
    that stop show again. Keys scroll it past the cursor, to read what's
    around it: scroll(), page(), toward(). It stays so until the cursor
    moves, or a key that doesn't scroll it brings the cursor back into view
    (settle(), after each key). With ``scrollbar``, a scrollbar shows while the content overflows.
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
        # Scrolled by keys, past the cursor: the cursor isn't followed. And
        # whether the key being handled scrolled it (settle()).
        self._manual = False
        self._scrolled = False
        following = Condition(lambda: not self._manual)
        super().__init__(
            content,
            scroll_offsets=ScrollOffsets(top=0, bottom=0),
            keep_cursor_visible=following,
            keep_focused_window_visible=following,
            show_scrollbar=Condition(lambda: self._scrollbar and self._overflowing),
        )
        self._at_top = at_top
        # The window focused at the last render.
        self._focused: Window | None = None
        # As last drawn: the content's rows, the rows shown, and where each
        # window inside starts and how tall it is, in content rows.
        self._content_rows = 0
        self._visible_rows = 0
        self._windows: dict[Window, tuple[int, int]] = {}

    @property
    def overflows(self) -> bool:
        """True if the content didn't fit at the last render."""
        return self._overflowing

    def settle(self) -> None:
        """After a key: unless it scrolled the region, follow the cursor
        again, back in view at the next draw."""
        if not self._scrolled:
            self._manual = False
        self._scrolled = False

    def scroll(self, lines: int) -> None:
        """Scroll ``lines`` down (up if negative), within the content, past
        the cursor."""
        self._manual = True
        self._scrolled = True
        last = max(0, self._content_rows - self._visible_rows)
        self.vertical_scroll = max(0, min(last, self.vertical_scroll + lines))

    def toward(self, current: Container, target: Container | None, step: int) -> bool:
        """Scroll one line for ↑ (``step`` -1) or ↓ (1) from ``current``:
        back toward ``current`` while keys have scrolled it out of view that
        way; else toward ``target``, the stop the key moves to, while moving
        there would skip rows (it's further than the rows shown), so what's
        between shows on the way; with no stop that way, toward the
        content's edge that way (there already, nothing). False once the
        cursor can go: following it then shows everything between."""
        top = self._view_top(current)
        bottom = top + self._visible_rows
        here = self._span(current)
        if self._manual and here is not None:
            start, rows = here
            if (start < top) if step < 0 else (start + rows > bottom):
                self.vertical_scroll = top
                self.scroll(step)
                return True
        if target is None:
            if (top > 0) if step < 0 else (bottom < self._content_rows):
                self.vertical_scroll = top
                self.scroll(step)
            else:
                # At the edge already: the key does nothing, and leaves a
                # view scrolled there where it is (settle()).
                self._scrolled = True
            return True
        where = self._span(target)
        if where is None:
            return False
        start, rows = where
        if start + rows - bottom > self._visible_rows:
            lines = 1
        elif top - start > self._visible_rows:
            lines = -1
        else:
            return False
        self.vertical_scroll = top
        self.scroll(lines)
        return True

    def _view_top(self, current: Container) -> int:
        """The first row shown, once the next draw follows the cursor to
        ``current`` (keys can come faster than draws)."""
        top = self.vertical_scroll
        where = self._span(current)
        if not self._manual and where is not None:
            start, rows = where
            top = max(min(top, start), start + rows - self._visible_rows)
        return max(0, min(top, self._content_rows - self._visible_rows))

    def _span(self, container: Container) -> tuple[int, int] | None:
        """Where ``container`` was last drawn, in content rows: its first row
        and how many, across the windows in it (a stop can be a container,
        such as a text field's, which swaps its row for an edit row). None
        if it wasn't drawn."""
        drawn = [
            self._windows[w] for w in walk(container)
            if isinstance(w, Window) and w in self._windows
        ]
        if not drawn:
            return None
        start = min(first for first, _ in drawn)
        return start, max(first + rows for first, rows in drawn) - start

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
        # On arriving at the first stop, and when the rows change while
        # there (a resize: rows the pane scrolled off may fit again). Not on
        # every redraw: while the cursor stays there, a tall stop such as a
        # text field scrolls with its own cursor. The pane scrolls down from
        # the top only if the first stop wouldn't fit.
        arrived = focused is not self._focused
        resized = write_position.height != self._visible_rows
        if arrived:
            self._manual = False  # the cursor moved: follow it
        if (arrived or resized) and self._at_top():
            self.vertical_scroll = 0
        self._focused = focused
        self._measure(write_position)
        # ScrollablePane only clamps its scroll around a followed window:
        # nothing else would clamp it while scrolled by keys.
        last = max(0, self._content_rows - self._visible_rows)
        self.vertical_scroll = max(0, min(last, self.vertical_scroll))
        super().write_to_screen(
            screen, mouse_handlers, write_position, parent_style, erase_bg, z_index
        )
        # Where each window inside was drawn, in content rows (ScrollablePane
        # copies every one's position, out of view too).
        self._windows = {}
        for window in walk(self.content):
            if isinstance(window, Window):
                where = screen.visible_windows_to_write_positions.get(window)
                if where is not None:
                    start = where.ypos - write_position.ypos + self.vertical_scroll
                    self._windows[window] = (start, where.height)

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
