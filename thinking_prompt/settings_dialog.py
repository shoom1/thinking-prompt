"""
Settings dialog for ThinkingPromptSession.

Provides a form-based dialog for configuring multiple settings at once.
Navigation: Up/Down within controls, Tab/Shift-Tab through all elements.
Left/Right or Space to change values. Enter to edit text in-place.
Ctrl+S saves, Escape cancels.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    Container,
    DynamicContainer,
    Float,
    FloatContainer,
    HSplit,
    ScrollablePane,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.margins import ScrollbarMargin

from prompt_toolkit.widgets import Frame

from .dialog import BaseDialog


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
        value_text: str,
        value_style: str,
        is_selected: bool,
    ) -> list[FormattedText]:
        """Build the standard setting row with optional description.

        Returns a list of FormattedText lines (1 or 2 depending on description).
        """
        indicator = "> " if is_selected else "  "
        indicator_style = "class:setting-indicator" if is_selected else ""
        label_style = "class:setting-label-selected" if is_selected else "class:setting-label"

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

        return lines


class CheckboxControl(SettingControl):
    """Checkbox control that toggles on Space/Enter."""

    def __init__(self, item: CheckboxItem) -> None:
        super().__init__(item)
        height = 2 if item.description else 1
        self._window = Window(self, height=height)

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

        lines = self._build_setting_row(width, value_text, value_style, is_selected)

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


class InlineSelectControl(SettingControl):
    """Inline select control that cycles through options with Left/Right keys."""

    def __init__(self, item: InlineSelectItem) -> None:
        super().__init__(item)
        height = 2 if item.description else 1
        self._window = Window(self, height=height)

    def cycle(self, delta: int) -> None:
        """Move through options by delta (+1 or -1), clamped to boundaries."""
        options = self._item.options
        if not options:
            return
        try:
            idx = options.index(self._value)
        except ValueError:
            idx = 0
        new_idx = max(0, min(len(options) - 1, idx + delta))
        self._value = options[new_idx]

    def create_content(self, width: int, height: int) -> UIContent:
        """Render the inline select row with left/right arrows."""
        is_selected = self._check_focus()
        value_style = "class:setting-value-selected" if is_selected else "class:setting-value"

        value_text = str(self._value) if self._value else ""

        # Get current index to determine arrow visibility
        options = self._item.options
        try:
            idx = options.index(self._value)
        except ValueError:
            idx = 0

        left_arrow = "  " if idx == 0 else "◀ "
        right_arrow = "  " if idx == len(options) - 1 else " ▶"
        value_with_arrows = f"{left_arrow}{value_text}{right_arrow}"

        lines = self._build_setting_row(width, value_with_arrows, value_style, is_selected)

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


class DropdownControl(SettingControl):
    """Dropdown control with floating menu in edit mode."""

    def __init__(self, item: DropdownItem) -> None:
        super().__init__(item)
        self._original_value: Any = item.default
        self._selected_index = 0  # Index in dropdown list during edit
        self._scroll_offset = 0  # For scrolling long lists
        self._app_ref = None
        # Cache view-mode window for stable focus target
        height = 2 if item.description else 1
        self._view_window = Window(self, height=height)
        # Floating menu components (built lazily)
        self._menu_control = _DropdownMenuControl(self)
        self._menu_window = None
        self._max_visible_height: int | None = None  # Set by parent dialog

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
            if self._menu_window and app.layout.has_focus(self._menu_window):
                return True
            return False
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
        # Right-align value within dropdown width, add dropdown indicator
        value_with_arrow = f"{value_text.rjust(self._get_dropdown_width())} ▼"

        lines = self._build_setting_row(width, value_with_arrow, value_style, is_selected)

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
        """Key bindings for dropdown control."""
        kb = KeyBindings()

        @kb.add("enter", filter=Condition(lambda: not self._editing))
        @kb.add("space", filter=Condition(lambda: not self._editing))
        def _enter_edit(event: Any) -> None:
            self.enter_edit_mode(event.app)

        # Edit mode bindings (active when editing)
        @kb.add("up", filter=Condition(lambda: self._editing))
        def _up(event: Any) -> None:
            self._move_selection(-1)

        @kb.add("down", filter=Condition(lambda: self._editing))
        def _down(event: Any) -> None:
            self._move_selection(1)

        @kb.add("enter", filter=Condition(lambda: self._editing))
        def _confirm(event: Any) -> None:
            self.confirm_edit()

        @kb.add("escape", filter=Condition(lambda: self._editing))
        def _cancel(event: Any) -> None:
            self.cancel_edit()

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


class TextControl(SettingControl):
    """Text input control with view/edit modes."""

    def __init__(self, item: TextItem) -> None:
        super().__init__(item)
        self._original_value: str = item.default
        self._buffer = Buffer(multiline=False)
        self._app_ref = None  # Store app reference for focus management
        # Cache view-mode window for stable focus target
        height = 2 if item.description else 1
        self._view_window = Window(self, height=height)
        # Cache edit container for stable focus
        self._edit_container = None
        self._buffer_window = None

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

        lines = self._build_setting_row(width, value_text, value_style, is_selected)

        def get_line(i: int) -> FormattedText:
            return lines[i] if i < len(lines) else FormattedText([])

        return UIContent(get_line=get_line, line_count=len(lines))

    def get_container(self) -> Container:
        """Return container that switches between view/edit modes."""
        return DynamicContainer(self._get_current_container)

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

        # Cache the buffer window for focus management
        edit_width = self._item.edit_width
        self._buffer_window = Window(buffer_control, width=edit_width, style="class:setting-input")

        row = VSplit([
            Window(
                FormattedTextControl(lambda: FormattedText([
                    ("class:setting-indicator", "> "),
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


class SettingsDialog(BaseDialog):
    """
    A settings dialog using individual controls per setting type.

    Navigation:
    - Up/Down: Navigate within settings controls (stops at boundaries)
    - Tab/Shift-Tab: Navigate through all elements (controls + buttons)
    - Left/Right or Space: Change value (dropdown/checkbox)
    - Enter: Edit text item in-place
    - Ctrl+S: Save and close
    - Escape: Cancel edit or close dialog

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

        # Navigation state
        self._focus_index = 0

        # Escape behavior
        self.escape_result = None if can_cancel else "close"

    def _create_control(self, item: SettingsItem) -> SettingControl:
        """Create the appropriate control for a settings item."""
        if isinstance(item, CheckboxItem):
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

    def _sync_focus_index(self, app: Any) -> None:
        """Sync _focus_index with actual focus (for when focus changes externally)."""
        for i, container in enumerate(self._control_containers):
            if app.layout.has_focus(container):
                self._focus_index = i
                return

    def _focus_control(self, index: int, app: Any) -> None:
        """Focus the control at the given index and update indicators."""
        if 0 <= index < len(self._controls):
            self._focus_index = index
            # Update focus indicators
            for i, control in enumerate(self._controls):
                control.set_has_focus(i == index)
            # Focus the control's container
            container = self._control_containers[index]
            app.layout.focus(container)

    def _clear_focus_indicators(self) -> None:
        """Clear all focus indicators (when leaving controls area)."""
        for control in self._controls:
            control.set_has_focus(False)

    def _get_navigation_key_bindings(self) -> KeyBindings:
        """Key bindings for navigation."""
        kb = KeyBindings()

        # Up/Down: navigate within controls only, stop at boundaries
        @kb.add("up", filter=Condition(lambda: not self._any_editing()))
        def _move_up(event: Any) -> None:
            self._sync_focus_index(event.app)  # Sync in case focus changed externally
            if self._focus_index > 0:
                self._focus_control(self._focus_index - 1, event.app)

        @kb.add("down", filter=Condition(lambda: not self._any_editing()))
        def _move_down(event: Any) -> None:
            self._sync_focus_index(event.app)  # Sync in case focus changed externally
            if self._focus_index < len(self._controls) - 1:
                self._focus_control(self._focus_index + 1, event.app)

        # Tab/Shift-Tab: navigate through controls + buttons (no wrapping)
        @kb.add("tab", filter=Condition(lambda: not self._any_editing()))
        def _tab_next(event: Any) -> None:
            self._sync_focus_index(event.app)  # Sync in case focus changed externally
            if self._focus_index < len(self._controls) - 1:
                # Move to next control
                self._focus_control(self._focus_index + 1, event.app)
            else:
                # At last control, move to buttons (no wrap back)
                self._clear_focus_indicators()
                event.app.layout.focus_next()

        @kb.add("s-tab", filter=Condition(lambda: not self._any_editing()))
        def _tab_prev(event: Any) -> None:
            self._sync_focus_index(event.app)  # Sync in case focus changed externally
            if self._focus_index > 0:
                # Move to previous control
                self._focus_control(self._focus_index - 1, event.app)
            # At first control: do nothing (no wrap to buttons)

        @kb.add("c-s", filter=Condition(lambda: not self._any_editing()))
        def _save(event: Any) -> None:
            self._on_save()

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

        # Set initial focus indicator on first control
        self._controls[0].set_has_focus(True)

        # Calculate control heights and total body height
        control_heights = []
        for control in self._controls:
            # Height is 2 if description present, else 1
            h = 2 if control.item.description else 1
            control_heights.append(h)
        total_height = sum(control_heights)

        # Set max_visible_height for dropdown controls based on available space
        cumulative_height = 0
        for i, control in enumerate(self._controls):
            if isinstance(control, DropdownControl):
                # Dropdown appears at top=1 relative to control's top
                dropdown_start = cumulative_height + 1
                available_below = total_height - dropdown_start
                # Subtract 2 for Frame borders (top + bottom)
                max_height = max(1, available_below - 2)
                control.set_max_visible_height(max_height)
            cumulative_height += control_heights[i]

        # Store containers for focus management
        self._control_containers = [control.get_container() for control in self._controls]

        # Create HSplit with navigation bindings
        # Use empty window_too_small to suppress brief "Window too small" message during layout
        controls_container = HSplit(
            self._control_containers,
            key_bindings=self._get_navigation_key_bindings(),
            window_too_small=Window(),
        )

        # Collect floats from dropdown controls (so they can overlay the entire dialog)
        floats = []
        for control in self._controls:
            if isinstance(control, DropdownControl):
                floats.append(control.get_float())

        if floats:
            # Wrap in FloatContainer so dropdowns can overlay other controls
            return FloatContainer(content=controls_container, floats=floats)
        else:
            return controls_container

    def get_buttons(self) -> list[tuple[str, Callable[[], None]]]:
        """Return dialog buttons."""
        if self._can_cancel:
            return [
                ("Save", self._on_save),
                ("Cancel", self.cancel),
            ]
        else:
            return [("Done", self._on_save)]
