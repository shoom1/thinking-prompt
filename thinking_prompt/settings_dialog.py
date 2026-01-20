"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
Navigation: Up/Down to move between rows, Left/Right or Space to change values.
For text items: Enter to edit in-place, Enter/Escape to confirm/cancel.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    Container,
    DynamicContainer,
    HSplit,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl

from .dialog import BaseDialog


@dataclass
class SettingsItem(ABC):
    """Base class for all settings items."""
    key: str              # Unique identifier, used as dict key in result
    label: str            # Display label
    description: str = "" # Optional description shown below label
    default: Any = None


@dataclass
class DropdownItem(SettingsItem):
    """Select from a list of options."""
    options: list[str] = field(default_factory=list)
    default: Any = None


@dataclass
class CheckboxItem(SettingsItem):
    """Boolean toggle."""
    default: bool = False


@dataclass
class TextItem(SettingsItem):
    """Free text input."""
    default: str = ""
    password: bool = False


class SettingControl(UIControl, ABC):
    """Base class for setting controls with view/edit modes."""

    def __init__(self, item: SettingsItem) -> None:
        self._item = item
        self._value: Any = item.default
        self._editing = False
        self._has_focus = False

    @property
    def item(self) -> SettingsItem:
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


class CheckboxControl(SettingControl):
    """Checkbox control that toggles on Space/Enter."""

    def __init__(self, item: CheckboxItem) -> None:
        super().__init__(item)
        self._has_focus = False

    def toggle(self) -> None:
        """Toggle the checkbox value."""
        self._value = not self._value

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the checkbox row."""
        is_selected = self._has_focus

        # Build the row: [indicator] [label] ... [value]
        indicator = "> " if is_selected else "  "
        indicator_style = "class:setting-indicator" if is_selected else ""
        label_style = "class:setting-label-selected" if is_selected else "class:setting-label"

        if self._value:
            value_text = "true"
            value_style = "class:setting-value-true-selected" if is_selected else "class:setting-value-true"
        else:
            value_text = "false"
            value_style = "class:setting-value-false-selected" if is_selected else "class:setting-value-false"

        label_text = self._item.label
        available = width - len(indicator) - len(label_text) - len(value_text) - 1
        padding = max(1, available)

        row: list[tuple[str, str]] = [
            (indicator_style, indicator),
            (label_style, label_text),
            ("", " " * padding),
            (value_style, value_text),
        ]

        lines = [FormattedText(row)]

        # Add description if present
        if self._item.description:
            desc_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
            desc_row: list[tuple[str, str]] = [
                ("", "  "),
                (desc_style, self._item.description),
            ]
            lines.append(FormattedText(desc_row))

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def get_container(self) -> Container:
        """Return window containing this control."""
        height = 2 if self._item.description else 1
        return Window(self, height=height)

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


class DropdownControl(SettingControl):
    """Dropdown control that cycles through options."""

    def __init__(self, item: DropdownItem) -> None:
        super().__init__(item)
        self._has_focus = False

    def cycle(self, delta: int) -> None:
        """Cycle through options by delta (+1 or -1)."""
        options = self._item.options
        if not options:
            return
        try:
            idx = options.index(self._value)
        except ValueError:
            idx = 0
        new_idx = (idx + delta) % len(options)
        self._value = options[new_idx]

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the dropdown row."""
        is_selected = self._has_focus

        indicator = "> " if is_selected else "  "
        indicator_style = "class:setting-indicator" if is_selected else ""
        label_style = "class:setting-label-selected" if is_selected else "class:setting-label"
        value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        label_text = self._item.label
        value_text = str(self._value) if self._value else ""

        available = width - len(indicator) - len(label_text) - len(value_text) - 1
        padding = max(1, available)

        row: list[tuple[str, str]] = [
            (indicator_style, indicator),
            (label_style, label_text),
            ("", " " * padding),
            (value_style, value_text),
        ]

        lines = [FormattedText(row)]

        if self._item.description:
            desc_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
            desc_row: list[tuple[str, str]] = [
                ("", "  "),
                (desc_style, self._item.description),
            ]
            lines.append(FormattedText(desc_row))

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def get_container(self) -> Container:
        height = 2 if self._item.description else 1
        return Window(self, height=height)

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("left")
        @kb.add("h")
        def _prev(event: Any) -> None:
            self.cycle(-1)

        @kb.add("right")
        @kb.add("l")
        @kb.add("space")
        def _next(event: Any) -> None:
            self.cycle(1)

        return kb


