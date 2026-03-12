"""
ThinkingBoxManager — manages a collection of thinking boxes.

Provides ManagedBox (dataclass holding one box's state) and
ThinkingBoxManager (collection manager with thread-safe operations).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.containers import Container, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.layout.margins import ConditionalMargin, ScrollbarMargin

from .layout import ThinkingHeader
from .thinking import ThinkingBoxControl
from .types import ContentFormat, StreamingContent


@dataclass
class ManagedBox:
    """State for a single managed thinking box."""

    box_id: str
    control: ThinkingBoxControl
    header: Optional[ThinkingHeader]
    container: Container
    order: int
    seq: int
    streaming_content: Optional[StreamingContent]


class ThinkingBoxManager:
    """
    Manages a collection of thinking boxes.

    Thread-safe via RLock. Supports creating, removing, sorting,
    and bulk expand/collapse of boxes.
    """

    def __init__(
        self,
        default_max_lines: int = 15,
        default_style: str = "class:thinking-box",
    ) -> None:
        self._default_max_lines = default_max_lines
        self._default_style = default_style
        self._boxes: dict[str, ManagedBox] = {}
        self._seq_counter = 0
        self._auto_id_counter = 0
        self._expanded = False
        self._lock = threading.RLock()

    def create_box(
        self,
        content_callback: Optional[Callable[[], str]] = None,
        *,
        title: Optional[str] = None,
        order: int = 0,
        max_lines: Optional[int] = None,
        content_format: ContentFormat = "plain",
        box_id: Optional[str] = None,
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

            # Create control
            control = ThinkingBoxControl(
                max_collapsed_lines=effective_max_lines,
                style=self._default_style,
            )

            # Create StreamingContent if no callback provided
            streaming_content: Optional[StreamingContent] = None
            if content_callback is None:
                streaming_content = StreamingContent()
                content_callback = streaming_content.get_content

            # Start the control
            control.start(content_callback, content_format=content_format)

            # Apply current expand state
            if self._expanded:
                control.expand()

            # Create header if title provided
            header: Optional[ThinkingHeader] = None
            if title is not None:
                header = ThinkingHeader(text=title)

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
            )

            self._boxes[box_id] = box
            return box

    def _build_container(
        self,
        control: ThinkingBoxControl,
        header: Optional[ThinkingHeader],
        max_lines: int,
    ) -> Container:
        """Build the layout container for a single box."""

        def get_height() -> D:
            if control.is_expanded:
                return D(min=5, preferred=20, max=40)
            else:
                line_count = control.get_line_count()
                height = min(max(1, line_count), max_lines)
                return D(min=1, max=max_lines, preferred=height)

        is_expanded_filter = Condition(lambda: control.is_expanded)

        content_window = Window(
            content=control,
            height=get_height,
            wrap_lines=True,
            dont_extend_height=True,
            right_margins=[
                ConditionalMargin(
                    ScrollbarMargin(display_arrows=True),
                    filter=is_expanded_filter,
                ),
            ],
        )

        if header is not None:
            header_control = FormattedTextControl(
                text=lambda h=header: h.get_formatted_text(80)
            )
            header_window = Window(
                content=header_control,
                height=D.exact(1),
            )
            return HSplit([header_window, content_window])

        return content_window

    def remove_box(self, box_id: str) -> Tuple[str, bool, ContentFormat]:
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
            return box.control.finish()

    def get_sorted_boxes(self) -> List[ManagedBox]:
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
        """Toggle expand/collapse for all boxes."""
        with self._lock:
            self._expanded = not self._expanded
            for box in self._boxes.values():
                if self._expanded:
                    box.control.expand()
                else:
                    box.control.collapse()

    def expand_all(self) -> None:
        """Expand all boxes."""
        with self._lock:
            self._expanded = True
            for box in self._boxes.values():
                box.control.expand()

    def collapse_all(self) -> None:
        """Collapse all boxes."""
        with self._lock:
            self._expanded = False
            for box in self._boxes.values():
                box.control.collapse()

    def can_toggle(self) -> bool:
        """
        Check if toggle is available.

        Returns True if expanded or any box can toggle.
        """
        with self._lock:
            if self._expanded:
                return True
            return any(box.control.can_toggle_expanded for box in self._boxes.values())

    def finish_all(self) -> List[Tuple[str, str, bool, ContentFormat]]:
        """
        Finish all boxes and return their final states.

        Returns:
            List of (box_id, content, was_expanded, content_format) tuples.
        """
        with self._lock:
            results: List[Tuple[str, str, bool, ContentFormat]] = []
            for box_id in list(self._boxes.keys()):
                box = self._boxes.pop(box_id)
                content, was_expanded, fmt = box.control.finish()
                results.append((box_id, content, was_expanded, fmt))
            return results

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
