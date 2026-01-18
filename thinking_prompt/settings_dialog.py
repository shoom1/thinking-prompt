"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
Navigation: Up/Down to move between rows, Left/Right or Space to change values.
For text items: Enter to edit, Enter/Escape to confirm/cancel.
"""
from __future__ import annotations

from abc import ABC
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
        on_edit_text: Callable[[int], None] | None = None,
    ) -> None:
        self._items = items
        self._on_edit_text = on_edit_text
        self._selected_index = 0

        # Current values (start with defaults)
        self._values: dict[str, Any] = {}
        for item in items:
            self._values[item.key] = item.default

    @property
    def values(self) -> dict[str, Any]:
        """Get current values."""
        return self._values.copy()

    @property
    def selected_index(self) -> int:
        """Get currently selected index."""
        return self._selected_index

    @property
    def selected_item(self) -> SettingsItem | None:
        """Get currently selected item."""
        if 0 <= self._selected_index < len(self._items):
            return self._items[self._selected_index]
        return None

    def _format_value(self, item: SettingsItem, is_selected: bool) -> tuple[str, str]:
        """Format value for display. Returns (text, style_class)."""
        value = self._values[item.key]

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
            style = "class:setting-value-selected" if is_selected else "class:setting-value"
            if item.password and value:
                return ("••••••", style)
            text = str(value) if value else "(empty)"
            if not value:
                style = "class:setting-desc" if not is_selected else "class:setting-desc-selected"
            return (text, style)
        style = "class:setting-value-selected" if is_selected else "class:setting-value"
        return (str(value), style)

    def _change_value(self, delta: int) -> None:
        """Change the current item's value."""
        if not self._items:
            return
        item = self._items[self._selected_index]

        if isinstance(item, CheckboxItem):
            # Toggle boolean
            self._values[item.key] = not self._values[item.key]
        elif isinstance(item, DropdownItem):
            # Cycle through options
            if item.options:
                current = self._values[item.key]
                try:
                    idx = item.options.index(current)
                except ValueError:
                    idx = 0
                new_idx = (idx + delta) % len(item.options)
                self._values[item.key] = item.options[new_idx]

    def create_content(self, width: int, height: int) -> UIContent:
        """Create the visual content."""
        lines: list[FormattedText] = []

        for i, item in enumerate(self._items):
            is_selected = (i == self._selected_index)

            # Build the main row: [indicator] [label] ... [value]
            indicator = "› " if is_selected else "  "
            indicator_style = "class:setting-indicator" if is_selected else ""

            label_style = "class:setting-label-selected" if is_selected else "class:setting-label"
            value_text, value_style = self._format_value(item, is_selected)

            # Add hint for text items
            if isinstance(item, TextItem) and is_selected:
                value_text = value_text + " [Enter]"

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
                    ("", "  "),  # Indent to align with label
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
        @kb.add("k")  # vim-style
        def _move_up(event: Any) -> None:
            if self._selected_index > 0:
                self._selected_index -= 1

        @kb.add("down")
        @kb.add("j")  # vim-style
        def _move_down(event: Any) -> None:
            if self._selected_index < len(self._items) - 1:
                self._selected_index += 1

        @kb.add("left")
        @kb.add("h")  # vim-style
        def _prev_value(event: Any) -> None:
            self._change_value(-1)

        @kb.add("right")
        @kb.add("l")  # vim-style
        @kb.add("space")
        def _next_value(event: Any) -> None:
            self._change_value(1)

        @kb.add("enter")
        def _handle_enter(event: Any) -> None:
            # For text items, trigger edit mode
            item = self.selected_item
            if isinstance(item, TextItem) and self._on_edit_text:
                self._on_edit_text(self._selected_index)

        return kb


