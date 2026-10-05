"""
Box presentation of dialogs: prompt_toolkit's framed Dialog widget, floating
over the session's layout.

DialogManager decides when a dialog opens and closes; this module decides how
a box dialog looks and where it floats.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import (
    AnyContainer,
    ConditionalContainer,
    DynamicContainer,
    Float,
    FloatContainer,
    HSplit,
    ScrollablePane,
    Window,
    to_container,
)
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button
from prompt_toolkit.widgets import Dialog as _DialogWidget

if TYPE_CHECKING:
    from .dialog import Dialog
    from .session import ThinkingPromptSession

# Chrome height = title bar (2) + button row (2) + padding (1) around the body.
# Used when a dialog's ``height`` is set to compute the body area from the total.
CHROME_HEIGHT = 5

# Rows reserved below/above the dialog: prompt area, status bar, margin.
# When a dialog's ``height`` is set, the effective height is clamped to
# ``terminal_height - TERMINAL_BUFFER_ROWS`` so the dialog doesn't cover the
# prompt or overflow the screen.
TERMINAL_BUFFER_ROWS = 4

# Smallest total dialog height (chrome + body) that's considered usable.
# With TERMINAL_BUFFER_ROWS = 4, this implies a minimum terminal height of
# MIN_DIALOG_HEIGHT + TERMINAL_BUFFER_ROWS = 12 rows.
MIN_DIALOG_HEIGHT = 8

# Returned by BoxPresenter.effective_height() when the terminal is too small
# to show the dialog. The caller aborts without building the widget.
TERMINAL_TOO_SMALL = object()


@dataclass
class BoxView:
    """A built box dialog.

    Attributes:
        widget: prompt_toolkit's Dialog widget.
        buttons: Its Button widgets, one per ButtonConfig, in order.
        focused_button: The first ``ButtonConfig(focused=True)`` button, if any.
    """

    widget: _DialogWidget
    buttons: list[Button]
    focused_button: Button | None = None

    @property
    def initial_focus(self) -> Window | None:
        """The window to focus when the dialog opens, if a button asked for it."""
        return self.focused_button.window if self.focused_button else None


def build_box(dialog: Dialog, effective_height: int | None = None) -> BoxView:
    """Build prompt_toolkit's Dialog widget for ``dialog``.

    Args:
        dialog: The dialog to draw.
        effective_height: Height after terminal clamping; overrides
            ``dialog.height``. None means use ``dialog.height`` directly.
    """
    body: AnyContainer = dialog.build_body()

    # Pin body height so the Dialog renders in one shot (opt-in via the
    # ``height`` attribute). Overflow scrolls within the pane.
    h = effective_height if effective_height is not None else dialog.height
    if h is not None and h > 0:
        body = HSplit(
            [ScrollablePane(to_container(body), show_scrollbar=True)],
            height=Dimension.exact(max(1, h - CHROME_HEIGHT)),
        )

    # Each ButtonConfig's style and focused flag apply however the dialog was made.
    buttons: list[Button] = []
    focused: Button | None = None
    for cfg in dialog._button_configs():
        button = Button(text=cfg.text, handler=dialog._click_handler(cfg))
        _apply_button_style(button, cfg.style)
        if cfg.focused and focused is None:
            focused = button
        buttons.append(button)

    widget = _DialogWidget(
        title=dialog.title,
        body=body,
        buttons=buttons,
        width=_width_dimension(dialog.width),
        with_background=False,  # Use styled dialog, no light overlay
    )
    return BoxView(widget, buttons, focused)


def _width_dimension(width: int | None) -> Dimension | None:
    """None/0 = auto-size, -1 = as wide as possible, >0 = preferred width."""
    if width is None or width == 0:
        return None
    if width == -1:
        # Max width - use large preferred with no max constraint
        return Dimension(preferred=9999)
    # Preferred width (allows shrinking if terminal is smaller)
    return Dimension(preferred=width)


def _apply_button_style(button: Button, extra_style: str) -> None:
    """Append ``extra_style`` to a Button's style classes.

    The Button widget builds its own style callable that toggles between
    ``class:button`` and ``class:button.focused`` based on focus. We wrap
    that callable to append the user's style so focus styling still works.
    """
    if not extra_style:
        return
    original = button.window.style
    if callable(original):
        def combined() -> str:
            return f"{original()} {extra_style}".strip()
        button.window.style = combined
    else:
        button.window.style = f"{original} {extra_style}".strip()


class BoxPresenter:
    """Floats box dialogs over the session's layout."""

    def __init__(self, session: ThinkingPromptSession) -> None:
        self._session = session
        self.view: BoxView | None = None
        self._float = Float(
            content=ConditionalContainer(
                content=DynamicContainer(self._content),
                filter=Condition(lambda: self.view is not None),
            ),
            allow_cover_cursor=True,
        )
        self._installed = False

    def _content(self) -> AnyContainer:
        return self.view.widget if self.view is not None else Window()

    def install(self) -> None:
        """Wrap the session's layout container in a FloatContainer (once)."""
        if self._installed:
            return
        layout = self._session.app.layout
        layout.container = FloatContainer(content=layout.container, floats=[self._float])
        self._installed = True

    def effective_height(self, dialog: Dialog) -> Any:
        """Clamp ``dialog.height`` to the terminal.

        Returns:
            None if the dialog didn't ask for a fixed height; TERMINAL_TOO_SMALL
            (after reporting an error line) if the terminal can't fit the
            smallest usable dialog; otherwise the clamped height.
        """
        if dialog.height is None or dialog.height <= 0:
            return None

        term_height = shutil.get_terminal_size().lines
        max_allowed = term_height - TERMINAL_BUFFER_ROWS

        if max_allowed < MIN_DIALOG_HEIGHT:
            required = MIN_DIALOG_HEIGHT + TERMINAL_BUFFER_ROWS
            self._session.add_error(
                f"Not enough room to show dialog: need at least {required} "
                f"terminal rows, have {term_height}."
            )
            return TERMINAL_TOO_SMALL

        return min(dialog.height, max_allowed)

    def open(self, dialog: Dialog, effective_height: int | None) -> BoxView:
        """Build ``dialog`` and float it according to its ``top``."""
        view = build_box(dialog, effective_height)

        if dialog.top is None:
            # Center: no top or bottom constraint
            self._float.top = None
            self._float.bottom = None
        elif dialog.top >= 0:
            # Offset from top
            self._float.top = dialog.top
            self._float.bottom = None
        else:
            # Negative = offset from bottom
            self._float.top = None
            self._float.bottom = abs(dialog.top)

        # Pin the Float height so prompt_toolkit allocates the full height in
        # one render frame instead of measuring the content over several.
        self._float.height = effective_height

        self.view = view
        return view

    def close(self) -> None:
        self.view = None
