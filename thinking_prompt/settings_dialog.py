"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Container, HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.widgets import CheckboxList, Label, TextArea

from .dialog import BaseDialog


class CompactSelect(UIControl):
    """
    A compact single-line select control that cycles through options.

    Displays as: [selected_value ▼]
    Use Up/Down arrows or Enter to cycle through options.
    """

    def __init__(self, options: list[str], default: str | None = None) -> None:
        self.options = options
        self._selected_index = 0

        # Set default selection
        if default and default in options:
            self._selected_index = options.index(default)

    @property
    def current_value(self) -> str | None:
        """Get the currently selected value."""
        if self.options:
            return self.options[self._selected_index]
        return None

    @current_value.setter
    def current_value(self, value: str) -> None:
        """Set the currently selected value."""
        if value in self.options:
            self._selected_index = self.options.index(value)

    def _next(self) -> None:
        """Select next option."""
        if self.options:
            self._selected_index = (self._selected_index + 1) % len(self.options)

    def _prev(self) -> None:
        """Select previous option."""
        if self.options:
            self._selected_index = (self._selected_index - 1) % len(self.options)

    def create_content(self, width: int, height: int) -> UIContent:
        """Create the visual content."""
        if self.options:
            value = self.options[self._selected_index]
            # Show as: [value ▼]
            text = FormattedText([
                ("", "["),
                ("class:select-value", value),
                ("class:select-arrow", " ▼"),
                ("", "]"),
            ])
        else:
            text = FormattedText([("class:select-empty", "[No options]")])

        def get_line(i: int) -> FormattedText:
            if i == 0:
                return text
            return FormattedText([])

        return UIContent(get_line=get_line, line_count=1)

    def is_focusable(self) -> bool:
        return True

    def get_key_bindings(self) -> KeyBindings:
        """Key bindings for navigation."""
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("left")
        def _prev(event: Any) -> None:
            self._prev()

        @kb.add("down")
        @kb.add("right")
        @kb.add("enter")
        @kb.add("space")
        def _next(event: Any) -> None:
            self._next()

        return kb


@dataclass
class SettingsItem(ABC):
    """Base class for all settings items."""
    key: str          # Unique identifier, used as dict key in result
    label: str        # Display label
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


class SettingsDialog(BaseDialog):
    """
    A dialog that displays a vertical form of configurable items.

    Returns a dictionary of changed values when closed, or None if cancelled.
    """

    def __init__(
        self,
        title: str,
        items: list[SettingsItem],
        can_cancel: bool = True,
        styles: dict | None = None,
        width: int | None = 60,  # Default min width of 60 for settings dialogs
    ) -> None:
        super().__init__()
        self.title = title
        self._items = items
        self._can_cancel = can_cancel
        self._styles = styles or {}
        self.width = width  # None/0=auto, >0=min width, -1=max width

        # State management
        self._original_values: dict[str, Any] = {}
        self._current_values: dict[str, Any] = {}

        # Control references for value access
        self._controls: dict[str, Any] = {}

        self._init_values()

        # Escape behavior depends on can_cancel
        self.escape_result = None if can_cancel else "close"

    def _init_values(self) -> None:
        """Initialize original and current values from items."""
        for item in self._items:
            self._original_values[item.key] = item.default
            self._current_values[item.key] = item.default

    def _get_changed_values(self) -> dict[str, Any]:
        """Return only values that differ from original."""
        changed = {}
        for key, value in self._current_values.items():
            if value != self._original_values[key]:
                changed[key] = value
        return changed

    def _create_dropdown_control(self, item: DropdownItem) -> CompactSelect:
        """Create a compact select control for dropdown item."""
        control = CompactSelect(options=item.options, default=item.default)
        return control

    def _create_checkbox_control(self, item: CheckboxItem) -> CheckboxList:
        """Create a checkbox control for checkbox item."""
        control = CheckboxList(values=[(item.key, "")])
        if item.default:
            control.current_values = [item.key]
        return control

    def _create_text_control(self, item: TextItem) -> TextArea:
        """Create a TextArea control for text item."""
        control = TextArea(
            text=item.default,
            multiline=False,
            password=item.password,
            height=1,
        )
        return control

    def _build_row(self, item: SettingsItem) -> VSplit:
        """Build a form row with label and control."""
        label_width = 20  # Fixed label width

        # Create control based on item type
        control: CompactSelect | CheckboxList | TextArea | Label
        if isinstance(item, DropdownItem):
            control = self._create_dropdown_control(item)
        elif isinstance(item, CheckboxItem):
            control = self._create_checkbox_control(item)
        elif isinstance(item, TextItem):
            control = self._create_text_control(item)
        else:
            control = Label("Unknown item type")

        self._controls[item.key] = control

        # Wrap UIControl in Window, widgets are already containers
        if isinstance(control, CompactSelect):
            control_container = Window(control, height=1)
        else:
            control_container = control

        # Create row: Label | Control
        return VSplit([
            Window(
                FormattedTextControl(f"{item.label}:"),
                width=label_width,
                align=WindowAlign.RIGHT,
            ),
            Window(width=2),  # Spacer
            control_container,
        ])

    def build_body(self) -> Container:
        """Build the dialog body with form rows."""
        rows = [self._build_row(item) for item in self._items]
        return HSplit(rows)

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        """Return dialog buttons based on can_cancel mode."""
        if self._can_cancel:
            return [
                ("Save", self._on_save),
                ("Cancel", self.cancel),
            ]
        else:
            return [
                ("Done", self._on_save),
            ]

    def _sync_values_from_controls(self) -> None:
        """Read current values from all controls into _current_values."""
        for item in self._items:
            control = self._controls.get(item.key)
            if control is None:
                continue

            if isinstance(item, DropdownItem):
                self._current_values[item.key] = control.current_value
            elif isinstance(item, CheckboxItem):
                # CheckboxList stores checked items in current_values list
                self._current_values[item.key] = item.key in control.current_values
            elif isinstance(item, TextItem):
                self._current_values[item.key] = control.text

    def _on_save(self) -> None:
        """Handle save/done button - sync and return changed values."""
        self._sync_values_from_controls()
        self.set_result(self._get_changed_values())
