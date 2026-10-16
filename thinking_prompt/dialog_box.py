"""
Box presentation of dialogs: prompt_toolkit's framed Dialog widget, floating
over the session's layout.

DialogManager decides when a dialog opens and closes; this module decides how
a box dialog looks, where it floats and how tall it is.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import merge_key_bindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    Container,
    DynamicContainer,
    Float,
    FloatContainer,
    FormattedTextControl,
    Window,
    to_container,
)
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button, Frame, Label
from prompt_toolkit.widgets import Dialog as _DialogWidget

from .dialog_scroll import AtMost, ScrollRegion, dialog_cap, focusable_windows

if TYPE_CHECKING:
    from prompt_toolkit.layout.mouse_handlers import MouseHandlers
    from prompt_toolkit.layout.screen import Screen, WritePosition

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
        floats: Floats the body needs over the whole screen (Dialog._screen_floats), drawn over the box.
        start: Where the body's cursor starts when no button asks for focus (a radio list's picked option).
    """

    widget: _DialogWidget
    buttons: list[Button]
    focused_button: Button | None = None
    max_height: int | None = None
    text_region: ScrollRegion | None = None
    floats: list[Float] = field(default_factory=list)
    start: Container | None = None

    @property
    def initial_focus(self) -> Container | None:
        """What to focus when the dialog opens: a ButtonConfig(focused=True)
        button, else where the body's cursor starts; None: the widget's first
        focusable window (a button)."""
        if self.focused_button is not None:
            return self.focused_button.window
        return self.start


def build_box(dialog: Dialog) -> BoxView:
    """Build prompt_toolkit's Dialog widget for ``dialog``.

    When the dialog is capped (BoxPresenter._cap), a body that is one window
    taking the cursor (a radio list, a text field) is squeezed and scrolls
    itself. Any other body sits in a ScrollRegion: it scrolls with the
    cursor (form fields, a check list), or by keys for a text body.
    """
    content, start = dialog._content()
    if content is None:
        # No fields and an empty text body: one blank row, as ever.
        content = to_container(Label(text=""))
    stops = focusable_windows(content)
    body: Container = content
    text_region: ScrollRegion | None = None
    # A body whose stops are one window stays out of a region: there, a
    # focused window taller than the region fills it, and the text above
    # it (a dropdown's question) never shows.
    if len(stops) != 1:

        def at_first_stop() -> bool:
            # Back at the first stop, the region scrolls to its top: rows
            # above that stop (a check list's text) show again.
            first = focusable_windows(content)[:1]
            return bool(first) and get_app().layout.has_focus(first[0])

        body = ScrollRegion(content, at_first_stop, scrollbar=True)
        # Nothing in it takes focus (a text body): it scrolls by keys.
        text_region = body if not stops else None

    # Each ButtonConfig's style and focused flag apply however the dialog was made.
    buttons: list[Button] = []
    focused: Button | None = None
    for cfg in dialog._button_configs():
        button = Button(text=cfg.text, handler=dialog._click_handler(cfg))
        _apply_button_style(button, cfg.style)
        if cfg.focused and focused is None:
            focused = button
        buttons.append(button)
    # Tab / Shift+Tab from a button enter a field at its start (a radio
    # list's pick), not at its row nearest the buttons. On each button's own
    # control, so they win over the dialog widget's keys.
    tabs = dialog._form.button_tab_bindings()
    for button in buttons:
        own = button.control.key_bindings
        button.control.key_bindings = tabs if own is None else merge_key_bindings([own, tabs])

    widget = _DialogWidget(
        title=dialog.title,
        body=body,
        buttons=buttons,
        # Never narrower than its buttons, inside the frame: below that the
        # box collapses to an empty frame.
        width=_width_dimension(dialog.width, _buttons_row(buttons) + 2),
        with_background=False,  # Use styled dialog, no light overlay
    )
    return BoxView(
        widget=widget,
        buttons=buttons,
        focused_button=focused,
        max_height=dialog.max_height,
        text_region=text_region,
        floats=dialog._screen_floats(),
        start=start,
    )


def _width_dimension(width: int | None, least: int) -> Dimension | None:
    """None/0 = auto-size, -1 = as wide as possible, >0 = preferred width,
    at least ``least``."""
    if width is None or width == 0:
        return None
    if width == -1:
        # Max width - use large preferred with no max constraint
        return Dimension(preferred=9999)
    # Preferred width (allows shrinking if terminal is smaller)
    return Dimension(preferred=max(width, least))


def _buttons_row(buttons: list[Button]) -> int:
    """The columns ``buttons`` take side by side (VSplit's padding=1
    between): the one row of a box that can't be squeezed."""
    widths = [b.window.preferred_width(1000).min for b in buttons]
    return sum(widths) + max(len(widths) - 1, 0)


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


