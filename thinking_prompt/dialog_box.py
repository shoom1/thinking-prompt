"""
Box presentation of dialogs: prompt_toolkit's framed Dialog widget, floating
over the session's layout.

DialogManager decides when a dialog opens and closes; this module decides how
a box dialog looks, where it floats and how tall it is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import (
    ConditionalContainer,
    Container,
    DynamicContainer,
    Float,
    FloatContainer,
    Window,
    to_container,
)
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button
from prompt_toolkit.widgets import Dialog as _DialogWidget

from .dialog_scroll import AtMost, ScrollRegion, dialog_cap, focusable_windows

if TYPE_CHECKING:
    from .dialog import Dialog
    from .session import ThinkingPromptSession


@dataclass
class BoxView:
    """A built box dialog.

    Attributes:
        widget: prompt_toolkit's Dialog widget.
        buttons: Its Button widgets, one per ButtonConfig, in order.
        focused_button: The first ``ButtonConfig(focused=True)`` button, if any.
        max_height: The dialog's max_height (None: the terminal's).
        text_region: The body's region when nothing in the body takes focus (a text body): it scrolls by keys.
    """

    widget: _DialogWidget
    buttons: list[Button]
    focused_button: Button | None = None
    max_height: int | None = None
    text_region: ScrollRegion | None = None

    @property
    def initial_focus(self) -> Window | None:
        """The window to focus when the dialog opens, if a button asked for it."""
        return self.focused_button.window if self.focused_button else None


def build_box(dialog: Dialog) -> BoxView:
    """Build prompt_toolkit's Dialog widget for ``dialog``.

    The body sits in a ScrollRegion: when the dialog is capped
    (BoxPresenter.rows), it scrolls with the cursor, or by keys for a text body.
    """
    content = to_container(dialog.build_body())
    body = ScrollRegion(content, scrollbar=True)
    # Nothing in it takes focus (a text body): it scrolls by keys.
    text_region = body if not focusable_windows(content) else None

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
    return BoxView(widget, buttons, focused, dialog.max_height, text_region)


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
        # The open dialog's widget, no taller than rows(). The float takes
        # its content's height: given a height of its own, FloatContainer
        # would no longer trim it to the rows left under top= (or above
        # a negative one), cutting off the title or the buttons.
        self._capped: Container = Window()
        self._float = Float(
            content=ConditionalContainer(
                content=DynamicContainer(lambda: self._capped),
                filter=Condition(lambda: self.view is not None),
            ),
            allow_cover_cursor=True,
        )
        self._installed = False

    def install(self) -> None:
        """Wrap the session's layout container in a FloatContainer (once)."""
        if self._installed:
            return
        layout = self._session.app.layout
        layout.container = FloatContainer(content=layout.container, floats=[self._float])
        self._installed = True

    def open(self, dialog: Dialog) -> BoxView:
        """Build ``dialog`` and float it according to its ``top``."""
        view = build_box(dialog)

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

        self.view = view
        self._capped = AtMost(to_container(view.widget), self._cap)
        return view

    def close(self) -> None:
        self.view = None
        self._capped = Window()

    def rows(self, width: int, max_rows: int) -> int:
        """Rows the open dialog takes in a ``width``-column, ``max_rows``-row
        terminal: its content's, capped by its max_height and the terminal
        (dialog_cap), but never fewer than its frame, buttons and one body
        row need. 0 when none is open."""
        if self.view is None:
            return 0
        widget = to_container(self.view.widget)
        dialog_width = min(widget.preferred_width(width).preferred, width)
        wanted = widget.preferred_height(dialog_width, max_rows)
        cap = dialog_cap(self.view.max_height, max_rows)
        return max(wanted.min, min(wanted.preferred, cap))

    def _cap(self, width: int) -> int:
        """The open dialog's rows in the app's terminal: rows(), as the
        session reserves them. (``width``, the float's, is the dialog's own.)"""
        size = get_app().output.get_size()
        return self.rows(size.columns, size.rows)
