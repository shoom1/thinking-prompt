"""
Layout creation for ThinkingPromptSession.

Provides functions to create the UI layout components:
- Thinking box (collapsible/expandable)
- Status bar
- Main layout composition
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, Literal

from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition, is_done
from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText
from prompt_toolkit.layout import (
    AnyContainer,
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
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import (
    HighlightIncrementalSearchProcessor,
    HighlightSelectionProcessor,
)

from .spinner import Spinner

if TYPE_CHECKING:
    from .manager import ThinkingBoxManager

# Seconds past a frame's tick that a header asks to be redrawn at, so timer
# jitter can't redraw it a hair early, still on the old frame.
_TICK_SLACK = 0.005

__all__ = [
    "ThinkingHeader",
    "create_layout",
    "create_status_bar",
    "create_thinking_area",
]


class ThinkingHeader:
    """
    Animated separator line for the thinking box.

    Displays a horizontal line with optional animated text in the center.
    The spinner steps through its frames, one per ``spinner.interval``;
    while drawn, an animated header asks for a redraw at its next frame.

    Example outputs:
        ─────── ⠋ Thinking ───────   (default, spinner before text)
        ─────── Processing... ───────  (dots after text)
        ─────── ⠋ ───────              (spinner only, no text)
        ───────────────────────────    (no animation, no text)
        ⠋ Thinking                     (border=False)
    """

    def __init__(
        self,
        text: str = "Thinking",
        spinner: Spinner | None = Spinner.DOTS,
        position: Literal["before", "after"] = "before",
        border_char: str = "─",
        request_frame: Callable[[float], None] | None = None,
        border: bool = True,
    ) -> None:
        """
        Initialize the thinking separator.

        Args:
            text: Text to display in the separator. Empty string for no text.
            spinner: The animation (None for none).
            position: Position of the spinner relative to text ('before' or 'after').
            border_char: Character used for the separator line.
            request_frame: Called with the seconds until the next frame each
                time an animated header is drawn, to have it redrawn then
                (the session passes its FrameScheduler.redraw_in).
            border: False: the spinner and the text only, at the left
                edge, with no line.
        """
        self.text = text
        self.spinner = spinner
        self.position = position
        self.border_char = border_char
        self.border = border
        self._request_frame = request_frame
        self._first_tick: int | None = None

    def _get_current_frame(self) -> str:
        """The animation frame for now; asks to be redrawn for the next one.

        Frames step on a clock every header shares (one tick per interval),
        so any number of spinners turn on the same redraws. Each starts on
        its first frame. A one-frame spinner never changes, so it asks for
        nothing.
        """
        spinner = self.spinner
        if spinner is None:
            return ""
        frames = spinner.frames
        if len(frames) == 1:
            return frames[0]

        now = time.monotonic()
        tick = int(now / spinner.interval)
        if self._first_tick is None:
            self._first_tick = tick
        if self._request_frame is not None:
            # A little past the tick, so the redraw lands on the new frame.
            self._request_frame((tick + 1) * spinner.interval - now + _TICK_SLACK)
        return frames[(tick - self._first_tick) % len(frames)]

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

        if not self.border:
            return FormattedText([("class:thinking-box.border", content)])

        # Calculate padding for left-adjusted content
        content_with_spaces = f" {content} " if content else ""

        remaining = max(0, width - len(content_with_spaces))
        left_pad = min(3, remaining)  # Small left margin
        right_pad = remaining - left_pad

        line = f"{self.border_char * left_pad}{content_with_spaces}{self.border_char * right_pad}"

        return FormattedText([("class:thinking-box.border", line)])


def create_thinking_area(manager: ThinkingBoxManager) -> DynamicContainer:
    """Create a dynamic container that renders active thinking boxes."""
    return DynamicContainer(lambda: manager.get_container())


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

    # The app's last frame, drawn as it exits, leaves out the status bar,
    # as prompt_toolkit's PromptSession leaves out its bottom toolbar.
    return ConditionalContainer(
        content=window,
        filter=Condition(is_enabled) & ~is_done,
    )


def create_layout(
    default_buffer: Buffer,
    message: Callable[[], AnyFormattedText],
    thinking_max_lines: int,
    get_status_text: Callable[[], AnyFormattedText],
    is_status_bar_enabled: Callable[[], bool],
    thinking_manager: ThinkingBoxManager | None = None,
    completions_menu_height: int = 5,
    inline_dialog: AnyContainer | None = None,
) -> Layout:
    """
    Create the layout with thinking boxes, input and status bar.

    Args:
        default_buffer: The main input buffer.
        message: Callable that returns the prompt message.
        thinking_max_lines: Maximum height for collapsed thinking box.
        get_status_text: Callable that returns status bar text.
        is_status_bar_enabled: Callable that returns status bar visibility.
        thinking_manager: ThinkingBoxManager instance for managing thinking boxes.
        completions_menu_height: Maximum height of the completions dropdown menu.
        inline_dialog: Shown between the input area and the status bar
            (inline dialogs).

    Returns:
        The complete Layout.
    """
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
        style="class:prompt",
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

    # Thinking area (visible when thinking)
    if thinking_manager is None:
        raise ValueError("thinking_manager is required")
    # Left out of the app's last frame: boxes still open then are echoed
    # below it instead (see ThinkingPromptSession.run_async).
    thinking_area = ConditionalContainer(
        create_thinking_area(thinking_manager), filter=~is_done
    )

    # Status bar
    status_bar = create_status_bar(
        get_status_text=get_status_text,
        is_enabled=is_status_bar_enabled,
    )

    # Build the main layout
    main_layout = HSplit([
        thinking_area,         # Only visible when thinking
        input_with_separators, # Always visible
        *([inline_dialog] if inline_dialog is not None else []),  # Inline dialogs
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
