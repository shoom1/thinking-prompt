"""
Form fields for dialogs (Dialog.fields): the Field classes that describe
them and the row controls that draw and edit them.

Up/Down move between rows, Left/Right or Space change a value, Enter edits
text in place (in a box, opens a dropdown's menu; in a choice list, starts
picking), Escape ends an edit.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, Union

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition, FilterOrBool
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_bindings import KeyBindingsBase
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    Container,
    DynamicContainer,
    Float,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.processors import PasswordProcessor
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import Frame

from .rows import MARKER, NO_MARKER, OptionGroup, RowControl, RowNavigator, has_focus
from .types import Placement


@dataclass(frozen=True)
class Field(ABC):
    """A dialog's form field (Dialog.fields). Frozen: a list of fields can be
    shared by many dialogs (a class attribute), each keeping its own values.

    Attributes:
        key: The field's key in Dialog.values; unique within its dialog.
        label: Shown on the field's row. A check or radio list with no
            label and no description shows just its options.
        description: Shown under the label (optional).
        default: The field's starting value.
    """
    key: str
    label: str
    description: str = ""
    default: Any = None


@dataclass(frozen=True)
class SelectField(Field):
    """One of ``options``, stepped through in place with ←/→ (``◀ medium ▶``)."""
    options: list[str] = field(default_factory=list)
    default: Any = None


@dataclass(frozen=True)
class DropdownField(Field):
    """One of ``options``. In a box, Enter opens a menu of them; inline, it's
    a ←/→ selector. ``height``: the menu's rows; ``width``: its columns
    (None: the widest option's, at most ``max_width``)."""
    options: list[str] = field(default_factory=list)
    default: Any = None
    height: int = 4
    width: int | None = 15
    max_width: int | None = None


@dataclass(frozen=True)
class CheckboxField(Field):
    """True or false, toggled with Space, Enter or ←/→."""
    default: bool = False


@dataclass(frozen=True)
class TextField(Field):
    """Free text, edited in place with Enter; ``password`` shows it as dots.
    ``edit_width``: the edit field's columns."""
    default: str = ""
    password: bool = False
    edit_width: int = 15


@dataclass(frozen=True)
class ChecklistField(Field):
    """Any number of options, one per line; the value is the checked ones, in option order."""
    options: list[str] = field(default_factory=list)
    default: Sequence[str] = ()


@dataclass(frozen=True)
class RadioField(Field):
    """One of several options, one per line; with no default nothing is picked."""
    options: list[str] = field(default_factory=list)
    default: str | None = None


@dataclass(frozen=True)
class ChoiceField(Field):
    """One of ``options``, one per line, like prompt_toolkit's choice(): the
    pick is shown in bold, with ❯ while the cursor is on it, not a radio
    mark. It starts on ``default`` (the first option if that isn't one).
    In a form, Enter starts picking, ↑↓ move the pick and Enter keeps it
    (Escape puts it back). As a dialog's only field it is always picking:
    ↑↓ move the pick and Enter presses the dialog's first button."""
    options: list[str] = field(default_factory=list)
    default: str | None = None

    def __post_init__(self) -> None:
        if not self.options:
            raise ValueError(f"ChoiceField {self.key!r} needs at least one option")


T = TypeVar("T", bound=Field)

# Where field values start: "labels" (two columns after the longest label or
# description), "right" (the row's right edge) or a column, the marker included.
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


def _add_selector_keys(kb: KeyBindings, cycle: Callable[[int], None], when: FilterOrBool = True) -> None:
    """A selector's keys: ←/→ step back and forward through the options,
    Space forward."""

    @kb.add("left", filter=when)
    def _prev(event: Any) -> None:
        cycle(-1)

    @kb.add("right", filter=when)
    @kb.add("space", filter=when)
    def _next(event: Any) -> None:
        cycle(1)


def _description(description: str, selected: bool) -> FormattedText:
    """A field's description row, under its label."""
    style = "class:field-desc-selected" if selected else "class:field-desc"
    return FormattedText([("", "  "), (style, description)])


def _content(lines: list[FormattedText], menu_position: Point | None = None) -> UIContent:
    """UIContent showing ``lines``."""

    def get_line(i: int) -> FormattedText:
        return lines[i] if i < len(lines) else FormattedText([])

    return UIContent(get_line=get_line, line_count=len(lines), menu_position=menu_position)


class FieldControl(RowControl, ABC, Generic[T]):
    """Base class for field controls with view/edit modes.

    Generic over the concrete Field subclass so subclasses get
    typed access to their item-specific fields (e.g. options, width).
    """

    def __init__(self, item: T) -> None:
        self._item: T = item
        self._value: Any = item.default
        self._editing = False
        # Where the value starts (set_value_column); None: the right edge.
        self._value_column: _ValueColumn | None = None
        # The field's row, and its description (a text field shows its
        # edit row in its place while editing).
        self._window = Window(self, height=2 if item.description else 1)

    @property
    def item(self) -> T:
        """The Field this control shows."""
        return self._item

    @property
    def value(self) -> Any:
        """Current value of the field."""
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

    def abandon_edit(self) -> None:
        """End an edit left open (the dialog closed mid-edit): the value
        goes back as cancel_edit() would leave it, but focus stays where it
        is. Override where cancelling restores a value."""
        self._editing = False

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
        """The most columns this field's value takes in full
        (_RowValue.columns): showing any of its options, or what it shows
        now (a text field's value can outgrow it as it's edited); 0 with
        no value on the field's row."""
        return 0

    def preferred_width(self, max_available_width: int) -> int:
        """The columns this field's rows take uncut, so an auto-width box is
        wide enough for them: the marker, the label, the gap and the widest
        value (from the value column when one is set, which counts the
        marker, the longest label and the gap), the row's last column (see
        _layout_row) and, wider still, the description row."""
        widest = self.widest_value()
        if self._value_column is None:
            row = get_cwidth(MARKER) + get_cwidth(self._item.label) + 2 + widest
        else:
            row = self._value_column.least + widest + 1
        description = self._item.description
        return max(row, 2 + get_cwidth(description) if description else 0)

    @abstractmethod
    def create_content(self, width: int, height: int) -> UIContent:
        """Create the visual content for this control."""
        pass

    def get_container(self) -> Container:
        """The container this field is drawn in (for use in layouts): its row."""
        return self._window

    @property
    def row_count(self) -> int:
        """Rows this field takes: 1, or 2 with a description."""
        return 2 if self._item.description else 1

    def get_stops(self) -> list[Container]:
        """Where the cursor stops in this field: one place per row the user acts on."""
        return [self.get_container()]

    def start_stop(self) -> Container:
        """Where the cursor lands entering this field: its first stop."""
        return self.get_stops()[0]

    def _check_focus(self) -> bool:
        """Whether the field's row has focus (it's drawn highlighted)."""
        return has_focus(self._window)

    def _build_row(
        self,
        width: int,
        value: _RowValue,
        is_selected: bool,
    ) -> list[FormattedText]:
        """Build the standard field row with optional description.

        ``value`` is laid out by _layout_row at the value column
        (set_value_column), or at the row's right edge with none. Returns a
        list of FormattedText lines (1 or 2 depending on description).
        """
        indicator = MARKER if is_selected else NO_MARKER
        indicator_style = "class:field-indicator" if is_selected else ""
        label_style = "class:field-label-selected" if is_selected else "class:field-label"

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
            lines.append(_description(self._item.description, is_selected))
        return lines


class CheckboxFieldControl(FieldControl[CheckboxField]):
    """Checkbox control that toggles on Space/Enter."""

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
            value_style = "class:field-value-true-selected" if is_selected else "class:field-value-true"
        else:
            value_text = "false"
            value_style = "class:field-value-false-selected" if is_selected else "class:field-value-false"
        value = _RowValue(value_text, value_style, get_cwidth(value_text))
        return _content(self._build_row(width, value, is_selected))

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


class SelectFieldControl(FieldControl[SelectField]):
    """Inline select control that cycles through options with Left/Right keys."""

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
        value_style = "class:field-value-selected" if is_selected else "class:field-value"
        value = _selector_value(self._item.options, self._value, value_style)
        return _content(self._build_row(width, value, is_selected))

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        _add_selector_keys(kb, self.cycle)
        return kb


class DropdownFieldControl(FieldControl[DropdownField]):
    """Dropdown control with floating menu in edit mode."""

    def __init__(self, item: DropdownField) -> None:
        super().__init__(item)
        self._original_value: Any = item.default
        self._selected_index = 0  # Index in dropdown list during edit
        self._scroll_offset = 0  # The menu's first option shown, kept by the menu as it draws
        self._app_ref: Any = None
        # The popup menu. Its height is the terminal's to give: the options
        # asked for, fewer where there's no room (the menu then scrolls and
        # shows a scrollbar).
        self._menu_window = Window(
            _DropdownMenuControl(self),
            width=self._get_dropdown_width(),
            height=Dimension(min=1, preferred=self._preferred_menu_rows()),
            style="class:field-dropdown",
        )
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

    def _get_dropdown_width(self) -> int:
        """Calculate dropdown width based on the field."""
        item = self._item
        if item.width is not None:
            return item.width
        # Auto-size based on longest option
        max_opt = max((get_cwidth(opt) for opt in item.options), default=10)
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
            self._app_ref.layout.focus(self._window)
            self._app_ref.invalidate()

    def abandon_edit(self) -> None:
        self._value = self._original_value
        self._editing = False

    def cancel_edit(self) -> None:
        """Cancel edit - restore original value."""
        self.abandon_edit()
        if self._app_ref:
            self._app_ref.layout.focus(self._window)
            self._app_ref.invalidate()

    def _move_selection(self, delta: int) -> None:
        """Move selection by delta, clamping to bounds."""
        new_index = self._selected_index + delta
        new_index = max(0, min(new_index, len(self._item.options) - 1))
        self._selected_index = new_index

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the dropdown row with down arrow indicator."""
        is_selected = self._check_focus()
        value_style = "class:field-value-selected" if is_selected else "class:field-value"

        if self._inline:
            value = _selector_value(self._item.options, self._value, value_style)
        else:
            value = self._menu_value(str(self._value) if self._value else "", value_style)

        lines = self._build_row(width, value, is_selected)
        # The menu opens under the value, where this row draws it (get_float).
        # prompt_toolkit's menu position counts characters into the line, not
        # terminal columns: those drawn ahead of it.
        drawn = 2 + len(value.after)
        ahead = lines[0][: len(lines[0]) - drawn]
        return _content(lines, Point(x=sum(len(text) for _, text, *_ in ahead), y=0))

    def get_float(self) -> Float:
        """Return the Float for the dropdown menu (to be added at dialog level)."""
        framed_menu = Frame(
            body=self._menu_window,
            style="class:field-dropdown-border",
        )

        # Directly under its row, at the value: the menu position the row gives
        # (create_content). prompt_toolkit shrinks the float where there is
        # no room below, or flips it above the row when there is more there.
        return Float(
            content=ConditionalContainer(
                content=framed_menu,
                filter=Condition(lambda: self._editing),
            ),
            attach_to_window=self._window,
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

        _add_selector_keys(kb, self.cycle, inline)
        return kb


class _DropdownMenuControl(UIControl):
    """Internal UIControl for rendering floating dropdown menu."""

    def __init__(self, dropdown: DropdownFieldControl) -> None:
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
            style = "class:field-dropdown-selected" if i == selected else "class:field-dropdown-item"
            # Cut and padded in terminal columns: a wide character takes two.
            text = _justify(_cut(opt, text_width), text_width, True)
            fragments = [(style, text)]
            if scrolls:
                on_thumb = thumb_top <= row < thumb_top + thumb
                fragments.append(("class:scrollbar.button" if on_thumb else "class:scrollbar.background", " "))
            lines.append(FormattedText(fragments))

        return UIContent(get_line=lambda i: lines[i], line_count=len(lines))

    def is_focusable(self) -> bool:
        return False  # Menu is not focusable, control handles keys


class TextFieldControl(FieldControl[TextField]):
    """Text input control with view/edit modes."""

    def __init__(self, item: TextField) -> None:
        super().__init__(item)
        self._original_value: str = item.default
        self._buffer = Buffer(multiline=False)
        self._app_ref: Any = None  # Store app reference for focus management
        # The input field. It takes the width the row gives it; the buffer
        # scrolls long text sideways.
        self._buffer_window = Window(
            BufferControl(
                buffer=self._buffer,
                key_bindings=self._edit_key_bindings(),
                input_processors=[PasswordProcessor()] if item.password else None,
            ),
            style="class:text-area",
        )
        self._edit_container = self._build_edit_container()
        self._container = DynamicContainer(self._get_current_container)

    def enter_edit_mode(self, app: Any = None) -> None:
        """Enter edit mode - populate buffer with current value."""
        self._original_value = self._value
        self._buffer.text = self._value or ""
        self._buffer.cursor_position = len(self._buffer.text)
        self._editing = True
        self._app_ref = app
        if app:
            app.layout.focus(self._buffer_window)
            # The row swapped for the edit row: keys find the dialog's
            # bindings through parent links, which only a redraw refreshes.
            app.layout.update_parents_relations()

    def confirm_edit(self) -> None:
        """Confirm edit - save buffer to value."""
        self._value = self._buffer.text
        self._editing = False
        # Restore focus to the field's row
        if self._app_ref:
            self._app_ref.layout.focus(self._window)
            self._app_ref.layout.update_parents_relations()

    def abandon_edit(self) -> None:
        self._value = self._original_value
        self._editing = False

    def cancel_edit(self) -> None:
        """Cancel edit - restore original value."""
        self.abandon_edit()
        # Restore focus to the field's row
        if self._app_ref:
            self._app_ref.layout.focus(self._window)
            self._app_ref.layout.update_parents_relations()

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the text row in view mode."""
        if self._editing:
            # Edit mode handled by get_container's DynamicContainer
            return _content([])

        is_selected = self._check_focus()
        if not self._value:
            value_style = "class:field-desc-selected" if is_selected else "class:field-desc"
        else:
            value_style = "class:field-value-selected" if is_selected else "class:field-value"
        return _content(self._build_row(width, self._row_value(value_style), is_selected))

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
        """The edit row while editing, else the field's row."""
        return self._edit_container if self._editing else self._window

    def _edit_key_bindings(self) -> KeyBindings:
        """The input field's keys: Enter keeps the edit, Escape drops it."""
        kb = KeyBindings()

        @kb.add("enter")
        def _confirm(event: Any) -> None:
            self.confirm_edit()

        @kb.add("escape")
        def _cancel(event: Any) -> None:
            self.cancel_edit()

        return kb

    def _build_edit_container(self) -> Container:
        """The edit row (the input field where the value was drawn), and the
        description under it."""
        row = _EditRow(self, self._buffer_window)
        if not self._item.description:
            return row
        description = Window(
            FormattedTextControl(lambda: _description(self._item.description, True)), height=1
        )
        return HSplit([row, description])

    def get_key_bindings(self) -> KeyBindings:
        """Key bindings for view mode (Enter to edit)."""
        kb = KeyBindings()

        @kb.add("enter", filter=Condition(lambda: not self._editing))
        def _enter_edit(event: Any) -> None:
            self.enter_edit_mode(event.app)

        return kb


class _EditRow(Container):
    """A text field's row while its value is edited: the label, cut with
    "…" to fit, then the input field where the row draws the value
    (_layout_row), at the width it gives. Laid out from the row's width at
    each redraw, so a row too narrow for the column keeps the field, as it
    keeps the value. The field keeps min(8, edit_width) columns: the label
    is cut further to keep them."""

    def __init__(self, control: TextFieldControl, field: Window) -> None:
        self._control = control
        self._field = field
        self._label = Window(_MarkedLabel(control.item))
        self._rest = Window()

    def reset(self) -> None:
        for child in self.get_children():
            child.reset()

    def preferred_width(self, max_available_width: int) -> Dimension:
        # The view row's rule (FieldControl.preferred_width), so the box
        # keeps its width as the edit starts.
        control = self._control
        item = control.item
        if control._value_column is None:
            width = get_cwidth(MARKER) + get_cwidth(item.label) + 2 + item.edit_width
        else:
            width = control._value_column.least + item.edit_width + 1
        return Dimension(min=0, preferred=width)

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
    """A highlighted field's label after the marker, cut with "…" to keep
    a blank column at the end of the width it's drawn in."""

    def __init__(self, item: Field) -> None:
        self._item = item

    def create_content(self, width: int, height: int) -> UIContent:
        label = _cut(self._item.label, width - get_cwidth(MARKER) - 1)
        line = FormattedText([
            ("class:field-indicator", MARKER),
            ("class:field-label-selected", label),
        ])
        return UIContent(get_line=lambda i: line, line_count=1)


class OptionsFieldControl(FieldControl[Any]):
    """A check list or radio list field: its label row, then one OptionRow
    per option. The options are the cursor stops; the label takes no focus."""

    def __init__(self, item: ChecklistField | RadioField) -> None:
        super().__init__(item)
        # With no label and no description, just the options, not indented:
        # a dialog's text stands in for the label (checklist_dialog).
        self._labelled = bool(item.label or item.description)
        indent = 2 if self._labelled else 0
        if isinstance(item, ChecklistField):
            self._group = OptionGroup(item.options, multiple=True, selected=list(item.default), indent=indent)
        else:
            picked = [item.default] if item.default is not None else []
            self._group = OptionGroup(item.options, multiple=False, selected=picked, indent=indent)
        rows = [row.window for row in self._group.rows]
        self._container = HSplit([self._window, *rows] if self._labelled else rows)

    def preferred_width(self, max_available_width: int) -> int:
        """The label row's columns (and its description's); the option rows
        say their own."""
        description = self._item.description
        label = get_cwidth(NO_MARKER) + get_cwidth(self._item.label)
        return max(label, 2 + get_cwidth(description) if description else 0)

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
        label_rows = super().row_count if self._labelled else 0
        return label_rows + len(self._group.rows)

    def is_focusable(self) -> bool:
        return False  # the label row; the option rows take focus

    def get_container(self) -> Container:
        return self._container

    def get_stops(self) -> list[Container]:
        return [row.window for row in self._group.rows]

    def start_stop(self) -> Container:
        """A radio list's picked option, else the first option."""
        picked = None if self._group.multiple else self._group.picked
        for row in self._group.rows:
            if row.option == picked:
                return row.window
        return self._group.rows[0].window

    def create_content(self, width: int, height: int) -> UIContent:
        """The label row (and description), highlighted while an option has focus."""
        selected = any(has_focus(row.window) for row in self._group.rows)
        label_style = "class:field-label-selected" if selected else "class:field-label"
        lines = [FormattedText([("", NO_MARKER), (label_style, self._item.label)])]
        if self._item.description:
            lines.append(_description(self._item.description, selected))
        return _content(lines)


class _ChoiceRow(RowControl):
    """One option of a ChoiceField. It takes focus only while it's the
    field's one cursor stop (ChoiceFieldControl.current_stop)."""

    def __init__(self, choice: ChoiceFieldControl, index: int) -> None:
        self.choice = choice
        self.index = index
        self.window = Window(self, height=1, dont_extend_height=True)

    def is_focusable(self) -> bool:
        return self.choice.current_stop() is self.window

    def preferred_width(self, max_available_width: int) -> int:
        """The columns the row takes uncut: the marker, the indent and the option."""
        option = self.choice.item.options[self.index]
        return get_cwidth(MARKER) + self.choice.indent + get_cwidth(option)

    def create_content(self, width: int, height: int) -> UIContent:
        """The option, bold if it's the pick, after ❯ while it has focus."""
        focused = has_focus(self.window)
        picked = self.index == self.choice.index
        line = FormattedText([
            ("class:field-indicator" if focused else "", MARKER if focused else NO_MARKER),
            ("", " " * self.choice.indent),
            (
                "class:dialog-choice-selected" if picked else "class:field-label",
                self.choice.item.options[self.index],
            ),
        ])
        # The marker shows the cursor row: no terminal cursor drawn over it.
        return UIContent(get_line=lambda i: line, line_count=1, show_cursor=False)

    def get_key_bindings(self) -> KeyBindings:
        return self.choice.keys


class ChoiceFieldControl(FieldControl[ChoiceField]):
    """A ChoiceField: its label row (with a label or a description), then
    one _ChoiceRow per option. One window takes the cursor at a time
    (current_stop): the label row at rest (with no label row, the pick),
    the pick while picking. Alone in its dialog (set_alone) it is always
    picking."""

    def __init__(self, item: ChoiceField) -> None:
        super().__init__(item)
        options = item.options
        # The pick's index.
        self.index = options.index(item.default) if item.default in options else 0
        self._original_index = self.index
        self._app_ref: Any = None
        # Alone in its dialog: what Enter does (press the first button).
        self._press: Callable[[], None] | None = None
        # With no label and no description, just the options, not indented:
        # a dialog's text stands in for the label (dropdown_dialog).
        self._labelled = bool(item.label or item.description)
        self.indent = 2 if self._labelled else 0
        self.keys = self._key_bindings()
        self._rows = [_ChoiceRow(self, i) for i in range(len(options))]
        windows = [row.window for row in self._rows]
        self._container = HSplit([self._window, *windows] if self._labelled else windows)

    @property
    def value(self) -> str:
        """The picked option."""
        return self._item.options[self.index]

    @value.setter
    def value(self, val: Any) -> None:
        if val in self._item.options:
            self.index = self._item.options.index(val)

    @property
    def picking(self) -> bool:
        """Whether ↑↓ move the pick: while picking in a form, always alone."""
        return self._editing or self._press is not None

    def set_alone(self, press: Callable[[], None] | None) -> None:
        """Alone in its dialog (the only field, nothing else to focus), with
        ``press`` for Enter: always picking. None: one field among others."""
        self._press = press

    def current_stop(self) -> Window:
        """The one window that takes the cursor now: the label row at rest
        (the pick, with no label row), the pick while picking."""
        if self._labelled and not self.picking:
            return self._window
        return self._rows[self.index].window

    def is_focusable(self) -> bool:
        return self.current_stop() is self._window

    def get_container(self) -> Container:
        return self._container

    def get_stops(self) -> list[Container]:
        return [self.current_stop()]

    @property
    def row_count(self) -> int:
        label_rows = super().row_count if self._labelled else 0
        return label_rows + len(self._rows)

    def preferred_width(self, max_available_width: int) -> int:
        """The label row's columns (and its description's); the option rows
        say their own."""
        description = self._item.description
        label = get_cwidth(MARKER) + get_cwidth(self._item.label)
        return max(label, 2 + get_cwidth(description) if description else 0)

    def create_content(self, width: int, height: int) -> UIContent:
        """The label row (and description): ❯ while it's the cursor stop,
        highlighted while any of the field has focus."""
        focused = self._check_focus()
        selected = focused or any(has_focus(row.window) for row in self._rows)
        label_style = "class:field-label-selected" if selected else "class:field-label"
        lines = [FormattedText([
            ("class:field-indicator" if focused else "", MARKER if focused else NO_MARKER),
            (label_style, self._item.label),
        ])]
        if self._item.description:
            lines.append(_description(self._item.description, selected))
        return _content(lines)

    def enter_edit_mode(self, app: Any = None) -> None:
        """Start picking: the cursor goes to the pick."""
        self._original_index = self.index
        self._editing = True
        self._app_ref = app
        self._focus_stop()

    def confirm_edit(self) -> None:
        """Keep the pick: the cursor goes back to the field's stop."""
        self._editing = False
        self._focus_stop()

    def abandon_edit(self) -> None:
        self.index = self._original_index
        self._editing = False

    def cancel_edit(self) -> None:
        """Put the old pick back: the cursor goes back to the field's stop."""
        self.abandon_edit()
        self._focus_stop()

    def move(self, delta: int, app: Any = None) -> None:
        """Move the pick ``delta`` options, clamped to the ends; the cursor follows."""
        last = len(self._item.options) - 1
        self.index = max(0, min(last, self.index + delta))
        if app:
            app.layout.focus(self.current_stop())

    def _focus_stop(self) -> None:
        if self._app_ref:
            self._app_ref.layout.focus(self.current_stop())

    def get_key_bindings(self) -> KeyBindings:
        return self.keys

    def _key_bindings(self) -> KeyBindings:
        """The label row's and the option rows' keys. At rest Enter starts
        picking. While picking ↑↓ move the pick, Enter keeps it and Escape
        puts it back. Alone, ↑↓ stop short of the ends (where the dialog's
        cursor takes them) and Enter presses the first button."""
        kb = KeyBindings()
        last = len(self._item.options) - 1
        at_rest = Condition(lambda: not self.picking)
        editing = Condition(lambda: self._editing)
        alone = Condition(lambda: self._press is not None)
        up = Condition(lambda: self._editing or (self._press is not None and self.index > 0))
        down = Condition(lambda: self._editing or (self._press is not None and self.index < last))

        @kb.add("enter", filter=at_rest)
        def _start(event: Any) -> None:
            self.enter_edit_mode(event.app)

        @kb.add("up", filter=up)
        def _up(event: Any) -> None:
            self.move(-1, event.app)

        @kb.add("down", filter=down)
        def _down(event: Any) -> None:
            self.move(1, event.app)

        @kb.add("enter", filter=editing)
        def _keep(event: Any) -> None:
            self.confirm_edit()

        @kb.add("escape", filter=editing)
        def _cancel(event: Any) -> None:
            self.cancel_edit()

        @kb.add("enter", filter=alone)
        def _press_button(event: Any) -> None:
            if self._press is not None:
                self._press()

        return kb


def _control_for(field: Field) -> FieldControl:
    """The control that shows ``field``."""
    if isinstance(field, ChoiceField):
        return ChoiceFieldControl(field)
    if isinstance(field, (ChecklistField, RadioField)):
        return OptionsFieldControl(field)
    if isinstance(field, CheckboxField):
        return CheckboxFieldControl(field)
    if isinstance(field, DropdownField):
        return DropdownFieldControl(field)
    if isinstance(field, SelectField):
        return SelectFieldControl(field)
    if isinstance(field, TextField):
        return TextFieldControl(field)
    raise TypeError(
        "Dialog fields must be TextField, CheckboxField, SelectField, "
        f"DropdownField, ChecklistField, RadioField or ChoiceField; got {type(field).__name__}"
    )


class _Form:
    """A dialog's fields (Dialog.fields): one control each, holding its value
    from the dialog's creation on."""

    def __init__(self, fields: Sequence[Field]) -> None:
        self.controls: list[FieldControl] = [_control_for(f) for f in fields]
        keys: set[str] = set()
        for control in self.controls:
            key = control.item.key
            if key in keys:
                raise ValueError(f"Dialog fields need unique keys; {key!r} is used twice")
            keys.add(key)
        # The placement the fields were last laid out for (container()).
        self._placement: Placement = "box"

    @property
    def values(self) -> dict[str, Any]:
        """Each field's current value by key, in field order."""
        return {control.item.key: control.value for control in self.controls}

    def is_editing(self) -> bool:
        """Whether a field is being edited (a text field, an open menu)."""
        return any(control.is_editing for control in self.controls)

    def stops(self) -> list[Container]:
        """Every cursor stop in the fields, top to bottom."""
        return [stop for control in self.controls for stop in control.get_stops()]

    def start(self) -> Container | None:
        """Where the cursor starts in the fields: the first field's start (a
        radio list's picked option); None with no stops."""
        entered = self._enterable()
        return entered[0].start_stop() if entered else None

    def container(self, placement: Placement, align_values: AlignValues) -> HSplit | None:
        """The fields one under another, laid out for ``placement`` with
        values at ``align_values``, with their keys; None without fields."""
        if not self.controls:
            return None
        self._placement = placement
        inline = placement == "inline"
        for control in self.controls:
            if control.is_editing:
                control.abandon_edit()   # a dialog closed mid-edit
            if isinstance(control, DropdownFieldControl):
                control.set_inline(inline)
        # After set_inline: an inline dropdown's value is a selector.
        column = self._value_column(align_values)
        for control in self.controls:
            control.set_value_column(column)
        # An empty window_too_small: no "Window too small" flash while the
        # layout settles.
        return HSplit(
            [control.get_container() for control in self.controls],
            key_bindings=self._key_bindings(),
            window_too_small=Window(),
        )

    def floats(self) -> list[Float]:
        """A box's dropdown menus, to float over the whole screen, not the
        form, so each is sized by the room the terminal has around its row."""
        if self._placement == "inline":
            return []
        return [c.get_float() for c in self.controls if isinstance(c, DropdownFieldControl)]

    def _enterable(self) -> list[FieldControl]:
        """The fields the cursor can enter (a list with no options can't)."""
        return [control for control in self.controls if control.get_stops()]

    def _value_column(self, align_values: AlignValues) -> _ValueColumn | None:
        """Where values start (align_values); None: the row's right edge."""
        if align_values == "right":
            return None
        if align_values != "labels":
            return _ValueColumn(int(align_values))
        # Check, radio and choice lists have their label, and description,
        # on rows with no value. A description starts where labels do (under
        # the marker's columns).
        rows = [
            c for c in self.controls if not isinstance(c, (OptionsFieldControl, ChoiceFieldControl))
        ]

        def after(texts: Iterable[str]) -> int:
            return get_cwidth(MARKER) + max((get_cwidth(t) for t in texts), default=0) + 2

        return _ValueColumn(
            after(c.item.label for c in rows),
            after(c.item.description for c in rows),
            max((c.widest_value() for c in rows), default=0),
        )

    def _key_bindings(self) -> KeyBindingsBase | None:
        """In a box, ↑↓ move a row at a time. Inline: none, the dialog's own
        cursor walks fields and actions alike."""
        if self._placement == "inline":
            return None
        return RowNavigator(self.stops, is_editing=self.is_editing).key_bindings()

    def tab_bindings(self, before: Callable[[], list[Container]]) -> KeyBindings:
        """A box's Tab / Shift+Tab: a group at a time, in order. Each
        focusable window ``before()`` returns (the body above the fields) is
        a group, and each field is one, entered at its start (a radio list's
        picked option). Tab goes on to the buttons after the last group;
        Shift+Tab stays at the first (no wrap to the buttons)."""
        editing = Condition(self.is_editing)
        idle = ~editing
        kb = KeyBindings()

        # The cursor stays in an edit: the key is spent here, before the
        # dialog widget's Tab (focus_next / focus_previous) can move it.
        @kb.add("tab", filter=editing)
        @kb.add("s-tab", filter=editing)
        def _stay(event: Any) -> None:
            pass

        def groups() -> list[tuple[list[Container], Container]]:
            found: list[tuple[list[Container], Container]] = [([w], w) for w in before()]
            found.extend((c.get_stops(), c.start_stop()) for c in self._enterable())
            return found

        def current(layout: Layout, found: list[tuple[list[Container], Container]]) -> int | None:
            for i, (stops, _) in enumerate(found):
                if any(layout.has_focus(stop) for stop in stops):
                    return i
            return None

        @kb.add("tab", filter=idle)
        def _next_group(event: Any) -> None:
            found = groups()
            index = current(event.app.layout, found)
            if index is not None and index < len(found) - 1:
                event.app.layout.focus(found[index + 1][1])
            else:
                # After the last group: on to the buttons (no wrap).
                event.app.layout.focus(self.stops()[-1] if self.stops() else found[-1][1])
                event.app.layout.focus_next()

        @kb.add("s-tab", filter=idle)
        def _previous_group(event: Any) -> None:
            found = groups()
            index = current(event.app.layout, found)
            if index is not None and index > 0:
                event.app.layout.focus(found[index - 1][1])

        return kb
