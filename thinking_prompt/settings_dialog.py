"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
Navigation: Up/Down move between settings (and, in an inline dialog, on to
the Save/Cancel rows), Tab/Shift-Tab too. Left/Right or Space change values,
Enter edits text in place. Ctrl+S saves, Escape cancels.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, Union

from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.key_bindings import KeyBindingsBase
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    Container,
    DynamicContainer,
    Float,
    HSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.processors import PasswordProcessor
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import Frame

from .dialog import ButtonConfig, Dialog
from .rows import MARKER, NO_MARKER, OptionGroup, RowControl, RowNavigator, has_focus
from .types import Placement


@dataclass
class SettingsItem(ABC):
    """Base class for all settings items."""
    key: str              # Unique identifier, used as dict key in result
    label: str            # Display label
    description: str = "" # Optional description shown below label
    default: Any = None


@dataclass
class InlineSelectItem(SettingsItem):
    """Inline select that cycles through options with Left/Right keys."""
    options: list[str] = field(default_factory=list)
    default: Any = None


@dataclass
class DropdownItem(SettingsItem):
    """Dropdown select with edit mode showing a scrollable list."""
    options: list[str] = field(default_factory=list)
    default: Any = None
    height: int = 4  # Number of visible items in dropdown
    width: int | None = 15  # Fixed width, or None for auto
    max_width: int | None = None  # Max width when auto-sizing


@dataclass
class CheckboxItem(SettingsItem):
    """Boolean toggle."""
    default: bool = False


@dataclass
class TextItem(SettingsItem):
    """Free text input."""
    default: str = ""
    password: bool = False
    edit_width: int = 15  # Width of text input field in edit mode


@dataclass
class ChecklistItem(SettingsItem):
    """Any number of options, one per line; the value is the checked ones, in option order."""
    options: list[str] = field(default_factory=list)
    default: Sequence[str] = ()


@dataclass
class RadioItem(SettingsItem):
    """One of several options, one per line; with no default nothing is picked."""
    options: list[str] = field(default_factory=list)
    default: str | None = None


T = TypeVar("T", bound=SettingsItem)

# Where settings values start: "labels" (two columns after the longest
# label, or description, see SettingsDialog), "right" (the row's right
# edge) or a column, the marker included.
AlignValues = Union[Literal["labels", "right"], int]

# The smallest value column: the marker, one label character and a space.
MIN_VALUE_COLUMN = len(MARKER) + 2


def _check_align_values(align: object) -> None:
    if align in ("labels", "right"):
        return
    if isinstance(align, int) and not isinstance(align, bool) and align >= MIN_VALUE_COLUMN:
        return
    raise ValueError(
        f'align_values must be "labels", "right" or a column of at least '
        f"{MIN_VALUE_COLUMN}, got {align!r}"
    )


@dataclass(frozen=True)
class _ValueColumn:
    """Where a form's values start in a row: at ``least``, or further
    right, as far as ``most``, while a value ``widest`` columns wide still
    fits before the row's last column (_layout_row's edge)."""

    least: int
    most: int = 0
    widest: int = 0

    def at(self, width: int) -> int:
        """The column in a row ``width`` columns wide."""
        return max(self.least, min(self.most, width - 1 - self.widest))


def _cut(text: str, columns: int) -> str:
    """``text`` in at most ``columns`` terminal columns, ending in "…" if cut."""
    if get_cwidth(text) <= columns:
        return text
    if columns < 1:
        return ""
    kept = ""
    for char in text:
        if get_cwidth(kept + char) > columns - 1:
            break
        kept += char
    return kept.rstrip() + "…"


def _justify(text: str, width: int, left: bool) -> str:
    """``text`` padded with spaces to ``width`` terminal columns, after it
    (``left``-justified) or before it."""
    padding = " " * max(0, width - get_cwidth(text))
    return text + padding if left else padding + text


def _columns(fragments: Sequence[tuple[str, str]]) -> int:
    """The terminal columns (style, text) fragments take."""
    return sum(get_cwidth(text) for _, text in fragments)


@dataclass(frozen=True)
class _RowValue:
    """A row's value as ``_layout_row`` takes it: its text, the field it
    normally takes (``left``- or right-justified), and the decoration
    fragments around the field. ``lead`` and ``trail`` are blank padding
    columns (in the value's style) beside it: unlike decoration, they give
    way, down to nothing, before the text is cut."""
    text: str
    style: str
    field: int
    left: bool = True
    before: tuple[tuple[str, str], ...] = ()
    after: tuple[tuple[str, str], ...] = ()
    lead: int = 0
    trail: int = 0

    def columns(self) -> int:
        """The columns the value takes in full: its decoration, padding and
        field, or its text where that is wider."""
        decoration = _columns(self.before) + _columns(self.after)
        return decoration + self.lead + self.trail + max(self.field, get_cwidth(self.text))

    def fragments(self, layout: _RowLayout) -> list[tuple[str, str]]:
        return [
            *self.before,
            (self.style, " " * layout.lead),
            (self.style, layout.text),
            (self.style, " " * layout.trail),
            *self.after,
        ]