class _BoxOrNotice(Container):
    """``box`` (the capped dialog widget), or a notice in its place while the
    terminal is too small for it.

    The box stays among the children, so its windows keep their focus and
    key bindings; only its drawing is replaced. ``notice`` gives the
    notice's container, or None when the box fits: asked on each size
    question and draw, so the terminal growing brings the box back.
    """

    def __init__(self, box: Container, notice: Callable[[], Container | None]) -> None:
        self.box = box
        self.notice = notice

    def _shown(self) -> Container:
        return self.notice() or self.box

    def reset(self) -> None:
        self.box.reset()

    def preferred_width(self, max_available_width: int) -> Dimension:
        return self._shown().preferred_width(max_available_width)

    def preferred_height(self, width: int, max_available_height: int) -> Dimension:
        return self._shown().preferred_height(width, max_available_height)

    def write_to_screen(
        self,
        screen: Screen,
        mouse_handlers: MouseHandlers,
        write_position: WritePosition,
        parent_style: str,
        erase_bg: bool,
        z_index: int | None,
    ) -> None:
        self._shown().write_to_screen(
            screen, mouse_handlers, write_position, parent_style, erase_bg, z_index
        )

    def get_children(self) -> list[Container]:
        return [self.box]


class _BoxFloat(Float):
    """The box's float: anchored to the window that holds its reserved
    rows, where an inline dialog would be, or centered over the drawn area.

    ``room`` gives that window while the box sits over it (None when it
    isn't drawn, or got fewer rows than the box's smallest size: the box
    centers then). Asked on each draw. The anchor is the window's top-left,
    so with ``ycursor`` and ``allow_cover_cursor`` the box's top border
    lands on its first row.
    """

    def __init__(self, room: Callable[[], Window | None], **kwargs: Any) -> None:
        self._room = room
        super().__init__(**kwargs)

    # Float assigns these in __init__; here they are worked out when read.
    @property
    def attach_to_window(self) -> Window | None:
        return self._room()

    @attach_to_window.setter
    def attach_to_window(self, value: Any) -> None:
        pass

    @property
    def ycursor(self) -> bool:
        return self._room() is not None

    @ycursor.setter
    def ycursor(self, value: bool) -> None:
        pass