class TextControl(SettingControl):
    """Text input control with view/edit modes."""

    def __init__(self, item: TextItem) -> None:
        super().__init__(item)
        self._has_focus = False
        self._original_value: str = item.default
        self._buffer = Buffer(multiline=False)

    def enter_edit_mode(self) -> None:
        """Enter edit mode - populate buffer with current value."""
        self._original_value = self._value
        self._buffer.text = self._value or ""
        self._buffer.cursor_position = len(self._buffer.text)
        self._editing = True

    def confirm_edit(self) -> None:
        """Confirm edit - save buffer to value."""
        self._value = self._buffer.text
        self._editing = False

    def cancel_edit(self) -> None:
        """Cancel edit - restore original value."""
        self._value = self._original_value
        self._editing = False

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the text row in view mode."""
        if self._editing:
            # Edit mode handled by get_container's DynamicContainer
            return UIContent(get_line=lambda i: FormattedText([]), line_count=0)

        is_selected = self._has_focus

        indicator = "> " if is_selected else "  "
        indicator_style = "class:setting-indicator" if is_selected else ""
        label_style = "class:setting-label-selected" if is_selected else "class:setting-label"

        # Format value
        if self._item.password and self._value:
            value_text = "••••••"
        elif self._value:
            value_text = str(self._value)
        else:
            value_text = "(empty)"

        if not self._value:
            value_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
        else:
            value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        label_text = self._item.label
        available = width - len(indicator) - len(label_text) - len(value_text) - 1
        padding = max(1, available)

        row: list[tuple[str, str]] = [
            (indicator_style, indicator),
            (label_style, label_text),
            ("", " " * padding),
            (value_style, value_text),
        ]

        lines = [FormattedText(row)]

        if self._item.description:
            desc_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
            desc_row: list[tuple[str, str]] = [
                ("", "  "),
                (desc_style, self._item.description),
            ]
            lines.append(FormattedText(desc_row))

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def get_container(self) -> Container:
        """Return container that switches between view/edit modes."""
        return DynamicContainer(self._get_current_container)

    def _get_current_container(self) -> Container:
        """Return appropriate container based on edit state."""
        height = 2 if self._item.description else 1

        if self._editing:
            return self._build_edit_container()
        else:
            return Window(self, height=height)

    def _build_edit_container(self) -> Container:
        """Build the edit mode container with buffer input."""
        # Label on left, input field on right
        label_text = f"> {self._item.label}"
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
        )

        row = VSplit([
            Window(
                FormattedTextControl(lambda: FormattedText([
                    ("class:setting-indicator", "> "),
                    ("class:setting-label-selected", self._item.label),
                ])),
                width=label_width,
            ),
            Window(width=1),
            Window(buffer_control, style="class:setting-input"),
        ])

        if self._item.description:
            desc_row = Window(
                FormattedTextControl(lambda: FormattedText([
                    ("", "  "),
                    ("class:setting-desc-selected", self._item.description),
                ])),
                height=1,
            )
            return HSplit([row, desc_row])

        return row

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter", filter=Condition(lambda: not self._editing))
        def _enter_edit(event: Any) -> None:
            self.enter_edit_mode()

        return kb


class SettingsDialog(BaseDialog):
    """
    A settings dialog using individual controls per setting type.

    Navigation:
    - Up/Down (or j/k): Move between settings
    - Left/Right (or h/l) or Space: Change value (dropdown/checkbox)
    - Enter: Edit text item in-place
    - Escape: Cancel edit or close dialog
    - Tab: Move to buttons

    Returns a dictionary of changed values when closed, or None if cancelled.
    """

    def __init__(
        self,
        title: str,
        items: list[SettingsItem],
        can_cancel: bool = True,
        styles: dict | None = None,
        width: int | None = 60,
        top: int | None = None,
    ) -> None:
        super().__init__()
        self.title = title
        self._items = items
        self._can_cancel = can_cancel
        self._styles = styles or {}
        self.width = width
        self.top = top

        # Original values for change detection
        self._original_values: dict[str, Any] = {}
        for item in items:
            self._original_values[item.key] = item.default

        # Create controls
        self._controls: list[SettingControl] = []
        for item in items:
            control = self._create_control(item)
            self._controls.append(control)

        # Escape behavior
        self.escape_result = None if can_cancel else "close"

    def _create_control(self, item: SettingsItem) -> SettingControl:
        """Create the appropriate control for a settings item."""
        if isinstance(item, CheckboxItem):
            return CheckboxControl(item)
        elif isinstance(item, DropdownItem):
            return DropdownControl(item)
        elif isinstance(item, TextItem):
            return TextControl(item)
        else:
            raise ValueError(f"Unknown settings item type: {type(item)}")

    def _any_editing(self) -> bool:
        """Check if any control is in edit mode."""
        return any(c.is_editing for c in self._controls)

    def _get_navigation_key_bindings(self) -> KeyBindings:
        """Key bindings for navigating between settings."""
        kb = KeyBindings()

        @kb.add("up", filter=Condition(lambda: not self._any_editing()))
        @kb.add("k", filter=Condition(lambda: not self._any_editing()))
        def _move_up(event: Any) -> None:
            event.app.layout.focus_previous()

        @kb.add("down", filter=Condition(lambda: not self._any_editing()))
        @kb.add("j", filter=Condition(lambda: not self._any_editing()))
        def _move_down(event: Any) -> None:
            event.app.layout.focus_next()

        return kb

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
        """Build the dialog body with individual control containers."""
        if not self._controls:
            return Window(height=1)

        rows = [control.get_container() for control in self._controls]

        # Create container with navigation bindings
        container = HSplit(rows, key_bindings=self._get_navigation_key_bindings())
        return container

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        """Return dialog buttons."""
        if self._can_cancel:
            return [
                ("Save", self._on_save),
                ("Cancel", self.cancel),
            ]
        else:
            return [("Done", self._on_save)]


# Keep these for backward compatibility and standalone use
class SettingsListControl(UIControl):
    """
    A clean settings list control with focus indicator and right-aligned values.

    Displays settings as:
      › Label                                    value
        Description text here (optional)

    Navigation: Up/Down to move, Left/Right/Space to change values.
    For text items: Enter to edit.
    """

    def __init__(
        self,
        items: list[SettingsItem],
        values: dict[str, Any] | None = None,
        get_selected_index: Callable[[], int] | None = None,
        get_editing_index: Callable[[], int | None] | None = None,
        on_edit_text: Callable[[int], None] | None = None,
    ) -> None:
        self._items = items
        self._on_edit_text = on_edit_text
        self._selected_index = 0

        # Use provided values dict or create our own
        if values is not None:
            self._values = values
            self._get_selected_index = get_selected_index or (lambda: self._selected_index)
            self._get_editing_index = get_editing_index or (lambda: None)
        else:
            # Standalone mode - manage our own state
            self._values = {item.key: item.default for item in items}
            self._get_selected_index = lambda: self._selected_index
            self._get_editing_index = lambda: None

    @property
    def values(self) -> dict[str, Any]:
        """Get current values."""
        return self._values.copy()

    @property
    def selected_index(self) -> int:
        """Get currently selected index."""
        return self._get_selected_index()

    @property
    def selected_item(self) -> SettingsItem | None:
        """Get currently selected item."""
        idx = self._get_selected_index()
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def _format_value(self, item: SettingsItem, is_selected: bool) -> tuple[str, str]:
        """Format value for display. Returns (text, style_class)."""
        value = self._values.get(item.key)

        if isinstance(item, CheckboxItem):
            if value:
                style = "class:setting-value-true-selected" if is_selected else "class:setting-value-true"
                return ("true", style)
            else:
                style = "class:setting-value-false-selected" if is_selected else "class:setting-value-false"
                return ("false", style)
        elif isinstance(item, DropdownItem):
            style = "class:setting-value-selected" if is_selected else "class:setting-value"
            return (str(value) if value else "", style)
        elif isinstance(item, TextItem):
            editing_idx = self._get_editing_index()
            idx = self._get_selected_index()
            item_idx = self._items.index(item) if item in self._items else -1
            is_editing = (item_idx == editing_idx)

            if is_editing:
                return ("", "")  # Empty when editing in-place

            style = "class:setting-value-selected" if is_selected else "class:setting-value"
            if item.password and value:
                return ("••••••", style)
            text = str(value) if value else "(empty)"
            if not value:
                style = "class:setting-desc" if not is_selected else "class:setting-desc-selected"
            # Add hint for text items when selected
            if is_selected:
                text = text + " ⏎"
            return (text, style)
        style = "class:setting-value-selected" if is_selected else "class:setting-value"
        return (str(value), style)

    def _change_value(self, delta: int) -> None:
        """Change the current item's value."""
        if not self._items:
            return
        idx = self._get_selected_index()
        item = self._items[idx]

        if isinstance(item, CheckboxItem):
            self._values[item.key] = not self._values[item.key]
        elif isinstance(item, DropdownItem):
            if item.options:
                current = self._values[item.key]
                try:
                    i = item.options.index(current)
                except ValueError:
                    i = 0
                new_idx = (i + delta) % len(item.options)
                self._values[item.key] = item.options[new_idx]

    def create_content(self, width: int, height: int) -> UIContent:
        """Create the visual content."""
        lines: list[FormattedText] = []
        selected_index = self._get_selected_index()
        editing_index = self._get_editing_index()

        for i, item in enumerate(self._items):
            is_selected = (i == selected_index)
            is_editing = (i == editing_index) and isinstance(item, TextItem)

            # Build the main row: [indicator] [label] ... [value]
            indicator = "› " if is_selected else "  "
            indicator_style = "class:setting-indicator" if is_selected else ""

            label_style = "class:setting-label-selected" if is_selected else "class:setting-label"

            if is_editing:
                value_text = ""
                value_style = ""
            else:
                value_text, value_style = self._format_value(item, is_selected)

            # Calculate padding to right-align value
            label_text = item.label
            available = width - len(indicator) - len(label_text) - len(value_text) - 1
            padding = max(1, available)

            row: list[tuple[str, str]] = [
                (indicator_style, indicator),
                (label_style, label_text),
                ("", " " * padding),
                (value_style, value_text),
            ]
            lines.append(FormattedText(row))

            # Add description line if present
            if item.description:
                desc_style = "class:setting-desc-selected" if is_selected else "class:setting-desc"
                desc_row: list[tuple[str, str]] = [
                    ("", "  "),
                    (desc_style, item.description),
                ]
                lines.append(FormattedText(desc_row))

        def get_line(i: int) -> FormattedText:
            if i < len(lines):
                return lines[i]
            return FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def is_focusable(self) -> bool:
        return True

    def get_key_bindings(self) -> KeyBindings:
        """Key bindings for navigation and value changes."""
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _move_up(event: Any) -> None:
            if self._selected_index > 0:
                self._selected_index -= 1

        @kb.add("down")
        @kb.add("j")
        def _move_down(event: Any) -> None:
            if self._selected_index < len(self._items) - 1:
                self._selected_index += 1

        @kb.add("left")
        @kb.add("h")
        def _prev_value(event: Any) -> None:
            self._change_value(-1)

        @kb.add("right")
        @kb.add("l")
        @kb.add("space")
        def _next_value(event: Any) -> None:
            self._change_value(1)

        @kb.add("enter")
        def _handle_enter(event: Any) -> None:
            item = self.selected_item
            if isinstance(item, TextItem) and self._on_edit_text:
                self._on_edit_text(self._selected_index)

        return kb


