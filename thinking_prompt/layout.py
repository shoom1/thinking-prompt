"""
Layout creation for ThinkingPromptSession.

Provides functions to create the UI layout components:
- Thinking box (collapsible/expandable)
- History window (for fullscreen mode)
- Status bar
- Main layout composition
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, Literal

from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText
from prompt_toolkit.layout import (
    BufferControl,
    DynamicContainer,
    Float,
    FloatContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.containers import ConditionalContainer, ScrollOffsets
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import (
    HighlightIncrementalSearchProcessor,
    HighlightSelectionProcessor,
)

from .types import DEFAULT_SPINNER_FRAMES

if TYPE_CHECKING:
    from .history import FormattedTextHistory
    from .manager import ThinkingBoxManager

__all__ = [
    "DEFAULT_SPINNER_FRAMES",  # re-export; canonical home is types.py
    "ThinkingHeader",
    "ThinkingSeparator",
    "create_history_window",
    "create_layout",
    "create_status_bar",
    "create_thinking_area",
]


class ThinkingHeader:
    """
    Animated separator line for the thinking box.

    Displays a horizontal line with optional animated text in the center.
    The animation cycles through frames on each render.

    Example outputs:
        ─────── ⠋ Thinking ───────   (default, spinner before text)
        ─────── Processing... ───────  (dots after text)
        ─────── ⠋ ───────              (spinner only, no text)
        ───────────────────────────    (no animation, no text)
    """

    def __init__(
        self,
        text: str = "Thinking",
        frames: tuple[str, ...] = DEFAULT_SPINNER_FRAMES,
        position: Literal["before", "after"] = "before",
        border_char: str = "─",
        animation_interval: float = 0.1,
    ) -> None:
        """
        Initialize the thinking separator.

        Args:
            text: Text to display in the separator. Empty string for no text.
            frames: Animation frames to cycle through. Empty tuple for no animation.
            position: Position of animation relative to text ('before' or 'after').
            border_char: Character used for the separator line.
            animation_interval: Time between frame changes in seconds.
        """
        self.text = text
        self.frames = frames
        self.position = position
        self.border_char = border_char
        self.animation_interval = animation_interval
        self._last_update = 0.0
        self._frame_index = 0

    def _get_current_frame(self) -> str:
        """Get current animation frame, advancing if interval elapsed."""
        if not self.frames:
            return ""

        now = time.time()
        if now - self._last_update >= self.animation_interval:
            self._frame_index = (self._frame_index + 1) % len(self.frames)
            self._last_update = now

        return self.frames[self._frame_index]

    def get_formatted_text(self, width: int = 80) -> FormattedText:
        """
        Generate the separator line with current animation frame.

        Args:
            width: Total width of the separator line.

        Returns:
            FormattedText with styled separator content.
        """
        frame = self._get_current_frame()

        # Build content based on position
        if frame and self.text:
            if self.position == "before":
                content = f"{frame} {self.text}"
            else:
                content = f"{self.text} {frame}"
        elif frame:
            content = frame
        elif self.text:
            content = self.text
        else:
            content = ""

        # Calculate padding for left-adjusted content
        content_with_spaces = f" {content} " if content else ""

        remaining = max(0, width - len(content_with_spaces))
        left_pad = min(3, remaining)  # Small left margin
        right_pad = remaining - left_pad

        line = f"{self.border_char * left_pad}{content_with_spaces}{self.border_char * right_pad}"

        return FormattedText([("class:thinking-box.border", line)])

    def reset(self) -> None:
        """Reset animation to first frame."""
        self._frame_index = 0
        self._last_update = 0.0


# Backward-compat alias
ThinkingSeparator = ThinkingHeader


def create_thinking_area(manager: ThinkingBoxManager) -> DynamicContainer:
    """Create a dynamic container that renders active thinking boxes."""
    return DynamicContainer(lambda: manager.get_container())


def create_history_window(
    history: FormattedTextHistory,
    is_visible: Condition,
    style: str = "",
) -> ConditionalContainer:
    """
    Create the history window.

    The history:
    - Is visible based on the is_visible filter
    - Shows scrollable history of formatted text
    - Looks like normal console output
    - Takes up remaining space above thinking box
    - Auto-scrolls to show newest content
    - Supports mouse scrolling to view earlier messages

    Args:
        history: The FormattedTextHistory instance.
        is_visible: Filter controlling visibility.
        style: Style for the history window.

    Returns:
        A ConditionalContainer with the history.
    """
    # Track content length to detect new content
    last_history_len = [0]  # Use list for mutable closure

    def get_history_text() -> FormattedText:
        return history.get_formatted_text()

    def get_cursor_position() -> Point | None:
        """Return cursor position at end only when new content is added."""
        current_len = len(history)
        if current_len > last_history_len[0]:
            # New content added - scroll to bottom
            last_history_len[0] = current_len
            text = history.get_formatted_text()
            line_count = sum(fragment[1].count('\n') for fragment in text)
            return Point(x=0, y=max(0, line_count - 1))
        # No new content - return None to preserve scroll position
        return None

    # Control with dynamic content - focusable for mouse scroll support
    control = FormattedTextControl(
        text=get_history_text,
        focusable=True,  # Enable mouse interaction
        show_cursor=False,
        get_cursor_position=get_cursor_position,
    )

    # Window that takes remaining space - minimal styling to look like console
    history_window = Window(
        content=control,
        style=style,
        wrap_lines=True,
        scroll_offsets=ScrollOffsets(top=2, bottom=2),
        right_margins=[ScrollbarMargin(display_arrows=True)],
        allow_scroll_beyond_bottom=True,
    )

    return ConditionalContainer(
        content=history_window,
        filter=is_visible,
    )


def create_status_bar(
    get_status_text: Callable[[], AnyFormattedText],
    is_enabled: Callable[[], bool],
) -> ConditionalContainer:
    """
    Create the status bar at the bottom of the screen.

    Args:
        get_status_text: Callable that returns the status text.
        is_enabled: Callable that returns whether status bar is enabled.

    Returns:
        A ConditionalContainer with the status bar.
    """
    def _resolve_status_text() -> AnyFormattedText:
        text = get_status_text()
        if isinstance(text, str):
            return FormattedText([("class:status", text)])
        return text

    control = FormattedTextControl(
        text=_resolve_status_text,
        focusable=False,
    )

    window = Window(
        content=control,
        height=D.exact(1),
        style="class:status",
        dont_extend_height=True,
    )

    return ConditionalContainer(
        content=window,
        filter=Condition(is_enabled),
    )


def create_layout(
    default_buffer: Buffer,
    message: Callable[[], AnyFormattedText],
    max_thinking_height: int,
    history: FormattedTextHistory,
    is_fullscreen: Callable[[], bool],
    get_status_text: Callable[[], AnyFormattedText],
    is_status_bar_enabled: Callable[[], bool],
    thinking_manager: ThinkingBoxManager | None = None,
    completions_menu_height: int = 5,
) -> Layout:
    """
    Create the layout with chat history, thinking box, and input.

    Args:
        default_buffer: The main input buffer.
        message: Callable that returns the prompt message.
        max_thinking_height: Maximum height for collapsed thinking box.
        history: The FormattedTextHistory instance.
        is_fullscreen: Callable that returns fullscreen state.
        get_status_text: Callable that returns status bar text.
        is_status_bar_enabled: Callable that returns status bar visibility.
        thinking_manager: ThinkingBoxManager instance for managing thinking boxes.
        completions_menu_height: Maximum height of the completions dropdown menu.

    Returns:
        The complete Layout.
    """
    # Conditions
    is_fullscreen_cond = Condition(is_fullscreen)

    # Input processors
    input_processors = [
        HighlightIncrementalSearchProcessor(),
        HighlightSelectionProcessor(),
    ]

    # Buffer control for input
    buffer_control = BufferControl(
        buffer=default_buffer,
        input_processors=input_processors,
    )

    # Prompt window
    prompt_window = Window(
        content=FormattedTextControl(text=message),
        dont_extend_width=True,
        dont_extend_height=True,
    )

    # Dynamic height function that reserves space for completion menu
    def get_input_height() -> D:
        # Reserve space only when completions menu is actually visible
        if (
            completions_menu_height > 0
            and not get_app().is_done
            and default_buffer.complete_state is not None
        ):
            return D(min=completions_menu_height)
        return D()

    # Input window - sizes naturally, but reserves space for completions menu
    input_window = Window(
        content=buffer_control,
        height=get_input_height,
        wrap_lines=True,
    )

    # Main input container with prompt + input + completions
    input_line = VSplit([
        prompt_window,
        input_window,
    ])

    # Separator lines above and below input
    separator_top = Window(
        height=D.exact(1),
        char='─',
        style='class:input-separator',
    )
    separator_bottom = Window(
        height=D.exact(1),
        char='─',
        style='class:input-separator',
    )

    # Input area with separators
    input_with_separators = HSplit([
        separator_top,
        input_line,
        separator_bottom,
    ])

    # Chat history (visible in full-screen mode) - looks like normal console
    history_window = create_history_window(
        history=history,
        is_visible=is_fullscreen_cond,
    )

    # Thinking area (visible when thinking)
    if thinking_manager is None:
        raise ValueError("thinking_manager is required")
    thinking_area = create_thinking_area(thinking_manager)

    # Status bar
    status_bar = create_status_bar(
        get_status_text=get_status_text,
        is_enabled=is_status_bar_enabled,
    )

    # Build the main layout
    main_layout = HSplit([
        history_window,        # Only visible in full-screen
        thinking_area,         # Only visible when thinking
        input_with_separators, # Always visible
        status_bar,            # Status bar at bottom
    ])

    # Wrap in FloatContainer at root level so completions menu can expand
    root = FloatContainer(
        content=main_layout,
        floats=[
            Float(
                xcursor=True,
                ycursor=True,
                transparent=True,
                content=CompletionsMenu(max_height=completions_menu_height),
            ),
        ],
    )

    return Layout(root, focused_element=default_buffer)
