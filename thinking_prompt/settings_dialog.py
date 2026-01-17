"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit.widgets import Label

from .dialog import BaseDialog


@dataclass
class SettingsItem(ABC):
    """Base class for all settings items."""
    key: str          # Unique identifier, used as dict key in result
    label: str        # Display label


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

    def build_body(self):
        """Build the dialog body (placeholder for now)."""
        return Label("Settings form (TODO)")

    def get_buttons(self):
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