class BoxPresenter:
    """Floats box dialogs over the session's layout."""

    def __init__(self, session: ThinkingPromptSession) -> None:
        self._session = session
        self.view: BoxView | None = None
        # The open dialog's widget, no taller than _cap(): the float takes
        # its content's height.
        self._capped: Container = Window()
        self._title = ""
        self._escapable = True
        self._float = _BoxFloat(
            self._room_window,
            content=ConditionalContainer(
                content=DynamicContainer(lambda: self._capped),
                filter=Condition(lambda: self.view is not None),
            ),
            allow_cover_cursor=True,
        )
        self._installed = False
        self._root: FloatContainer | None = None
        # _smallest's last answer and the question it answered: asked several
        # times per draw, and measuring the whole body each time is slow.
        self._smallest_memo: tuple[tuple[int, int, int], tuple[int, int]] | None = None
        # _room's last decision and the (render, room rows) it was for: the
        # float asks for its anchor, its cursor flag and its cap in one
        # draw, and must get one answer, even if the terminal is resized
        # meanwhile.
        self._room_memo: tuple[tuple[int, int], bool] | None = None

    def install(self) -> None:
        """Wrap the session's layout container in a FloatContainer (once)."""
        if self._installed:
            return
        layout = self._session.app.layout
        self._root = FloatContainer(content=layout.container, floats=[self._float])
        layout.container = self._root
        self._installed = True

    @property
    def root(self) -> FloatContainer:
        """The float layer install() put over the session's layout, the whole
        screen: box dialogs float on it, and so do an open dialog's own
        floats (a dropdown's menu), box or inline."""
        assert self._root is not None  # install() ran
        return self._root

    def open(self, dialog: Dialog) -> BoxView:
        """Build ``dialog`` and float it over its reserved rows (_BoxFloat)."""
        view = build_box(dialog)
        self.view = view
        self._title = dialog.title
        self._escapable = dialog.escapable
        self._smallest_memo = None
        self._room_memo = None
        self._capped = _BoxOrNotice(
            AtMost(to_container(view.widget), self._cap), self._notice_in_app
        )
        # The body's own floats go on the root, over the whole screen, after
        # the box's so they draw over it. Hidden with the box: a notice
        # leaves them no row to attach to.
        if view.floats:
            boxed = Condition(lambda: self._notice_in_app() is None)
            for fl in view.floats:
                fl.content = ConditionalContainer(fl.content, filter=boxed)
            self.root.floats.extend(view.floats)
        return view

    def close(self) -> None:
        if self.view is not None:
            for fl in self.view.floats:
                self.root.floats.remove(fl)
        self.view = None
        self._smallest_memo = None
        self._room_memo = None
        self._capped = Window()

    def rows(self, width: int, max_rows: int) -> int:
        """Rows the open dialog takes in a ``width``-column, ``max_rows``-row
        terminal: its content's, capped by its max_height and the terminal
        (dialog_cap), but never fewer than its frame, buttons and one body
        row need. 0 when none is open."""
        if self.view is None:
            return 0
        notice = self._notice(width, max_rows)
        if notice is not None:
            return min(self._notice_rows(notice, width), max_rows)
        widget = to_container(self.view.widget)
        dialog_width = min(widget.preferred_width(width).preferred, width)
        wanted = widget.preferred_height(dialog_width, max_rows)
        cap = dialog_cap(self.view.max_height, max_rows)
        return max(wanted.min, min(wanted.preferred, cap))

    def _smallest(self, width: int, max_rows: int) -> tuple[int, int]:
        """The open dialog's smallest size (columns, rows): its frame, buttons
        row and one body row. Measured once per draw: the answer is kept
        for the same terminal size and render, so a resize or a new render
        (after a content change) measures again."""
        assert self.view is not None
        key = (width, max_rows, get_app().render_counter)
        if self._smallest_memo is not None and self._smallest_memo[0] == key:
            return self._smallest_memo[1]
        smallest = self._measure_smallest(width, max_rows)
        self._smallest_memo = (key, smallest)
        return smallest

    def _measure_smallest(self, width: int, max_rows: int) -> tuple[int, int]:
        assert self.view is not None
        widget = to_container(self.view.widget)
        # A box given a width reports no minimum for it, so the width comes
        # from the buttons row, inside the frame.
        needs_width = max(widget.preferred_width(width).min, _buttons_row(self.view.buttons) + 2)
        # Height at the width the box would get: below its minimum width the
        # box collapses, and reports a frame's two rows and no more.
        box_width = min(widget.preferred_width(width).preferred, max(width, needs_width))
        return needs_width, widget.preferred_height(box_width, max_rows).min

    def _notice(self, width: int, max_rows: int) -> Container | None:
        """The notice to draw in a ``width``-column, ``max_rows``-row terminal
        if the open dialog's smallest size doesn't fit it, else None."""
        if self.view is None:
            return None
        needs_width, needs_rows = self._smallest(width, max_rows)
        if needs_width <= width and needs_rows <= max_rows:
            return None
        text = f"Terminal too small: needs {needs_width}\u00d7{needs_rows}"
        if self._escapable:
            text += " \u00b7 Esc cancels"
        # Wrapped at spaces to the frame's inside; a longer word is cut.
        lines = textwrap.wrap(text, max(width - 2, 1))
        return to_container(Frame(
            Window(FormattedTextControl("\n".join(lines)), dont_extend_height=True),
            title=self._title,
            style="class:dialog.body",
        ))

    def _notice_in_app(self) -> Container | None:
        size = get_app().output.get_size()
        return self._notice(size.columns, size.rows)

    @staticmethod
    def _notice_rows(notice: Container, width: int) -> int:
        """The notice's rows in a ``width``-column terminal."""
        notice_width = min(notice.preferred_width(width).preferred, width)
        return notice.preferred_height(notice_width, 1000).preferred

    def _cap(self, width: int) -> int:
        """The open dialog's rows in the app's terminal: rows(), as the
        session reserves them, or fewer, the rows its room got when the rest
        of the layout took some (a thinking box, a longer prompt): what
        doesn't fit scrolls. (``width``, the float's, is the dialog's own.)"""
        size = get_app().output.get_size()
        rows = self.rows(size.columns, size.rows)
        room = self._room()
        return rows if room is None else min(rows, room[1])

    def _room(self) -> tuple[Window, int] | None:
        """The window holding the box's reserved rows and the rows it got in
        this render, if they are at least the box's smallest height (the
        box sits over them); else None, and the box centers."""
        room = self._session._box_room()
        if room is None or self.view is None:
            return None
        key = (get_app().render_counter, room[1])
        if self._room_memo is None or self._room_memo[0] != key:
            size = get_app().output.get_size()
            self._room_memo = (key, room[1] >= self._least_rows(size.columns, size.rows))
        return room if self._room_memo[1] else None

    def _room_window(self) -> Window | None:
        room = self._room()
        return None if room is None else room[0]

    def _least_rows(self, width: int, max_rows: int) -> int:
        """The fewest rows the open dialog can show in: its frame, buttons
        and one body row, or the notice drawn in its place."""
        notice = self._notice(width, max_rows)
        if notice is not None:
            return min(self._notice_rows(notice, width), max_rows)
        return self._smallest(width, max_rows)[1]