@dataclass(frozen=True)
class _RowLayout:
    label: str   # as drawn, cut or not
    column: int  # where the value starts, its decoration included
    field: int   # the field width used
    text: str    # the value text as drawn, padded to the field
    lead: int = 0   # the value's leading padding as drawn
    trail: int = 0  # the trailing padding as drawn


def _layout_row(
    width: int,
    label: str,
    column: int | None,
    value: _RowValue,
    min_field: int | None = None,
) -> _RowLayout:
    """Lay a label/value row out in ``width`` terminal columns.

    The one rule for where a value is drawn, and so for the menu under it
    and the field that edits it. The row gives way in this order:

    1. the value at ``column``, in full, the label cut to keep a space;
    2. the value in full at the right edge (the row's last column but
       one), the label cut to fit before it, down to 3 columns;
    3. the label at 3 columns, the field shrunk to what is left, down to
       ``min_field`` (default: the text's width), then the padding;
    4. the value text cut with "…" to what is left, at least 1 column.

    The decoration stays throughout; the value's blank padding (``lead``,
    ``trail``) is kept while the row has room and shrinks, down to nothing,
    before the text is cut. Past that the row is clipped. A
    ``min_field`` beyond the text (an edited field) is kept by cutting the
    label below 3 columns first.
    """
    marker = get_cwidth(MARKER)
    text_width = get_cwidth(value.text)
    minimum = text_width if min_field is None else min_field
    decoration = _columns(value.before) + _columns(value.after)
    padding = value.lead + value.trail
    edge = width - 1
    keep = min(3, get_cwidth(label))
    full = max(value.field, text_width)

    def laid_out(label: str, start: int, field: int, lead: int = 0, trail: int = 0) -> _RowLayout:
        text = _justify(_cut(value.text, field), field, value.left)
        return _RowLayout(label, start, field, text, lead, trail)

    if column is not None and column + value.columns() <= edge:
        return laid_out(_cut(label, column - marker - 1), column, full, value.lead, value.trail)
    start = edge - value.columns()
    if start - marker - 1 >= keep:
        return laid_out(_cut(label, start - marker - 1), start, full, value.lead, value.trail)
    label = _cut(label, keep)
    start = marker + get_cwidth(label) + 1
    if edge - start - decoration < minimum and minimum > text_width:
        label = _cut(label, max(1, edge - decoration - minimum - marker - 1))
        start = marker + get_cwidth(label) + 1
    left = edge - start - decoration
    # The padding gives way once the field is down to its minimum.
    kept = max(0, min(padding, left - minimum))
    trail = min(value.trail, kept)
    lead = kept - trail
    return laid_out(label, start, max(1, left - kept), lead, trail)


def _cycled(options: list[str], value: Any, delta: int) -> Any:
    """The option ``delta`` steps from ``value``, clamped to the ends.

    With no current selection (no default, or a default that isn't an
    option) any step selects the first option: moving from index 0 would
    skip over it.
    """
    if not options:
        return value
    try:
        idx = options.index(value)
    except ValueError:
        return options[0]
    return options[max(0, min(len(options) - 1, idx + delta))]


def _selector_value(options: list[str], value: Any, value_style: str) -> _RowValue:
    """``◀ value ▶``: the arrows layer class:select-arrow over the value
    style; at either end the missing arrow's place is kept blank, as
    padding that gives way before the option is cut."""
    try:
        idx = options.index(value)
    except ValueError:
        idx = 0
    arrow_style = f"{value_style} class:select-arrow"
    first, last = idx == 0, idx == len(options) - 1
    text = str(value) if value else ""
    return _RowValue(
        text,
        value_style,
        get_cwidth(text),
        before=() if first else ((arrow_style, "◀ "),),
        after=() if last else ((arrow_style, " ▶"),),
        lead=2 if first else 0,
        trail=2 if last else 0,
    )


def _widest_selector(options: list[str], value: Any) -> int:
    """The most columns a ``◀ option ▶`` selector over ``options`` takes,
    showing any of them or ``value`` (a default can be none of them)."""
    return max(_selector_value(options, shown, "").columns() for shown in [*options, value])


