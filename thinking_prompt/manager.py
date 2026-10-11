"""
ThinkingBoxManager — the thinking boxes on screen.

Provides ManagedBox (one box's parts and state) and ThinkingBoxManager,
which creates boxes, lays them out, keeps the expand mode they share, and
ends them: off the screen, with their text echoed through the Display.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, Literal

from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.containers import Container
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D

from .frames import POLL_INTERVAL, FrameScheduler
from .layout import ThinkingHeader
from .streaming import StreamingContent
from .thinking_control import ThinkingBoxControl
from .types import DEFAULT_SPINNER_FRAMES, ContentCallback, ContentFormat, Overflow

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


@dataclass(eq=False)
class ManagedBox:
    """State for a single managed thinking box.

    ``owner`` is the asyncio task that created the box (None when it was
    created outside one): when a handler ends or is cancelled, the session
    finishes only the boxes that handler answers for (see
    ThinkingBoxManager.finish_owned_by). ``finished`` turns True when the
    manager ends the box. Boxes compare by identity.
    """

    control: ThinkingBoxControl
    header: ThinkingHeader | None
    container: Container
    order: int
    seq: int
    streaming_content: StreamingContent | None
    owner: asyncio.Task[Any] | None = None
    finished: bool = False


class ThinkingBoxManager:
    """
    The thinking boxes on screen: creates them, lays them out in order,
    keeps the expand mode they share, and ends them. Ending a box removes
    it and echoes its text through the Display: cut to the box's own
    lines on the console, in full in history.

    Thread-safe via RLock.

    Expansion is one mode shared by every box: the user's choice (Ctrl+T),
    forced on while the session is in full screen. The user's choice
    resets to collapsed when the last box finishes, so each new thinking
    phase starts collapsed.

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
        echo_thinking: bool = True,
        spinner_frames: tuple[str, ...] = DEFAULT_SPINNER_FRAMES,
        spinner_position: Literal["before", "after"] = "before",
    ) -> None:
        """
        Args:
            display: Where a finished box's text is echoed.
            default_max_lines: Collapsed lines for boxes that don't set any.
            default_style: Style class of the box text.
            expand_key: The key named in the overflow hint.
            frames: Asks for redraws (None: nothing asks).
            echo_thinking: Whether a finished box is printed to the console
                when the finish call doesn't say (AppInfo.echo_thinking).
            spinner_frames: The header spinner's frames (() for none).
            spinner_position: The spinner "before" or "after" the title.
        """
        self._display = display
        self._default_max_lines = default_max_lines
        self._default_style = default_style
        self._expand_key = expand_key
        self._frames = frames
        self._echo_thinking = echo_thinking
        self._spinner_frames = spinner_frames
        self._spinner_position: Literal["before", "after"] = spinner_position
        self._boxes: list[ManagedBox] = []  # in creation order
        self._seq_counter = 0
        self._expanded = False  # the user's choice (Ctrl+T)
        self._forced = False  # full screen: every box expanded
        self._lock = threading.RLock()

    def _box_expanded(self) -> bool:
        """The mode every box reads (plain reads: no lock needed)."""
        return self._forced or self._expanded

    def create_box(
        self,
        content_callback: ContentCallback | None = None,
        *,
        title: str | None = None,
        order: int = 0,
        max_lines: int | None = None,
        content_format: ContentFormat = "plain",
        overflow: Overflow = "tail",
    ) -> ManagedBox:
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
                max_collapsed_lines=effective_max_lines,
                style=self._default_style,
                expand_key=self._expand_key,
                overflow=overflow,
                expanded=self._box_expanded,
                on_draw=on_draw,
            )
            control.start(content_callback, content_format=content_format)

            header: ThinkingHeader | None = None
            if title is not None:
                header = ThinkingHeader(
                    text=title,
                    frames=self._spinner_frames,
                    position=self._spinner_position,
                    request_frame=frames.redraw_in if frames is not None else None,
                )

            seq = self._seq_counter
            self._seq_counter += 1

            box = ManagedBox(
                control=control,
                header=header,
                container=self._build_container(control, header, effective_max_lines),
                order=order,
                seq=seq,
                streaming_content=streaming_content,
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

    def get_sorted_boxes(self) -> list[ManagedBox]:
        """
        Get all boxes sorted by (order, seq).

        Returns:
            List of ManagedBox sorted by order then creation sequence.
        """
        with self._lock:
            return sorted(self._boxes, key=lambda b: (b.order, b.seq))

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
            return HSplit([b.container for b in sorted_boxes])

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

    def force_expanded(self, on: bool) -> None:
        """While on (full screen), every box is expanded, new ones too.
        Turning it off brings back the user's choice."""
        with self._lock:
            self._forced = on

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
            return any(box.control.can_toggle_expanded for box in self._boxes)

    # -- ending boxes ----------------------------------------------------------

    def finish(
        self,
        box: ManagedBox,
        *,
        add_to_history: bool = True,
        echo_to_console: bool | None = None,
    ) -> bool:
        """End ``box``: remove it from the screen and echo its text.

        Returns:
            False if the box had already ended (nothing is echoed again).
        """
        ended = self._finish(
            lambda b: b is box,
            add_to_history=add_to_history,
            echo_to_console=echo_to_console,
        )
        return bool(ended)

    def finish_all(
        self, *, add_to_history: bool = True, echo_to_console: bool | None = None
    ) -> list[ManagedBox]:
        """End every box (e.g. Ctrl+C at an idle prompt); return them."""
        return self._finish(
            lambda b: True, add_to_history=add_to_history, echo_to_console=echo_to_console
        )

    def finish_owned_by(
        self,
        task: asyncio.Task[Any] | None,
        *,
        add_to_history: bool = True,
        echo_to_console: bool | None = None,
    ) -> list[ManagedBox]:
        """End the boxes a handler answers for when it ends; return them.

        Those ``task`` created, those whose task has already ended (nobody
        else will finish them), and those with no known owner (created
        outside asyncio, e.g. from a thread). A live background task's box
        is left alone.
        """

        def owned(box: ManagedBox) -> bool:
            return box.owner is None or box.owner is task or box.owner.done()

        return self._finish(
            owned, add_to_history=add_to_history, echo_to_console=echo_to_console
        )

    def _finish(
        self,
        pick: Callable[[ManagedBox], bool],
        *,
        add_to_history: bool,
        echo_to_console: bool | None,
    ) -> list[ManagedBox]:
        """End the boxes ``pick`` selects, in creation order, and echo them.

        The echo runs after the lock is released: each box's text cut to
        its own lines at its overflow end on the console, in full in
        history (blank text echoes nothing).
        """
        with self._lock:
            ended = [box for box in self._boxes if pick(box)]
            finals: list[tuple[ManagedBox, str, ContentFormat]] = []
            for box in ended:
                self._boxes.remove(box)
                text, _, content_format = box.control.finish()
                box.finished = True
                finals.append((box, text, content_format))
            self._reset_mode_if_empty()
        echo = self._echo_thinking if echo_to_console is None else echo_to_console
        for box, text, content_format in finals:
            self._display.thinking(
                text,
                truncate_lines=box.control.max_collapsed_lines,
                add_to_history=add_to_history,
                echo_to_console=echo,
                content_format=content_format,
                overflow=box.control.overflow,
            )
        if ended:
            self.redraw()
        return ended

    def redraw(self) -> None:
        """Ask for a redraw (nothing asks without frames)."""
        if self._frames is not None:
            self._frames.redraw()

    @property
    def is_expanded(self) -> bool:
        """True if boxes are currently expanded (by the user, or full screen)."""
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
