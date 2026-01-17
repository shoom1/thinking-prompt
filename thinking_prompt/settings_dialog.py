"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable

from prompt_toolkit.layout import Container, HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import CheckboxList, Label, RadioList, TextArea

from .dialog import BaseDialog


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
    ) -> None:
        super().__init__()
        self.title = title
        self._items = items
        self._can_cancel = can_cancel
        self._styles = styles or {}

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

    def _create_dropdown_control(self, item: DropdownItem) -> RadioList:
        """Create a RadioList control for dropdown item."""
        values = [(opt, opt) for opt in item.options]
        control = RadioList(values=values)
        if item.default and item.default in item.options:
            control.current_value = item.default
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
        if isinstance(item, DropdownItem):
            control = self._create_dropdown_control(item)
        elif isinstance(item, CheckboxItem):
            control = self._create_checkbox_control(item)
        elif isinstance(item, TextItem):
            control = self._create_text_control(item)
        else:
            control = Label("Unknown item type")

        self._controls[item.key] = control

        # Create row: Label | Control
        return VSplit([
            Window(
                FormattedTextControl(f"{item.label}:"),
                width=label_width,
                align=WindowAlign.RIGHT,
            ),
            Window(width=2),  # Spacer
            control,
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

    def _on_save(self) -> None:
        """Handle save/done button - return changed values."""
        self.set_result(self._get_changed_values())
