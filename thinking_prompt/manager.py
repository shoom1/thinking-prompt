"""
ThinkingBoxManager — manages a collection of thinking boxes.

Provides ManagedBox (dataclass holding one box's state) and
ThinkingBoxManager (collection manager with thread-safe operations).
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.containers import Container
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D

from .frames import POLL_INTERVAL, FrameScheduler
from .layout import ThinkingHeader
from .thinking import ThinkingBoxControl
from .types import ContentFormat, Overflow, StreamingContent


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


@dataclass
class ManagedBox:
    """State for a single managed thinking box.

    ``owner`` is the asyncio task that created the box (None when it was
    created outside one): when a handler ends or is cancelled, the session
    finishes only the boxes that handler answers for.
    """

    box_id: str
    control: ThinkingBoxControl
    header: ThinkingHeader | None
    container: Container
    order: int
    seq: int
    streaming_content: StreamingContent | None
    owner: asyncio.Task[Any] | None = None


class ThinkingBoxManager:
    """
    Manages a collection of thinking boxes.

    Thread-safe via RLock. Supports creating, removing, sorting,
    and bulk expand/collapse of boxes.

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
        default_max_lines: int = 15,
        default_style: str = "class:thinking-box",
        expand_key: str = "c-t",
        frames: FrameScheduler | None = None,
    ) -> None:
        self._default_max_lines = default_max_lines
        self._default_style = default_style
        self._expand_key = expand_key
        self._frames = frames
        self._boxes: dict[str, ManagedBox] = {}
        self._seq_counter = 0
        self._auto_id_counter = 0
        self._expanded = False  # the user's choice (Ctrl+T)
        self._forced = False  # full screen: every box expanded
        self._lock = threading.RLock()

    def _box_expanded(self) -> bool:
        """The mode every box reads (plain reads: no lock needed)."""
        return self._forced or self._expanded

    def create_box(
        self,
        content_callback: Callable[[], str] | None = None,
        *,
        title: str | None = None,
        order: int = 0,
        max_lines: int | None = None,
        content_format: ContentFormat = "plain",
        box_id: str | None = None,
        overflow: Overflow = "tail",
    ) -> ManagedBox:
        """
        Create a new managed thinking box.

        Args:
            content_callback: Callback returning content string.
                If None, a StreamingContent is created internally.
            title: Optional title for a ThinkingHeader above the box.
            order: Sort key (higher = closer to prompt).
            max_lines: Max collapsed lines (overrides default).
            content_format: Content format ("plain" or "ansi").
            box_id: Custom box ID. Auto-assigned if not provided.
            overflow: Which end of overflowing content stays visible:
                "tail" (newest lines) or "head" (first lines).

        Returns:
            The newly created ManagedBox.
        """
        with self._lock:
            # Assign ID
            if box_id is None:
                box_id = f"box-{self._auto_id_counter}"
                self._auto_id_counter += 1

            # Determine max lines
            effective_max_lines = max_lines if max_lines is not None else self._default_max_lines

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

            # Create control. expand_key is forwarded so the truncation
            # hint names the key that actually toggles expansion.
            control = ThinkingBoxControl(
                max_collapsed_lines=effective_max_lines,
                style=self._default_style,
                expand_key=self._expand_key,
                overflow=overflow,
                expanded=self._box_expanded,
                on_draw=on_draw,
            )

            # Start the control
            control.start(content_callback, content_format=content_format)

            # Create header if title provided
            header: ThinkingHeader | None = None
            if title is not None:
                header = ThinkingHeader(
                    text=title,
                    request_frame=frames.redraw_in if frames is not None else None,
                )

            # Assign sequence number
            seq = self._seq_counter
            self._seq_counter += 1

            # Build container
            container = self._build_container(control, header, effective_max_lines)

            box = ManagedBox(
                box_id=box_id,
                control=control,
                header=header,
                container=container,
                order=order,
                seq=seq,
                streaming_content=streaming_content,
                owner=_current_task(),
            )

            self._boxes[box_id] = box
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

    def remove_box(self, box_id: str) -> tuple[str, bool, ContentFormat]:
        """
        Remove a box and return its final state.

        Args:
            box_id: The ID of the box to remove.

        Returns:
            Tuple of (content, was_expanded, content_format).
            Returns ("", False, "plain") if box_id not found.
        """
        with self._lock:
            box = self._boxes.pop(box_id, None)
            if box is None:
                return ("", False, "plain")
            result = box.control.finish()
            self._reset_mode_if_empty()
            return result

    def _reset_mode_if_empty(self) -> None:
        """The next thinking phase starts collapsed (caller holds the lock)."""
        if not self._boxes:
            self._expanded = False

    def has_box(self, box_id: str) -> bool:
        """True while the box is active (not yet finished)."""
        with self._lock:
            return box_id in self._boxes

    def get_sorted_boxes(self) -> list[ManagedBox]:
        """
        Get all boxes sorted by (order, seq).

        Returns:
            List of ManagedBox sorted by order then creation sequence.
        """
        with self._lock:
            return sorted(self._boxes.values(), key=lambda b: (b.order, b.seq))

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
            return any(box.control.can_toggle_expanded for box in self._boxes.values())

    def finish_all(
        self, *, where: Callable[[ManagedBox], bool] | None = None
    ) -> list[tuple[str, str, bool, ContentFormat, int, Overflow]]:
        """
        Finish all boxes (or those ``where`` picks) and return their final states.

        Returns:
            List of (box_id, content, was_expanded, content_format,
            max_collapsed_lines, overflow) tuples.
        """
        with self._lock:
            results: list[tuple[str, str, bool, ContentFormat, int, Overflow]] = []
            for box_id, box in list(self._boxes.items()):
                if where is not None and not where(box):
                    continue
                del self._boxes[box_id]
                max_lines = box.control.max_collapsed_lines
                overflow = box.control.overflow
                content, was_expanded, fmt = box.control.finish()
                results.append((box_id, content, was_expanded, fmt, max_lines, overflow))
            self._reset_mode_if_empty()
            return results

    @property
    def is_expanded(self) -> bool:
        """True if boxes are currently expanded (by the user, or full screen)."""
        with self._lock:
            return self._box_expanded()

    @property
    def has_active_boxes(self) -> bool:
        """True if there are any active boxes."""
        with self._lock:
            return len(self._boxes) > 0

    @property
    def active_count(self) -> int:
        """Number of active boxes."""
        with self._lock:
            return len(self._boxes)