class SettingControl(RowControl, ABC, Generic[T]):
    """Base class for setting controls with view/edit modes.

    Generic over the concrete SettingsItem subclass so subclasses get
    typed access to their item-specific fields (e.g. options, width).
    """

    def __init__(self, item: T) -> None:
        self._item: T = item
        self._value: Any = item.default
        self._editing = False
        self._has_focus = False
        # Where the value starts (set_value_column); None: the right edge.
        self._value_column: _ValueColumn | None = None

    @property
    def item(self) -> T:
        """The settings item this control represents."""
        return self._item

    @property
    def value(self) -> Any:
        """Current value of the setting."""
        return self._value

    @value.setter
    def value(self, val: Any) -> None:
        """Set the current value."""
        self._value = val

    @property
    def is_editing(self) -> bool:
        """Whether the control is in edit mode."""
        return self._editing

    def enter_edit_mode(self) -> None:
        """Enter edit mode. Override in subclasses that support editing."""
        pass

    def confirm_edit(self) -> None:
        """Confirm and exit edit mode. Override in subclasses."""
        self._editing = False

    def cancel_edit(self) -> None:
        """Cancel and exit edit mode. Override in subclasses."""
        self._editing = False

    def set_has_focus(self, has_focus: bool) -> None:
        """Update focus state (called by parent container)."""
        self._has_focus = has_focus

    def set_value_column(self, column: _ValueColumn | None) -> None:
        """Start the value at ``column`` of the row (counted with the marker,
        and depending on the row's width); None puts it at the row's right
        edge."""
        self._value_column = column

    def _column(self, width: int) -> int | None:
        """Where the value starts in a row ``width`` columns wide; None: the
        row's right edge."""
        return None if self._value_column is None else self._value_column.at(width)

    def widest_value(self) -> int:
        """The most columns this setting's value takes in full
        (_RowValue.columns): showing any of its options, or what it shows
        now (a text setting's value can outgrow it as it's edited); 0 with
        no value on the setting's row."""
        return 0

    @abstractmethod
    def create_content(self, width: int, height: int) -> UIContent:
        """Create the visual content for this control."""
        pass

    @abstractmethod
    def get_container(self) -> Container:
        """Return the container for this control (for use in layouts)."""
        pass

    def is_focusable(self) -> bool:
        return True

    @property
    def row_count(self) -> int:
        """Rows this setting takes: 1, or 2 with a description."""
        return 2 if self._item.description else 1

    def get_stops(self) -> list[Container]:
        """Where the cursor stops in this setting: one place per row the user acts on."""
        return [self.get_container()]

    def _check_focus(self) -> bool:
        """Check if this control has focus (for rendering).

        Default implementation checks self._window. Subclasses with
        multiple focusable windows should override this method.
        """
        try:
            app = get_app()
            window = getattr(self, "_window", None) or getattr(self, "_view_window", None)
            if window:
                return app.layout.has_focus(window)
            return self._has_focus
        except Exception:
            return self._has_focus

    def _build_setting_row(
        self,
        width: int,
        value: _RowValue,
        is_selected: bool,
    ) -> list[FormattedText]:
        """Build the standard setting row with optional description.

        ``value`` is laid out by _layout_row at the value column
        (set_value_column), or at the row's right edge with none. Returns a
        list of FormattedText lines (1 or 2 depending on description).
        """
        indicator = MARKER if is_selected else NO_MARKER
        indicator_style = "class:setting-indicator" if is_selected else ""
        label_style = "class:setting-label-selected" if is_selected else "class:setting-label"

        layout = _layout_row(width, self._item.label, self._column(width), value)
        padding = max(1, layout.column - get_cwidth(indicator) - get_cwidth(layout.label))

        row: list[tuple[str, str]] = [
            (indicator_style, indicator),
            (label_style, layout.label),
            ("", " " * padding),
            *value.fragments(layout),
        ]

        lines = [FormattedText(row)]

        if self._item.description:
            desc_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
            desc_row: list[tuple[str, str]] = [
                ("", "  "),
                (desc_style, self._item.description),
            ]
            lines.append(FormattedText(desc_row))

        return lines


class CheckboxControl(SettingControl[CheckboxItem]):
    """Checkbox control that toggles on Space/Enter."""

    def __init__(self, item: CheckboxItem) -> None:
        super().__init__(item)
        height = 2 if item.description else 1
        self._window = Window(self, height=height)

    @property
    def hints(self) -> frozenset[str]:
        return frozenset({"Space toggle"})

    def widest_value(self) -> int:
        return get_cwidth("false")  # wider than "true"

    def toggle(self) -> None:
        """Toggle the checkbox value."""
        self._value = not self._value

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the checkbox row."""
        is_selected = self._check_focus()

        if self._value:
            value_text = "true"
            value_style = "class:setting-value-true-selected" if is_selected else "class:setting-value-true"
        else:
            value_text = "false"
            value_style = "class:setting-value-false-selected" if is_selected else "class:setting-value-false"

        value = _RowValue(value_text, value_style, get_cwidth(value_text))
        lines = self._build_setting_row(width, value, is_selected)

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def get_container(self) -> Container:
        """Return cached window containing this control."""
        return self._window

    def get_key_bindings(self) -> KeyBindings:
        """Key bindings for checkbox."""
        kb = KeyBindings()

        @kb.add("space")
        @kb.add("enter")
        @kb.add("left")
        @kb.add("right")
        def _toggle(event: Any) -> None:
            self.toggle()

        return kb


class InlineSelectControl(SettingControl[InlineSelectItem]):
    """Inline select control that cycles through options with Left/Right keys."""

    def __init__(self, item: InlineSelectItem) -> None:
        super().__init__(item)
        height = 2 if item.description else 1
        self._window = Window(self, height=height)

    @property
    def hints(self) -> frozenset[str]:
        return frozenset({"←→ change"})

    def widest_value(self) -> int:
        return _widest_selector(self._item.options, self._value)

    def cycle(self, delta: int) -> None:
        """Move through options by delta (+1 or -1), clamped to boundaries."""
        self._value = _cycled(self._item.options, self._value, delta)

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the inline select row with left/right arrows."""
        is_selected = self._check_focus()
        value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        value = _selector_value(self._item.options, self._value, value_style)
        lines = self._build_setting_row(width, value, is_selected)

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def get_container(self) -> Container:
        """Return cached window containing this control."""
        return self._window

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("left")
        def _prev(event: Any) -> None:
            self.cycle(-1)

        @kb.add("right")
        @kb.add("space")
        def _next(event: Any) -> None:
            self.cycle(1)

        return kb