class SettingsDialog(BaseDialog):
    """
    A settings dialog with clean list styling.

    Navigation:
    - Up/Down (or j/k): Move between settings
    - Left/Right (or h/l) or Space: Change value (dropdown/checkbox)
    - Enter: Edit text item / toggle checkbox
    - Tab: Move to buttons
    - Escape: Cancel

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

        # The list control will be created in build_body
        self._list_control: SettingsListControl | None = None

        # Text editing state
        self._editing_text = False
        self._edit_buffer: Buffer | None = None
        self._edit_window: Window | None = None
        self._list_window: Window | None = None

        # Escape behavior
        self.escape_result = None if can_cancel else "close"

    def _get_changed_values(self) -> dict[str, Any]:
        """Return only values that differ from original."""
        if not self._list_control:
            return {}
        changed = {}
        for key, value in self._list_control.values.items():
            if value != self._original_values.get(key):
                changed[key] = value
        return changed

    def _on_save(self) -> None:
        """Handle save - return changed values."""
        self.set_result(self._get_changed_values())

    def _start_text_edit(self, index: int) -> None:
        """Start editing a text item."""
        if not self._list_control or not self._edit_buffer:
            return

        item = self._items[index]
        if not isinstance(item, TextItem):
            return

        # Set buffer text to current value
        current_value = self._list_control._values[item.key] or ""
        self._edit_buffer.text = current_value
        self._edit_buffer.cursor_position = len(current_value)

        # Enter edit mode
        self._editing_text = True

        # Focus the edit window
        if self._manager and self._edit_window:
            self._manager._session.app.layout.focus(self._edit_window)

    def _confirm_text_edit(self) -> None:
        """Confirm text edit and return to list."""
        if not self._list_control or not self._edit_buffer:
            return

        item = self._list_control.selected_item
        if isinstance(item, TextItem):
            # Save the edited value
            self._list_control._values[item.key] = self._edit_buffer.text

        self._editing_text = False

        # Return focus to list
        if self._manager and self._list_window:
            self._manager._session.app.layout.focus(self._list_window)

    def _cancel_text_edit(self) -> None:
        """Cancel text edit and return to list."""
        self._editing_text = False

        # Return focus to list
        if self._manager and self._list_window:
            self._manager._session.app.layout.focus(self._list_window)

    def _get_edit_label(self) -> str:
        """Get the label for the text being edited."""
        if self._list_control:
            item = self._list_control.selected_item
            if item:
                return f"  {item.label}: "
        return "  Edit: "

    def build_body(self) -> Container:
        """Build the dialog body with list and text edit area."""
        self._list_control = SettingsListControl(
            items=self._items,
            on_edit_text=self._start_text_edit,
        )

        # Calculate height based on items (label + optional description)
        total_lines = sum(2 if item.description else 1 for item in self._items)

        self._list_window = Window(
            self._list_control,
            height=total_lines,
        )

        # Create text edit buffer and window
        self._edit_buffer = Buffer(
            multiline=False,
            on_text_changed=lambda _: None,
        )

        # Key bindings for edit buffer
        edit_kb = KeyBindings()

        @edit_kb.add("enter")
        def _confirm(event: Any) -> None:
            self._confirm_text_edit()

        @edit_kb.add("escape")
        def _cancel(event: Any) -> None:
            self._cancel_text_edit()

        edit_control = BufferControl(
            buffer=self._edit_buffer,
            key_bindings=edit_kb,
        )

        self._edit_window = Window(
            edit_control,
            height=1,
        )

        # Edit row: label + input field
        edit_row = ConditionalContainer(
            content=VSplit([
                Window(
                    FormattedTextControl(self._get_edit_label),
                    width=20,
                    align=WindowAlign.RIGHT,
                    style="class:setting-label-selected",
                ),
                self._edit_window,
            ]),
            filter=Condition(lambda: self._editing_text),
        )

        # Hint text when editing
        hint_row = ConditionalContainer(
            content=Window(
                FormattedTextControl("  Enter to confirm, Escape to cancel"),
                height=1,
                style="class:setting-desc",
            ),
            filter=Condition(lambda: self._editing_text),
        )

        return HSplit([
            self._list_window,
            edit_row,
            hint_row,
        ])

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
class CompactSelect(UIControl):
    """
    A compact single-line select control that cycles through options.
    Displays as: [selected_value ▼]
    """

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
                ("", "["),
                ("class:select-value", value),
                ("class:select-arrow", " ▼"),
                ("", "]"),
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
    """
    A compact single-line checkbox control.
    Displays as: [x] when checked, [ ] when unchecked.
    """

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
        text = FormattedText([
            ("", "["),
            ("class:checkbox-mark", mark),
            ("", "]"),
        ])

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