class CompactSelect(UIControl):
    """A compact single-line select control that cycles through options."""

    def __init__(self, options: list[str], default: str | None = None) -> None:
        self.options = options
        self._selected_index = 0
        if default and default in options:
            self._selected_index = options.index(default)

    @property
    def current_value(self) -> str | None:
        if self.options:
            return self.options[self._selected_index]
        return None

    @current_value.setter
    def current_value(self, value: str) -> None:
        if value in self.options:
            self._selected_index = self.options.index(value)

    def _next(self) -> None:
        if self.options:
            self._selected_index = (self._selected_index + 1) % len(self.options)

    def _prev(self) -> None:
        if self.options:
            self._selected_index = (self._selected_index - 1) % len(self.options)

    def create_content(self, width: int, height: int) -> UIContent:
        if self.options:
            value = self.options[self._selected_index]
            text = FormattedText([
                ("", "["), ("class:select-value", value), ("class:select-arrow", " ▼"), ("", "]"),
            ])
        else:
            text = FormattedText([("class:select-empty", "[No options]")])

        def get_line(i: int) -> FormattedText:
            return text if i == 0 else FormattedText([])
        return UIContent(get_line=get_line, line_count=1)

    def is_focusable(self) -> bool:
        return True

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("left")
        def _prev(event: Any) -> None:
            self._prev()

        @kb.add("right")
        @kb.add("space")
        def _next(event: Any) -> None:
            self._next()

        return kb


class CompactCheckbox(UIControl):
    """A compact single-line checkbox control."""

    def __init__(self, checked: bool = False) -> None:
        self._checked = checked

    @property
    def checked(self) -> bool:
        return self._checked

    @checked.setter
    def checked(self, value: bool) -> None:
        self._checked = value

    def _toggle(self) -> None:
        self._checked = not self._checked

    def create_content(self, width: int, height: int) -> UIContent:
        mark = "x" if self._checked else " "
        text = FormattedText([("", "["), ("class:checkbox-mark", mark), ("", "]")])

        def get_line(i: int) -> FormattedText:
            return text if i == 0 else FormattedText([])
        return UIContent(get_line=get_line, line_count=1)

    def is_focusable(self) -> bool:
        return True

    def get_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("space")
        @kb.add("enter")
        def _toggle(event: Any) -> None:
            self._toggle()

        return kb