class DropdownControl(SettingControl[DropdownItem]):
    """Dropdown control with floating menu in edit mode."""

    def __init__(self, item: DropdownItem) -> None:
        super().__init__(item)
        self._original_value: Any = item.default
        self._selected_index = 0  # Index in dropdown list during edit
        self._scroll_offset = 0  # The menu's first option shown, kept by the menu as it draws
        self._app_ref: Any = None
        # Cache view-mode window for stable focus target
        height = 2 if item.description else 1
        self._view_window = Window(self, height=height)
        # Floating menu components (built lazily)
        self._menu_control = _DropdownMenuControl(self)
        self._menu_window: Window | None = None
        # Inline dialogs show a dropdown as a ←/→ selector, with no popup menu.
        self._inline = False

    def set_inline(self, inline: bool) -> None:
        """Show as a ←/→ selector (inline dialogs) instead of a popup menu."""
        self._inline = inline

    @property
    def hints(self) -> frozenset[str]:
        return frozenset({"←→ change"}) if self._inline else frozenset()

    def widest_value(self) -> int:
        if self._inline:
            return _widest_selector(self._item.options, self._value)
        shown = [*self._item.options, str(self._value) if self._value else ""]
        return max(self._menu_value(text, "").columns() for text in shown)

    def _menu_value(self, text: str, style: str) -> _RowValue:
        """``text`` within the dropdown's width (left-justified when it
        starts at a column, so the ▼ marks line up), then the indicator."""
        return _RowValue(
            text,
            style,
            self._get_dropdown_width(),
            left=self._value_column is not None,
            after=((style, " "), (f"{style} class:select-arrow", "▼")),
        )

    def cycle(self, delta: int) -> None:
        """Move through options by delta (+1 or -1), clamped to the ends."""
        self._value = _cycled(self._item.options, self._value, delta)

    def _preferred_menu_rows(self) -> int:
        """Option rows the menu asks for; it gets fewer when there is no room."""
        return max(1, min(len(self._item.options), self._item.height))

    def _check_focus(self) -> bool:
        """Check if this control has focus (for rendering)."""
        try:
            app = get_app()
            # Check if view window or menu has focus
            if app.layout.has_focus(self._view_window):
                return True
            return bool(self._menu_window and app.layout.has_focus(self._menu_window))
        except Exception:
            return self._has_focus

    def _get_dropdown_width(self) -> int:
        """Calculate dropdown width based on settings."""
        item = self._item
        if item.width is not None:
            return item.width
        # Auto-size based on longest option
        max_opt = max((len(opt) for opt in item.options), default=10)
        width = max_opt + 4  # Add padding for indicator
        if item.max_width is not None:
            width = min(width, item.max_width)
        return width

    def enter_edit_mode(self, app: Any = None) -> None:
        """Enter edit mode - show floating dropdown menu."""
        self._original_value = self._value
        # Set selected index to current value
        try:
            self._selected_index = self._item.options.index(self._value)
        except (ValueError, IndexError):
            self._selected_index = 0
        self._scroll_offset = 0
        self._editing = True
        self._app_ref = app
        if app:
            app.invalidate()

    def confirm_edit(self) -> None:
        """Confirm edit - save selected value."""
        if self._item.options and 0 <= self._selected_index < len(self._item.options):
            self._value = self._item.options[self._selected_index]
        self._editing = False
        if self._app_ref:
            self._app_ref.layout.focus(self._view_window)
            self._app_ref.invalidate()

    def cancel_edit(self) -> None:
        """Cancel edit - restore original value."""
        self._value = self._original_value
        self._editing = False
        if self._app_ref:
            self._app_ref.layout.focus(self._view_window)
            self._app_ref.invalidate()

    def _move_selection(self, delta: int) -> None:
        """Move selection by delta, clamping to bounds."""
        new_index = self._selected_index + delta
        new_index = max(0, min(new_index, len(self._item.options) - 1))
        self._selected_index = new_index

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the dropdown row with down arrow indicator."""
        is_selected = self._check_focus()
        value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        if self._inline:
            value = _selector_value(self._item.options, self._value, value_style)
        else:
            value = self._menu_value(str(self._value) if self._value else "", value_style)

        lines = self._build_setting_row(width, value, is_selected)
        # The menu opens under the value, where this row draws it (get_float).
        # prompt_toolkit's menu position counts characters into the line, not
        # terminal columns: those drawn ahead of it.
        drawn = 2 + len(value.after)
        ahead = lines[0][: len(lines[0]) - drawn]
        menu_position = Point(x=sum(len(text) for _, text, *_ in ahead), y=0)

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines), menu_position=menu_position)

    def _build_menu(self) -> None:
        """Build the dropdown menu components (called lazily)."""
        if self._menu_window is not None:
            return

        # Its height is the terminal's to give: the options asked for, fewer
        # where there's no room (the menu then scrolls and shows a scrollbar).
        self._menu_window = Window(
            self._menu_control,
            width=self._get_dropdown_width(),
            height=Dimension(min=1, preferred=self._preferred_menu_rows()),
            style="class:setting-dropdown",
        )

    def get_container(self) -> Container:
        """Return the view window (dropdown Float is separate)."""
        return self._view_window

    def get_float(self) -> Float:
        """Return the Float for the dropdown menu (to be added at dialog level)."""
        self._build_menu()
        assert self._menu_window is not None  # _build_menu sets this

        framed_menu = Frame(
            body=self._menu_window,
            style="class:setting-dropdown-border",
        )

        # Directly under its row, at the value: the menu position the row gives
        # (create_content). prompt_toolkit shrinks the float where there is
        # no room below, or flips it above the row when there is more there.
        return Float(
            content=ConditionalContainer(
                content=framed_menu,
                filter=Condition(lambda: self._editing),
            ),
            attach_to_window=self._view_window,
            xcursor=True,
            ycursor=True,
        )

    def get_key_bindings(self) -> KeyBindings:
        """Popup menu keys in a box; ←/→ (and Space) cycle inline."""
        kb = KeyBindings()
        inline = Condition(lambda: self._inline)
        popup_closed = Condition(lambda: not self._inline and not self._editing)
        editing = Condition(lambda: self._editing)

        @kb.add("enter", filter=popup_closed)
        @kb.add("space", filter=popup_closed)
        def _enter_edit(event: Any) -> None:
            self.enter_edit_mode(event.app)

        # Edit mode bindings (active when the popup is open)
        @kb.add("up", filter=editing)
        def _up(event: Any) -> None:
            self._move_selection(-1)

        @kb.add("down", filter=editing)
        def _down(event: Any) -> None:
            self._move_selection(1)

        @kb.add("enter", filter=editing)
        def _confirm(event: Any) -> None:
            self.confirm_edit()

        @kb.add("escape", filter=editing)
        def _cancel(event: Any) -> None:
            self.cancel_edit()

        @kb.add("left", filter=inline)
        def _prev(event: Any) -> None:
            self.cycle(-1)

        @kb.add("right", filter=inline)
        @kb.add("space", filter=inline)
        def _next(event: Any) -> None:
            self.cycle(1)

        return kb


class _DropdownMenuControl(UIControl):
    """Internal UIControl for rendering floating dropdown menu."""

    def __init__(self, dropdown: DropdownControl) -> None:
        self._dropdown = dropdown

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the options that fit ``height`` rows, scrolled to keep the
        selected one in view, with a scrollbar when not all of them show."""
        dropdown = self._dropdown
        options = dropdown._item.options
        selected = dropdown._selected_index
        count = len(options)
        height = max(1, height)

        scrolls = count > height
        text_width = max(1, width - 1) if scrolls else width
        offset = min(dropdown._scroll_offset, max(0, count - height))
        if selected < offset:
            offset = selected
        elif selected >= offset + height:
            offset = selected - height + 1
        dropdown._scroll_offset = offset

        # The scrollbar's thumb: its size and place along the track.
        thumb = max(1, height * height // count) if scrolls else 0
        thumb_top = offset * (height - thumb) // (count - height) if scrolls else 0

        lines = []
        for row, i in enumerate(range(offset, min(count, offset + height))):
            opt = options[i]
            style = "class:setting-dropdown-selected" if i == selected else "class:setting-dropdown-item"
            text = opt[:text_width] if len(opt) > text_width else opt.ljust(text_width)
            fragments = [(style, text)]
            if scrolls:
                on_thumb = thumb_top <= row < thumb_top + thumb
                fragments.append(("class:scrollbar.button" if on_thumb else "class:scrollbar.background", " "))
            lines.append(FormattedText(fragments))

        return UIContent(get_line=lambda i: lines[i], line_count=len(lines))

    def is_focusable(self) -> bool:
        return False  # Menu is not focusable, control handles keys


class TextControl(SettingControl[TextItem]):
    """Text input control with view/edit modes."""

    def __init__(self, item: TextItem) -> None:
        super().__init__(item)
        self._original_value: str = item.default
        self._buffer = Buffer(multiline=False)
        self._app_ref: Any = None  # Store app reference for focus management
        # Cache view-mode window for stable focus target
        height = 2 if item.description else 1
        self._view_window = Window(self, height=height)
        # Cache edit container for stable focus
        self._edit_container: Container | None = None
        self._buffer_window: Window | None = None
        self._container = DynamicContainer(self._get_current_container)

    def enter_edit_mode(self, app: Any = None) -> None:
        """Enter edit mode - populate buffer with current value."""
        self._original_value = self._value
        self._buffer.text = self._value or ""
        self._buffer.cursor_position = len(self._buffer.text)
        self._editing = True
        self._app_ref = app
        # Build edit container (creates _buffer_window if not exists)
        self._build_edit_container()
        # Focus the buffer window
        if app and self._buffer_window:
            app.layout.focus(self._buffer_window)

    def confirm_edit(self) -> None:
        """Confirm edit - save buffer to value."""
        self._value = self._buffer.text
        self._editing = False
        # Restore focus to view window
        if self._app_ref:
            self._app_ref.layout.focus(self._view_window)

    def cancel_edit(self) -> None:
        """Cancel edit - restore original value."""
        self._value = self._original_value
        self._editing = False
        # Restore focus to view window
        if self._app_ref:
            self._app_ref.layout.focus(self._view_window)

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the text row in view mode."""
        if self._editing:
            # Edit mode handled by get_container's DynamicContainer
            return UIContent(get_line=lambda i: FormattedText([]), line_count=0)

        is_selected = self._check_focus()
        if not self._value:
            value_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
        else:
            value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        lines = self._build_setting_row(width, self._row_value(value_style), is_selected)

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def _shown_value(self) -> str:
        """The value as its row shows it."""
        if self._item.password and self._value:
            text = "••••••"
        elif self._value:
            text = str(self._value)
        else:
            text = "(empty)"
        return text

    def widest_value(self) -> int:
        return self._row_value("").columns()

    def _row_value(self, style: str) -> _RowValue:
        """The value within edit_width: left-justified at a value column,
        else right-justified."""
        return _RowValue(
            self._shown_value(), style, self._item.edit_width, left=self._value_column is not None
        )

    def get_container(self) -> Container:
        """Return the (cached) container that switches between view/edit modes."""
        return self._container

    def _get_current_container(self) -> Container:
        """Return appropriate container based on edit state."""
        if self._editing:
            return self._build_edit_container()
        else:
            return self._view_window

    def _build_edit_container(self) -> Container:
        """Build the edit mode container with buffer input (cached)."""
        if self._edit_container is not None:
            return self._edit_container

        edit_kb = KeyBindings()

        @edit_kb.add("enter")
        def _confirm(event: Any) -> None:
            self.confirm_edit()

        @edit_kb.add("escape")
        def _cancel(event: Any) -> None:
            self.cancel_edit()

        buffer_control = BufferControl(
            buffer=self._buffer,
            key_bindings=edit_kb,
            input_processors=[PasswordProcessor()] if self._item.password else None,
        )

        # Cache the buffer window for focus management. It takes the width
        # the row gives it; the buffer scrolls long text sideways.
        self._buffer_window = Window(buffer_control, style="class:text-area")
        row = _EditRow(self, self._buffer_window)

        if self._item.description:
            desc_row = Window(
                FormattedTextControl(lambda: FormattedText([
                    ("", "  "),
                    ("class:setting-desc-selected", self._item.description),
                ])),
                height=1,
            )
            self._edit_container = HSplit([row, desc_row])
        else:
            self._edit_container = row

        return self._edit_container

    def get_key_bindings(self) -> KeyBindings:
        """Key bindings for view mode (Enter to edit)."""
        kb = KeyBindings()

        @kb.add("enter", filter=Condition(lambda: not self._editing))
        def _enter_edit(event: Any) -> None:
            self.enter_edit_mode(event.app)

        return kb


class _EditRow(Container):
    """A text setting's row while its value is edited: the label, cut with
    "…" to fit, then the input field where the row draws the value
    (_layout_row), at the width it gives. Laid out from the row's width at
    each redraw, so a row too narrow for the column keeps the field, as it
    keeps the value. The field keeps min(8, edit_width) columns: the label
    is cut further to keep them."""

    def __init__(self, control: TextControl, field: Window) -> None:
        self._control = control
        self._field = field
        self._label = Window(_MarkedLabel(control.item))
        self._rest = Window()

    def reset(self) -> None:
        for child in self.get_children():
            child.reset()

    def preferred_width(self, max_available_width: int) -> Dimension:
        item = self._control.item
        column = self._control._column(max_available_width)
        if column is None:
            column = get_cwidth(MARKER) + get_cwidth(item.label) + 2
        return Dimension(min=0, preferred=column + item.edit_width)

    def preferred_height(self, width: int, max_available_height: int) -> Dimension:
        return Dimension.exact(1)

    def write_to_screen(
        self,
        screen: Screen,
        mouse_handlers: MouseHandlers,
        write_position: WritePosition,
        parent_style: str,
        erase_bg: bool,
        z_index: int | None,
    ) -> None:
        width = write_position.width
        control = self._control
        edit_width = control.item.edit_width
        layout = _layout_row(
            width,
            control.item.label,
            control._column(width),
            # The field doesn't depend on the buffer: edit_width, scrolling
            # long text, whatever the text (or password) is.
            _RowValue("", "", edit_width, left=control._value_column is not None),
            min_field=min(8, edit_width),
        )
        start = max(0, min(layout.column, width))
        field = min(layout.field, width - start)
        x = write_position.xpos
        for child, child_width in ((self._label, start), (self._field, field), (self._rest, width - start - field)):
            child.write_to_screen(
                screen,
                mouse_handlers,
                WritePosition(x, write_position.ypos, child_width, write_position.height),
                parent_style,
                erase_bg,
                z_index,
            )
            x += child_width

    def get_children(self) -> list[Container]:
        return [self._label, self._field, self._rest]


class _MarkedLabel(UIControl):
    """A highlighted setting's label after the marker, cut with "…" to keep
    a blank column at the end of the width it's drawn in."""

    def __init__(self, item: SettingsItem) -> None:
        self._item = item

    def create_content(self, width: int, height: int) -> UIContent:
        label = _cut(self._item.label, width - get_cwidth(MARKER) - 1)
        line = FormattedText([
            ("class:setting-indicator", MARKER),
            ("class:setting-label-selected", label),
        ])
        return UIContent(get_line=lambda i: line, line_count=1)


class OptionsControl(SettingControl[Any]):
    """A check list or radio list setting: its label row, then one OptionRow
    per option. The options are the cursor stops; the label takes no focus."""

    def __init__(self, item: ChecklistItem | RadioItem) -> None:
        super().__init__(item)
        if isinstance(item, ChecklistItem):
            self._group = OptionGroup(item.options, multiple=True, selected=list(item.default), indent=2)
        else:
            picked = [item.default] if item.default is not None else []
            self._group = OptionGroup(item.options, multiple=False, selected=picked, indent=2)
        self._label_window = Window(self, height=2 if item.description else 1)
        self._container = HSplit([self._label_window, *(row.window for row in self._group.rows)])

    @property
    def value(self) -> Any:
        """The checked options (check list) or the picked one (radio list)."""
        return self._group.checked if self._group.multiple else self._group.picked

    @value.setter
    def value(self, val: Any) -> None:
        if self._group.multiple:
            self._group.select(list(val))
        else:
            self._group.select([] if val is None else [val])

    @property
    def row_count(self) -> int:
        return super().row_count + len(self._group.rows)

    def is_focusable(self) -> bool:
        return False  # the label row; the option rows take focus

    def get_container(self) -> Container:
        return self._container

    def get_stops(self) -> list[Container]:
        return [row.window for row in self._group.rows]

    def create_content(self, width: int, height: int) -> UIContent:
        """The label row (and description), highlighted while an option has focus."""
        selected = any(has_focus(row.window) for row in self._group.rows)
        label_style = "class:setting-label-selected" if selected else "class:setting-label"
        lines = [FormattedText([("", NO_MARKER), (label_style, self._item.label)])]
        if self._item.description:
            desc_style = "class:setting-desc-selected" if selected else "class:setting-desc"
            lines.append(FormattedText([("", "  "), (desc_style, self._item.description)]))

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))


