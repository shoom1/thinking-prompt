"""
ThinkingBoxManager — the thinking boxes on screen.

Creates ThinkingBox objects, lays them out, keeps the expand mode they
share, and ends them: off the screen, with their text echoed through the
Display.
"""
from __future__ import annotations

import asyncio
import threading
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, Literal

from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.containers import Container
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D

from .frames import POLL_INTERVAL, FrameScheduler
from .layout import ThinkingHeader
from .spinner import Spinner
from .streaming import StreamingContent
from .thinking_box import ThinkingBox
from .thinking_control import ThinkingBoxControl
from .types import ContentCallback, ContentFormat, Overflow

if TYPE_CHECKING:
    from .display import Display


def _terminal_width(default: int = 80) -> int:
    """Best-effort terminal width in columns.

    get_app() returns a dummy app (80 cols) outside a running
    application; any failure falls back to ``default``.
    """
    try:
        return get_app().output.get_size().columns
    except Exception:
        return default


def _current_task() -> asyncio.Task[Any] | None:
    """The running asyncio task, or None outside one (e.g. in a thread)."""
    try:
        return asyncio.current_task()
    except RuntimeError:  # no running event loop in this thread
        return None


class ThinkingBoxManager:
    """
    The thinking boxes on screen: creates them, lays them out in order,
    keeps the expand mode they share, and ends them. Ending a box removes
    it and echoes its text through the Display, cut to the box's own
    lines.

    Thread-safe via RLock.

    Expansion is one mode shared by every box: the user's choice (Ctrl+T).
    It resets to collapsed when the last box finishes, so each new
    thinking phase starts collapsed.

    With ``frames``, boxes ask for their own redraws: a write redraws now,
    a spinner asks for its next frame, and a box fed by a content callback
    is polled every ``POLL_INTERVAL`` seconds while it's drawn.
    """

    def __init__(
        self,
        display: Display,
        *,
        default_max_lines: int = 15,
        default_style: str = "class:thinking-box",
        expand_key: str = "c-t",
        frames: FrameScheduler | None = None,
        thinking_echo: bool = True,
        spinner: Spinner | None = Spinner.DOTS,
        spinner_position: Literal["before", "after"] = "before",
    ) -> None:
        """
        Args:
            display: Where a finished box's text is echoed.
            default_max_lines: Collapsed lines for boxes that don't set any.
            default_style: Style class of the box text.
            expand_key: The key named in the overflow hint.
            frames: Asks for redraws (None: nothing asks).
            thinking_echo: Whether a finished box is printed to the console
                when the finish call doesn't say (the session's thinking_echo).
            spinner: The header spinner (None for none).
            spinner_position: The spinner "before" or "after" the title.
        """
        self._display = display
        self._default_max_lines = default_max_lines
        self._default_style = default_style
        self._expand_key = expand_key
        self._frames = frames
        self._thinking_echo = thinking_echo
        self._spinner = spinner
        self._spinner_position: Literal["before", "after"] = spinner_position
        self._boxes: list[ThinkingBox] = []  # in creation order
        self._expanded = False  # the user's choice (Ctrl+T)
        self._lock = threading.RLock()

    def _box_expanded(self) -> bool:
        """The mode every box reads (plain reads: no lock needed)."""
        return self._expanded

    def create_box(
        self,
        content_callback: ContentCallback | None = None,
        *,
        title: str | None = None,
        order: int = 0,
        max_lines: int | None = None,
        content_format: ContentFormat = "plain",
        overflow: Overflow = "tail",
    ) -> ThinkingBox:
        """
        Create a box and show it.

        Args:
            content_callback: Returns the text to show; the box re-reads it
                while drawn. If None, the box gets a StreamingContent of its
                own to write to.
            title: Title for a header line (with the spinner) above the box.
                None: no header.
            order: Sort key (higher = closer to the prompt).
            max_lines: Max collapsed lines (default: the manager's).
            content_format: Content format ("plain" or "ansi").
            overflow: Which end of overflowing content stays visible:
                "tail" (newest lines) or "head" (first lines).

        Returns:
            The new box.
        """
        with self._lock:
            effective_max_lines = (
                max_lines if max_lines is not None else self._default_max_lines
            )

            frames = self._frames
            # Content written through the box's handle redraws on each
            # write; a caller's content callback can only be polled.
            streaming_content: StreamingContent | None = None
            on_draw: Callable[[], None] | None = None
            if content_callback is None:
                streaming_content = StreamingContent(
                    on_change=frames.redraw if frames is not None else None
                )
                content_callback = streaming_content.get_content
            elif frames is not None:
                on_draw = partial(frames.redraw_in, POLL_INTERVAL)

            # expand_key is forwarded so the truncation hint names the key
            # that actually toggles expansion.
            control = ThinkingBoxControl(
                content_callback,
                max_collapsed_lines=effective_max_lines,
                style=self._default_style,
                expand_key=self._expand_key,
                overflow=overflow,
                content_format=content_format,
                expanded=self._box_expanded,
                on_draw=on_draw,
            )

            header: ThinkingHeader | None = None
            if title is not None:
                header = ThinkingHeader(
                    text=title,
                    spinner=self._spinner,
                    position=self._spinner_position,
                    request_frame=frames.redraw_in if frames is not None else None,
                )

            box = ThinkingBox(
                self,
                content=streaming_content,
                control=control,
                header=header,
                container=self._build_container(control, header, effective_max_lines),
                order=order,
                owner=_current_task(),
            )
            self._boxes.append(box)
        self.redraw()
        return box

    def _build_container(
        self,
        control: ThinkingBoxControl,
        header: ThinkingHeader | None,
        max_lines: int,
    ) -> Container:
        """Build the layout container for a single box."""

        def get_height() -> D:
            # Wrap-count at the real terminal width — a hardcoded 80
            # clips wrapped content on narrow terminals.
            rows = max(1, control.get_line_count(_terminal_width()))
            if control.is_expanded:
                # Fit the content; with no max, the layout squeezes the box
                # on a short screen, and the control then keeps the
                # overflow end in the rows it gets (nothing scrolls).
                return D(min=1, preferred=rows)
            return D(min=1, max=max_lines, preferred=min(rows, max_lines))

        content_window = Window(
            content=control,
            height=get_height,
            wrap_lines=True,
            dont_extend_height=True,
        )

        if header is not None:
            captured_header: ThinkingHeader = header

            def _get_header_text() -> Any:
                # Size the separator to the terminal so it spans wide
                # screens and doesn't overflow narrow ones.
                return captured_header.get_formatted_text(_terminal_width())

            header_control = FormattedTextControl(text=_get_header_text)
            header_window = Window(
                content=header_control,
                height=D.exact(1),
            )
            return HSplit([header_window, content_window])

        return content_window

    def _reset_mode_if_empty(self) -> None:
        """The next thinking phase starts collapsed (caller holds the lock)."""
        if not self._boxes:
            self._expanded = False

    def get_sorted_boxes(self) -> list[ThinkingBox]:
        """
        Get all boxes sorted by order, boxes of the same order in the order
        they were made (the sort is stable, and boxes are kept in that order).

        Returns:
            List of ThinkingBox sorted by order.
        """
        with self._lock:
            return sorted(self._boxes, key=lambda b: b._order)

    def get_container(self) -> Container:
        """
        Get a container representing all sorted boxes.

        Returns:
            HSplit of sorted box containers, or Window(height=0) if empty.
        """
        with self._lock:
            sorted_boxes = self.get_sorted_boxes()
            if not sorted_boxes:
                return Window(height=0)
            return HSplit([b._container for b in sorted_boxes])

    def toggle_all(self) -> None:
        """Toggle the user's expand/collapse choice for all boxes."""
        with self._lock:
            self._expanded = not self._expanded

    def expand_all(self) -> None:
        """Expand all boxes (the user's choice)."""
        with self._lock:
            self._expanded = True

    def collapse_all(self) -> None:
        """Collapse all boxes (the user's choice)."""
        with self._lock:
            self._expanded = False

    def can_toggle(self) -> bool:
        """
        Check if toggle is available.

        Returns True when there is a box, and the boxes are expanded or any
        of them overflows (shows the expand hint).
        """
        with self._lock:
            if not self._boxes:
                return False
            if self._expanded:
                return True
            return any(box._control.can_toggle_expanded for box in self._boxes)

    # -- ending boxes ----------------------------------------------------------

    def finish(
        self,
        box: ThinkingBox,
        *,
        echo: bool | None = None,
    ) -> bool:
        """End ``box``: remove it from the screen and echo its text.

        Returns:
            False if the box had already ended (nothing is echoed again).
        """
        ended = self._finish(lambda b: b is box, echo=echo)
        return bool(ended)

    def finish_owned_by(
        self,
        task: asyncio.Task[Any] | None,
        *,
        echo: bool | None = None,
    ) -> list[ThinkingBox]:
        """End the boxes nobody but ``task`` would end; return them.

        Those ``task`` created, those whose task has already ended, and those
        with no known owner (created outside asyncio, e.g. from a thread). A
        live task's box is left to that task. A handler's cleanup passes the
        handler's task; idle Ctrl+C and the end of run_async() pass the
        app's task (the one running run_async()).
        """

        def owned(box: ThinkingBox) -> bool:
            return box._owner is None or box._owner is task or box._owner.done()

        return self._finish(owned, echo=echo)

    def finish_when_owners_end(self) -> None:
        """End each open box when its task ends, unless the task ends it
        first. For the boxes left open once the session's UI is gone:
        cancelling a task doesn't end a box it opened with start_thinking(),
        and nothing else will look at the box again."""
        with self._lock:
            owners = {box._owner for box in self._boxes if box._owner is not None}
        for owner in owners:
            owner.add_done_callback(self.finish_owned_by)

    def _finish(
        self,
        pick: Callable[[ThinkingBox], bool],
        *,
        echo: bool | None,
    ) -> list[ThinkingBox]:
        """End the boxes ``pick`` selects, in creation order, and echo them.

        The echo runs after the lock is released: each box's text cut to
        its own lines at its overflow end (blank text echoes nothing),
        printed and kept for repaints. Without the echo the text is
        dropped.
        """
        with self._lock:
            ended = [box for box in self._boxes if pick(box)]
            for box in ended:
                self._boxes.remove(box)
                box._close()
            self._reset_mode_if_empty()
        echoed = self._thinking_echo if echo is None else echo
        for box in ended if echoed else []:
            control = box._control
            self._display.thinking(
                box.text,
                truncate_lines=control.max_collapsed_lines,
                content_format=control.content_format,
                overflow=control.overflow,
            )
        if ended:
            self.redraw()
        return ended

    def redraw(self) -> None:
        """Ask for a redraw (nothing asks without frames)."""
        if self._frames is not None:
            self._frames.redraw()

    @property
    def rich_theme(self) -> Any:
        """The Display's current Rich theme: the default for boxes' rich writes."""
        return self._display.rich_theme

    @property
    def output_width(self) -> int | None:
        """The Display's output width: what boxes' rich writes lay a Panel
        or Table out at."""
        return self._display.width

    @property
    def is_expanded(self) -> bool:
        """True if boxes are currently expanded."""
        with self._lock:
            return self._box_expanded()

    @property
    def has_active_boxes(self) -> bool:
        """True if there are any active boxes."""
        with self._lock:
            return bool(self._boxes)

    @property
    def active_count(self) -> int:
        """Number of active boxes."""
        with self._lock:
            return len(self._boxes)
