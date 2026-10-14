"""
The settings dialog: form fields in a Dialog that returns the changed values.
"""
from __future__ import annotations

from typing import Any

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import Container, HSplit

from .dialog import ButtonConfig, Dialog
from .fields import AlignValues, Field
from .types import Placement


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
        items: list[Field],
        can_cancel: bool = True,
        *,
        width: int | None = 60,
        max_height: int | None = None,
        align_values: AlignValues = "labels",
        placement: Placement | None = None,
    ) -> None:
        # escapable: with can_cancel=False there is no cancel concept, so
        # Escape is disabled (the Done button is the only way out).
        super().__init__(
            title,
            fields=items,
            escapable=can_cancel,
            width=width,
            max_height=max_height,
            align_values=align_values,
            placement=placement,
        )
        self._can_cancel = can_cancel
        # The values at the start, for change detection.
        self._original_values = self.values

    def _get_changed_values(self) -> dict[str, Any]:
        """Return only values that differ from original."""
        return {
            key: value for key, value in self.values.items()
            if value != self._original_values[key]
        }

    def _on_save(self) -> None:
        self.set_result(self._get_changed_values())

    def _content(self) -> tuple[Container | None, Container | None]:
        """The fields, with Ctrl+S to save."""
        content, start = super()._content()
        if isinstance(content, HSplit):
            kb = KeyBindings()

            @kb.add("c-s", filter=Condition(lambda: not self._is_editing()))
            def _save(event: Any) -> None:
                self._on_save()

            content.key_bindings = (
                kb if content.key_bindings is None
                else merge_key_bindings([content.key_bindings, kb])
            )
        return content, start

    def get_buttons(self) -> list[ButtonConfig]:
        if self._can_cancel:
            return [
                ButtonConfig("Save", handler=self._on_save),
                ButtonConfig("Cancel", handler=self.cancel),
            ]
        return [ButtonConfig("Done", handler=self._on_save)]
