"""
The settings dialog: form fields in a Dialog that returns the changed values.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.key_bindings import KeyBindingsBase
from prompt_toolkit.layout import Container, Float, HSplit, Window
from prompt_toolkit.utils import get_cwidth

from .dialog import ButtonConfig, Dialog
from .fields import (
    AlignValues,
    CheckboxField,
    CheckboxFieldControl,
    ChecklistField,
    DropdownField,
    DropdownFieldControl,
    Field,
    FieldControl,
    OptionsFieldControl,
    RadioField,
    SelectField,
    SelectFieldControl,
    TextField,
    TextFieldControl,
    _check_align_values,
    _ValueColumn,
)
from .rows import MARKER, RowNavigator
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
        _check_align_values(align_values)
        # escapable: with can_cancel=False there is no cancel concept, so
        # Escape is disabled (the Done button is the only way out).
        # escape_result stays the default None, so nothing but a dict or None
        # can come back from show_settings_dialog().
        super().__init__(
            title, width=width, max_height=max_height, escapable=can_cancel, placement=placement
        )
        self._can_cancel = can_cancel
        self._align_values = align_values

        # Create controls
        self._controls: list[FieldControl] = [self._create_control(item) for item in items]

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
        rows = [c for c in self._controls if not isinstance(c, OptionsFieldControl)]

        def after(texts: Iterable[str]) -> int:
            return get_cwidth(MARKER) + max((get_cwidth(t) for t in texts), default=0) + 2

        return _ValueColumn(
            after(c.item.label for c in rows),
            after(c.item.description for c in rows),
            max((c.widest_value() for c in rows), default=0),
        )

    def _create_control(self, item: Field) -> FieldControl:
        """Create the appropriate control for a settings item."""
        if isinstance(item, (ChecklistField, RadioField)):
            return OptionsFieldControl(item)
        elif isinstance(item, CheckboxField):
            return CheckboxFieldControl(item)
        elif isinstance(item, DropdownField):
            return DropdownFieldControl(item)
        elif isinstance(item, SelectField):
            return SelectFieldControl(item)
        elif isinstance(item, TextField):
            return TextFieldControl(item)
        else:
            raise ValueError(f"Unknown settings item type: {type(item)}")

    def _stops(self) -> list[Container]:
        """Every cursor stop in the form, top to bottom."""
        return [stop for control in self._controls for stop in control.get_stops()]

    def _is_editing(self) -> bool:
        """Whether a setting is in edit mode."""
        return any(c.is_editing for c in self._controls)

    def _settings_key_bindings(self) -> KeyBindingsBase:
        """Ctrl+S saves. In a box, ↑↓ walk the settings, and so do Tab /
        Shift+Tab, Tab going on to the buttons after the last setting.
        Inline, the dialog's own cursor walks settings and actions alike."""
        idle = Condition(lambda: not self._is_editing())
        kb = KeyBindings()

        @kb.add("c-s", filter=idle)
        def _save(event: Any) -> None:
            self._on_save()

        if self._placement == "inline":
            return kb

        navigator = RowNavigator(self._stops, is_editing=self._is_editing)

        @kb.add("tab", filter=idle)
        def _tab_next(event: Any) -> None:
            stops = self._stops()
            index = navigator.index(event.app.layout)
            if index is not None and index < len(stops) - 1:
                event.app.layout.focus(stops[index + 1])
            else:
                # After the last setting: on to the buttons (no wrap back)
                event.app.layout.focus_next()

        @kb.add("s-tab", filter=idle)
        def _tab_prev(event: Any) -> None:
            # At the first setting: stays put (no wrap to the buttons)
            navigator.move(event.app.layout, -1)

        return merge_key_bindings([navigator.key_bindings(), kb])

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
        for control in self._controls:
            if isinstance(control, DropdownFieldControl):
                control.set_inline(inline)
        # After set_inline: an inline dropdown's value is a selector.
        column = self._value_column()
        for control in self._controls:
            control.set_value_column(column)

        # Use empty window_too_small to suppress brief "Window too small" message during layout
        return HSplit(
            [control.get_container() for control in self._controls],
            key_bindings=self._settings_key_bindings(),
            window_too_small=Window(),
        )

    def _screen_floats(self) -> list[Float]:
        """A box's dropdown menus float over the whole screen, not the form,
        so each is sized by the room the terminal has around its row."""
        if self._placement == "inline":
            return []
        return [c.get_float() for c in self._controls if isinstance(c, DropdownFieldControl)]

    def get_buttons(self) -> list[ButtonConfig]:
        """Return dialog buttons."""
        if self._can_cancel:
            return [
                ButtonConfig("Save", handler=self._on_save),
                ButtonConfig("Cancel", handler=self.cancel),
            ]
        return [ButtonConfig("Done", handler=self._on_save)]