class SettingsDialog(Dialog):
    """
    A settings dialog using individual controls per setting type.

    Navigation:
    - Up/Down: move between settings; inline, on to the Save/Cancel rows
    - Tab/Shift-Tab: through the settings, then (box) to the buttons
    - Left/Right or Space: change value (selectors, checkboxes)
    - Enter: edit text in place (box dropdowns: open the menu)
    - Ctrl+S: save and close
    - Escape: cancel edit or close dialog

    Values start two columns after the longest label or description by
    default (align_values="labels"), though a description too long to leave
    room for the widest value runs on under the values; "right" puts them
    at the row's right edge, and a number at that column, cutting longer
    labels with "…".

    Returns a dictionary of changed values when closed, or None if cancelled.
    """

    def __init__(
        self,
        title: str,
        items: list[SettingsItem],
        can_cancel: bool = True,
        *,
        width: int | None = 60,
        top: int | None = None,
        max_height: int | None = None,
        align_values: AlignValues = "labels",
        placement: Placement | None = None,
    ) -> None:
        _check_align_values(align_values)
        # escapable: with can_cancel=False there is no cancel concept, so
        # Escape is disabled (the Done button is the only way out).
        # escape_result stays the default None, so nothing but a dict or None
        # can come back from show_settings_dialog().
        super().__init__(
            title, width=width, top=top, max_height=max_height, escapable=can_cancel, placement=placement
        )
        self._items = items
        self._can_cancel = can_cancel
        self._align_values = align_values

        # Create controls
        self._controls: list[SettingControl] = [self._create_control(item) for item in items]

        # Original values for change detection, as each control reports them.
        self._original_values: dict[str, Any] = {c.item.key: c.value for c in self._controls}

    def _value_column(self) -> _ValueColumn | None:
        """Where values start (see align_values); None: the row's right edge."""
        if self._align_values == "right":
            return None
        if self._align_values != "labels":
            return _ValueColumn(int(self._align_values))
        # Check and radio lists have their label, and description, on rows
        # with no value. A description starts where labels do (under the
        # marker's columns).
        rows = [c for c in self._controls if not isinstance(c, OptionsControl)]

        def after(texts: Iterable[str]) -> int:
            return get_cwidth(MARKER) + max((get_cwidth(t) for t in texts), default=0) + 2

        return _ValueColumn(
            after(c.item.label for c in rows),
            after(c.item.description for c in rows),
            max((c.widest_value() for c in rows), default=0),
        )

    def _create_control(self, item: SettingsItem) -> SettingControl:
        """Create the appropriate control for a settings item."""
        if isinstance(item, (ChecklistItem, RadioItem)):
            return OptionsControl(item)
        elif isinstance(item, CheckboxItem):
            return CheckboxControl(item)
        elif isinstance(item, DropdownItem):
            return DropdownControl(item)
        elif isinstance(item, InlineSelectItem):
            return InlineSelectControl(item)
        elif isinstance(item, TextItem):
            return TextControl(item)
        else:
            raise ValueError(f"Unknown settings item type: {type(item)}")

    def _any_editing(self) -> bool:
        """Check if any control is in edit mode."""
        return any(c.is_editing for c in self._controls)

    def _stops(self) -> list[Container]:
        """Every cursor stop in the form, top to bottom."""
        return [stop for control in self._controls for stop in control.get_stops()]

    def _is_editing(self) -> bool:
        return self._any_editing()

    def _settings_key_bindings(self) -> KeyBindingsBase:
        """Ctrl+S saves. In a box, ↑↓ walk the settings, and so do Tab /
        Shift+Tab, Tab going on to the buttons after the last setting.
        Inline, the dialog's own cursor walks settings and actions alike."""
        idle = Condition(lambda: not self._any_editing())
        kb = KeyBindings()

        @kb.add("c-s", filter=idle)
        def _save(event: Any) -> None:
            self._on_save()

        if self._placement == "inline":
            return kb

        navigator = RowNavigator(self._stops, is_editing=self._any_editing)

        @kb.add("tab", filter=idle)
        def _tab_next(event: Any) -> None:
            stops = self._stops()
            index = navigator.index(event.app.layout)
            if index is not None and index < len(stops) - 1:
                event.app.layout.focus(stops[index + 1])
            else:
                # After the last setting: on to the buttons (no wrap back)
                self._clear_focus_indicators()
                event.app.layout.focus_next()

        @kb.add("s-tab", filter=idle)
        def _tab_prev(event: Any) -> None:
            # At the first setting: stays put (no wrap to the buttons)
            navigator.move(event.app.layout, -1)

        return merge_key_bindings([navigator.key_bindings(), kb])

    def _clear_focus_indicators(self) -> None:
        """Clear all focus indicators (when leaving controls area)."""
        for control in self._controls:
            control.set_has_focus(False)

    def _get_changed_values(self) -> dict[str, Any]:
        """Return only values that differ from original."""
        changed = {}
        for control in self._controls:
            key = control.item.key
            if control.value != self._original_values.get(key):
                changed[key] = control.value
        return changed

    def _on_save(self) -> None:
        """Handle save - return changed values."""
        self.set_result(self._get_changed_values())

    def build_body(self) -> Container:
        """The settings, one control each, in an HSplit with their key bindings."""
        if not self._controls:
            return Window(height=1)

        inline = self._placement == "inline"

        # Set initial focus indicator on first control
        self._controls[0].set_has_focus(True)
        for control in self._controls:
            if isinstance(control, DropdownControl):
                control.set_inline(inline)
        # After set_inline: an inline dropdown's value is a selector.
        column = self._value_column()
        for control in self._controls:
            control.set_value_column(column)

        # Use empty window_too_small to suppress brief "Window too small" message during layout
        controls_container = HSplit(
            [control.get_container() for control in self._controls],
            key_bindings=self._settings_key_bindings(),
            window_too_small=Window(),
        )
        if inline:
            return controls_container

        return controls_container

    def _screen_floats(self) -> list[Float]:
        """A box's dropdown menus float over the whole screen, not the form,
        so each is sized by the room the terminal has around its row."""
        if self._placement == "inline":
            return []
        return [c.get_float() for c in self._controls if isinstance(c, DropdownControl)]

    def get_buttons(self) -> list[ButtonConfig]:
        """Return dialog buttons."""
        if self._can_cancel:
            return [
                ButtonConfig("Save", handler=self._on_save),
                ButtonConfig("Cancel", handler=self.cancel),
            ]
        return [ButtonConfig("Done", handler=self._on_save)]
