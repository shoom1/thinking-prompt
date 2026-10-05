"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
Navigation: Up/Down move between settings (and, in an inline dialog, on to
the Save/Cancel rows), Tab/Shift-Tab too. Left/Right or Space change values,
Enter edits text in place. Ctrl+S saves, Escape cancels.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

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
    FloatContainer,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.layout.processors import PasswordProcessor
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


def _selector_value(options: list[str], value: Any, value_style: str) -> list[tuple[str, str]]:
    """``◀ value ▶`` fragments. The arrows layer class:select-arrow over the
    value style; at either end the missing arrow's place is kept blank."""
    try:
        idx = options.index(value)
    except ValueError:
        idx = 0
    arrow_style = f"{value_style} class:select-arrow"
    left = (value_style, "  ") if idx == 0 else (arrow_style, "◀ ")
    right = (value_style, "  ") if idx == len(options) - 1 else (arrow_style, " ▶")
    return [left, (value_style, str(value) if value else ""), right]


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
        value: list[tuple[str, str]],
        is_selected: bool,
    ) -> list[FormattedText]:
        """Build the standard setting row with optional description.

        `value` is the right-aligned value as (style, text) fragments.
        Returns a list of FormattedText lines (1 or 2 depending on description).
        """
        indicator = MARKER if is_selected else NO_MARKER
        indicator_style = "class:setting-indicator" if is_selected else ""
        label_style = "class:setting-label-selected" if is_selected else "class:setting-label"

        label_text = self._item.label
        value_len = sum(len(text) for _, text in value)
        available = width - len(indicator) - len(label_text) - value_len - 1
        padding = max(1, available)

        row: list[tuple[str, str]] = [
            (indicator_style, indicator),
            (label_style, label_text),
            ("", " " * padding),
            *value,
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

        lines = self._build_setting_row(width, [(value_style, value_text)], is_selected)

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
        self._scroll_offset = 0  # For scrolling long lists
        self._app_ref: Any = None
        # Cache view-mode window for stable focus target
        height = 2 if item.description else 1
        self._view_window = Window(self, height=height)
        # Floating menu components (built lazily)
        self._menu_control = _DropdownMenuControl(self)
        self._menu_window: Window | None = None
        self._max_visible_height: int | None = None  # Set by parent dialog
        # Inline dialogs show a dropdown as a ←/→ selector, with no popup menu.
        self._inline = False

    def set_inline(self, inline: bool) -> None:
        """Show as a ←/→ selector (inline dialogs) instead of a popup menu."""
        self._inline = inline

    @property
    def hints(self) -> frozenset[str]:
        return frozenset({"←→ change"}) if self._inline else frozenset()

    def cycle(self, delta: int) -> None:
        """Move through options by delta (+1 or -1), clamped to the ends."""
        self._value = _cycled(self._item.options, self._value, delta)

    def set_max_visible_height(self, max_height: int) -> None:
        """Limit dropdown height to fit within dialog bounds."""
        self._max_visible_height = max_height

    def _get_visible_height(self) -> int:
        """Get the actual visible height (capped by max_visible_height)."""
        num_options = len(self._item.options)
        height = min(num_options, self._item.height)
        if self._max_visible_height is not None:
            height = min(height, self._max_visible_height)
        return max(1, height)

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
        self._ensure_visible()
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

    def _ensure_visible(self) -> None:
        """Ensure selected index is visible in the scroll window."""
        height = self._get_visible_height()
        if self._selected_index < self._scroll_offset:
            self._scroll_offset = self._selected_index
        elif self._selected_index >= self._scroll_offset + height:
            self._scroll_offset = self._selected_index - height + 1

    def _move_selection(self, delta: int) -> None:
        """Move selection by delta, clamping to bounds."""
        new_index = self._selected_index + delta
        new_index = max(0, min(new_index, len(self._item.options) - 1))
        self._selected_index = new_index
        self._ensure_visible()

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the dropdown row with down arrow indicator."""
        is_selected = self._check_focus()
        value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        value_text = str(self._value) if self._value else ""
        if self._inline:
            value = _selector_value(self._item.options, self._value, value_style)
        else:
            # Right-align value within dropdown width, add dropdown indicator
            value = [
                (value_style, f"{value_text.rjust(self._get_dropdown_width())} "),
                (f"{value_style} class:select-arrow", "▼"),
            ]

        lines = self._build_setting_row(width, value, is_selected)

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def _build_menu(self) -> None:
        """Build the dropdown menu components (called lazily)."""
        if self._menu_window is not None:
            return

        dropdown_width = self._get_dropdown_width()
        num_options = len(self._item.options)
        visible_height = self._get_visible_height()
        needs_scrollbar = num_options > visible_height

        right_margins = [ScrollbarMargin(display_arrows=False)] if needs_scrollbar else []

        self._menu_window = Window(
            self._menu_control,
            width=dropdown_width,
            height=visible_height,
            style="class:setting-dropdown",
            right_margins=right_margins,
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

        return Float(
            content=ConditionalContainer(
                content=framed_menu,
                filter=Condition(lambda: self._editing),
            ),
            attach_to_window=self._view_window,
            right=0,
            top=1,
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
        """Render all dropdown options (Window handles scrolling)."""
        dropdown = self._dropdown
        options = dropdown._item.options
        selected = dropdown._selected_index

        lines = []
        for i, opt in enumerate(options):
            is_selected = (i == selected)
            if is_selected:
                style = "class:setting-dropdown-selected"
            else:
                style = "class:setting-dropdown-item"
            # Truncate if needed
            max_text = width
            text = opt[:max_text] if len(opt) > max_text else opt.ljust(max_text)
            lines.append(FormattedText([(style, text)]))

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        # Return all lines with cursor at selected position for scrolling
        return UIContent(
            get_line=get_line,
            line_count=len(lines),
            cursor_position=Point(x=0, y=selected),
        )

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

        # Format value (right-aligned within edit_width)
        if self._item.password and self._value:
            value_text = "••••••"
        elif self._value:
            value_text = str(self._value)
        else:
            value_text = "(empty)"
        value_text = value_text.rjust(self._item.edit_width)

        if not self._value:
            value_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
        else:
            value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        lines = self._build_setting_row(width, [(value_style, value_text)], is_selected)

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

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

        # Label on left, input field on right
        label_text = f"{MARKER}{self._item.label}"
        label_width = len(label_text) + 2

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

        # Cache the buffer window for focus management
        edit_width = self._item.edit_width
        self._buffer_window = Window(buffer_control, width=edit_width, style="class:text-area")

        row = VSplit([
            Window(
                FormattedTextControl(lambda: FormattedText([
                    ("class:setting-indicator", MARKER),
                    ("class:setting-label-selected", self._item.label),
                ])),
                width=label_width,
            ),
            Window(),  # Flexible padding - expands to fill available space
            self._buffer_window,
        ])

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
        height: int | None = None,
        placement: Placement | None = None,
    ) -> None:
        # escapable: with can_cancel=False there is no cancel concept, so
        # Escape is disabled (the Done button is the only way out).
        # escape_result stays the default None, so nothing but a dict or None
        # can come back from show_settings_dialog().
        super().__init__(
            title, width=width, top=top, height=height, escapable=can_cancel, placement=placement
        )
        self._items = items
        self._can_cancel = can_cancel

        # Create controls
        self._controls: list[SettingControl] = [self._create_control(item) for item in items]

        # Original values for change detection, as each control reports them.
        self._original_values: dict[str, Any] = {c.item.key: c.value for c in self._controls}

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

        # Use empty window_too_small to suppress brief "Window too small" message during layout
        controls_container = HSplit(
            [control.get_container() for control in self._controls],
            key_bindings=self._settings_key_bindings(),
            window_too_small=Window(),
        )
        if inline:
            return controls_container

        # Box: dropdown menus float over the settings below them, sized to
        # the rows available under each dropdown.
        total_height = sum(control.row_count for control in self._controls)
        cumulative_height = 0
        floats = []
        for control in self._controls:
            if isinstance(control, DropdownControl):
                # Dropdown appears at top=1 relative to control's top;
                # subtract 2 for the Frame borders (top + bottom).
                available_below = total_height - (cumulative_height + 1)
                control.set_max_visible_height(max(1, available_below - 2))
                floats.append(control.get_float())
            cumulative_height += control.row_count

        if floats:
            # Wrap in FloatContainer so dropdowns can overlay other controls
            return FloatContainer(content=controls_container, floats=floats)
        return controls_container

    def get_buttons(self) -> list[ButtonConfig]:
        """Return dialog buttons."""
        if self._can_cancel:
            return [
                ButtonConfig("Save", handler=self._on_save),
                ButtonConfig("Cancel", handler=self.cancel),
            ]
        return [ButtonConfig("Done", handler=self._on_save)]
