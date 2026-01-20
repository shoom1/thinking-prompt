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


class SettingsDialog(BaseDialog):
    """
    A settings dialog with clean list styling and in-place text editing.

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

        # Current values
        self._values: dict[str, Any] = {}
        for item in items:
            self._values[item.key] = item.default

        # Navigation state
        self._selected_index = 0
        self._editing_index: int | None = None

        # Text edit buffer
        self._edit_buffer: Buffer | None = None
        self._edit_window: Window | None = None
        self._list_window: Window | None = None
        self._list_control: SettingsListControl | None = None

        # Escape behavior
        self.escape_result = None if can_cancel else "close"

    def _get_selected_index(self) -> int:
        return self._selected_index

    def _get_editing_index(self) -> int | None:
        return self._editing_index

    def _get_changed_values(self) -> dict[str, Any]:
        """Return only values that differ from original."""
        changed = {}
        for key, value in self._values.items():
            if value != self._original_values.get(key):
                changed[key] = value
        return changed

    def _on_save(self) -> None:
        """Handle save - return changed values."""
        self.set_result(self._get_changed_values())

    def _change_value(self, delta: int) -> None:
        """Change the current item's value."""
        if not self._items or self._editing_index is not None:
            return
        item = self._items[self._selected_index]

        if isinstance(item, CheckboxItem):
            self._values[item.key] = not self._values[item.key]
        elif isinstance(item, DropdownItem):
            if item.options:
                current = self._values[item.key]
                try:
                    idx = item.options.index(current)
                except ValueError:
                    idx = 0
                new_idx = (idx + delta) % len(item.options)
                self._values[item.key] = item.options[new_idx]

    def _start_text_edit(self, app: Any = None) -> None:
        """Start editing the current text item in-place."""
        if self._editing_index is not None:
            return
        item = self._items[self._selected_index]
        if not isinstance(item, TextItem):
            return
        if not self._edit_buffer:
            return

        # Set buffer to current value
        current_value = self._values[item.key] or ""
        self._edit_buffer.text = current_value
        self._edit_buffer.cursor_position = len(current_value)

        self._editing_index = self._selected_index

        # Focus the edit window - use provided app or fall back to manager
        if self._edit_window:
            if app:
                app.layout.focus(self._edit_window)
            elif self._manager:
                self._manager._session.app.layout.focus(self._edit_window)

    def _confirm_text_edit(self, app: Any = None) -> None:
        """Confirm text edit."""
        if self._editing_index is None or not self._edit_buffer:
            return

        item = self._items[self._editing_index]
        if isinstance(item, TextItem):
            self._values[item.key] = self._edit_buffer.text

        self._editing_index = None

        # Return focus to list
        if self._list_window:
            if app:
                app.layout.focus(self._list_window)
            elif self._manager:
                self._manager._session.app.layout.focus(self._list_window)

    def _cancel_text_edit(self, app: Any = None) -> None:
        """Cancel text edit."""
        self._editing_index = None

        # Return focus to list
        if self._list_window:
            if app:
                app.layout.focus(self._list_window)
            elif self._manager:
                self._manager._session.app.layout.focus(self._list_window)

    def _get_list_key_bindings(self) -> KeyBindings:
        """Key bindings for list navigation."""
        kb = KeyBindings()

        @kb.add("up", filter=Condition(lambda: self._editing_index is None))
        @kb.add("k", filter=Condition(lambda: self._editing_index is None))
        def _move_up(event: Any) -> None:
            if self._selected_index > 0:
                self._selected_index -= 1

        @kb.add("down", filter=Condition(lambda: self._editing_index is None))
        @kb.add("j", filter=Condition(lambda: self._editing_index is None))
        def _move_down(event: Any) -> None:
            if self._selected_index < len(self._items) - 1:
                self._selected_index += 1

        @kb.add("left", filter=Condition(lambda: self._editing_index is None))
        @kb.add("h", filter=Condition(lambda: self._editing_index is None))
        def _prev_value(event: Any) -> None:
            self._change_value(-1)

        @kb.add("right", filter=Condition(lambda: self._editing_index is None))
        @kb.add("l", filter=Condition(lambda: self._editing_index is None))
        @kb.add("space", filter=Condition(lambda: self._editing_index is None))
        def _next_value(event: Any) -> None:
            self._change_value(1)

        @kb.add("enter", filter=Condition(lambda: self._editing_index is None))
        def _handle_enter(event: Any) -> None:
            item = self._items[self._selected_index]
            if isinstance(item, TextItem):
                self._start_text_edit(app=event.app)

        return kb

    def _calculate_edit_position(self) -> int:
        """Calculate the line number where the edit field should appear."""
        if self._editing_index is None:
            return 0
        line = 0
        for i, item in enumerate(self._items):
            if i == self._editing_index:
                return line
            line += 1
            if item.description:
                line += 1
        return line

    def _get_label_width(self) -> int:
        """Get the width needed for labels."""
        return max(len(item.label) for item in self._items) + 4  # +4 for "› " and ": "

    def build_body(self) -> Container:
        """Build the dialog body with in-place text editing."""
        from prompt_toolkit.layout import FloatContainer, Float
        from prompt_toolkit.layout.dimension import Dimension

        # Create the list control with key bindings
        self._list_control = SettingsListControl(
            items=self._items,
            values=self._values,
            get_selected_index=self._get_selected_index,
            get_editing_index=self._get_editing_index,
        )

        # Add key bindings to control
        list_kb = self._get_list_key_bindings()
        original_get_kb = self._list_control.get_key_bindings

        def merged_key_bindings() -> KeyBindings:
            from prompt_toolkit.key_binding import merge_key_bindings
            return merge_key_bindings([original_get_kb(), list_kb])

        self._list_control.get_key_bindings = merged_key_bindings

        # Calculate total lines
        total_lines = sum(2 if item.description else 1 for item in self._items)

        self._list_window = Window(
            self._list_control,
            height=total_lines,
        )

        # Create text edit buffer with key bindings
        self._edit_buffer = Buffer(multiline=False)

        edit_kb = KeyBindings()

        @edit_kb.add("enter")
        def _confirm(event: Any) -> None:
            self._confirm_text_edit(app=event.app)

        @edit_kb.add("escape")
        def _cancel(event: Any) -> None:
            self._cancel_text_edit(app=event.app)

        edit_control = BufferControl(
            buffer=self._edit_buffer,
            key_bindings=edit_kb,
        )

        self._edit_window = Window(
            edit_control,
            height=1,
            style="class:setting-input",
        )

        # Create the edit overlay container
        label_width = self._get_label_width()

        def get_edit_label() -> FormattedText:
            """Get the label for the edit row."""
            if self._editing_index is None:
                return FormattedText([])
            item = self._items[self._editing_index]
            return FormattedText([("class:setting-indicator", "› "), ("class:setting-label-selected", item.label)])

        edit_overlay = VSplit([
            Window(FormattedTextControl(get_edit_label), width=label_width),
            Window(width=1),
            self._edit_window,
        ], height=1)

        # Use a dynamic container for the float that updates position
        class DynamicFloat(Float):
            """Float with dynamic top position."""
            def __init__(self, content: Container, get_top: Callable[[], int]) -> None:
                super().__init__(content=content, left=0, top=0)
                self._get_top = get_top

            @property  # type: ignore[override]
            def top(self) -> int:
                return self._get_top()

            @top.setter
            def top(self, value: int) -> None:
                pass  # Ignore setter, we use dynamic getter

        return FloatContainer(
            content=self._list_window,
            floats=[
                DynamicFloat(
                    content=ConditionalContainer(
                        content=edit_overlay,
                        filter=Condition(lambda: self._editing_index is not None),
                    ),
                    get_top=self._calculate_edit_position,
                ),
            ],
        )

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
