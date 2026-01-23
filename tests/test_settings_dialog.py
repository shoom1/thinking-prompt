"""Tests for the settings dialog system."""
from __future__ import annotations

from prompt_toolkit.layout import HSplit, Window

from thinking_prompt.settings_dialog import (
    CheckboxItem,
    DropdownItem,
    InlineSelectItem,
    SettingsDialog,
    TextItem,
)


class TestSettingsItems:
    """Tests for settings item types."""

    def test_inline_select_item_creation(self):
        """InlineSelectItem stores key, label, options, and default."""
        item = InlineSelectItem(
            key="model",
            label="Model",
            options=["gpt-4", "gpt-3.5"],
            default="gpt-4",
        )
        assert item.key == "model"
        assert item.label == "Model"
        assert item.options == ["gpt-4", "gpt-3.5"]
        assert item.default == "gpt-4"

    def test_inline_select_item_with_description(self):
        """InlineSelectItem can have a description."""
        item = InlineSelectItem(
            key="model",
            label="Model",
            description="Select the AI model to use",
            options=["gpt-4", "gpt-3.5"],
            default="gpt-4",
        )
        assert item.description == "Select the AI model to use"

    def test_checkbox_item_creation(self):
        """CheckboxItem stores key, label, and default bool."""
        item = CheckboxItem(
            key="stream",
            label="Stream Output",
            default=True,
        )
        assert item.key == "stream"
        assert item.label == "Stream Output"
        assert item.default is True

    def test_checkbox_item_default_false(self):
        """CheckboxItem defaults to False."""
        item = CheckboxItem(key="debug", label="Debug")
        assert item.default is False

    def test_text_item_creation(self):
        """TextItem stores key, label, default, and password flag."""
        item = TextItem(
            key="api_key",
            label="API Key",
            default="sk-xxx",
            password=True,
        )
        assert item.key == "api_key"
        assert item.label == "API Key"
        assert item.default == "sk-xxx"
        assert item.password is True

    def test_text_item_defaults(self):
        """TextItem has sensible defaults."""
        item = TextItem(key="name", label="Name")
        assert item.default == ""
        assert item.password is False


class TestSettingsDialogState:
    """Tests for SettingsDialog state management."""

    def test_settings_dialog_init_original_values(self):
        """SettingsDialog initializes original values from items."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)

        assert dialog._original_values == {"model": "a", "stream": True, "name": "test"}

    def test_settings_dialog_get_changed_values_empty(self):
        """No changes returns empty dict."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()  # Creates the list control

        changed = dialog._get_changed_values()
        assert changed == {}

    def test_settings_dialog_get_changed_values_with_changes(self):
        """Changed values are returned correctly."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()  # Creates the controls

        # Simulate user changing dropdown via control
        dialog._controls[0].value = "b"

        changed = dialog._get_changed_values()
        assert changed == {"model": "b"}

    def test_settings_dialog_can_cancel_default_true(self):
        """SettingsDialog has can_cancel=True by default."""
        dialog = SettingsDialog(title="Settings", items=[])
        assert dialog._can_cancel is True

    def test_settings_dialog_can_cancel_false(self):
        """SettingsDialog can disable cancel."""
        dialog = SettingsDialog(title="Settings", items=[], can_cancel=False)
        assert dialog._can_cancel is False


class TestSettingsDialogLayout:
    """Tests for SettingsDialog layout."""

    def test_build_body_returns_hsplit(self):
        """build_body returns an HSplit of control containers."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        body = dialog.build_body()

        # Should be an HSplit of control containers
        assert isinstance(body, HSplit)

    def test_build_body_creates_controls(self):
        """build_body creates individual SettingControl instances."""
        from thinking_prompt.settings_dialog import (
            CheckboxControl, InlineSelectControl, TextControl
        )

        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()

        assert len(dialog._controls) == 3
        assert isinstance(dialog._controls[0], InlineSelectControl)
        assert isinstance(dialog._controls[1], CheckboxControl)
        assert isinstance(dialog._controls[2], TextControl)


class TestSessionIntegration:
    """Tests for session.show_settings_dialog integration."""

    def test_settings_items_exported(self):
        """Settings item classes are exported from package."""
        from thinking_prompt import (
            SettingsItem,
            DropdownItem,
            InlineSelectItem,
            CheckboxItem,
            TextItem,
            SettingsDialog,
        )
        # Just check they're importable
        assert SettingsItem is not None
        assert DropdownItem is not None
        assert InlineSelectItem is not None
        assert CheckboxItem is not None
        assert TextItem is not None
        assert SettingsDialog is not None


class TestSettingControl:
    """Tests for the SettingControl base class."""

    def test_setting_control_stores_item_and_value(self):
        """SettingControl stores item reference and initial value."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream", default=True)
        control = CheckboxControl(item)

        assert control.item is item
        assert control.value is True

    def test_setting_control_is_not_editing_by_default(self):
        """SettingControl starts in view mode."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream", default=False)
        control = CheckboxControl(item)

        assert control.is_editing is False


class TestCheckboxControl:
    """Tests for CheckboxControl."""

    def test_checkbox_control_tracks_focus(self):
        """CheckboxControl updates _has_focus based on actual focus."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream", default=False)
        control = CheckboxControl(item)

        # Simulate gaining focus
        control.set_has_focus(True)
        assert control._has_focus is True

        # Simulate losing focus
        control.set_has_focus(False)
        assert control._has_focus is False

    def test_checkbox_toggle(self):
        """Checkbox toggles value."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream", default=False)
        control = CheckboxControl(item)

        assert control.value is False
        control.toggle()
        assert control.value is True
        control.toggle()
        assert control.value is False

    def test_checkbox_renders_label_and_value(self):
        """Checkbox renders label and true/false value."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream Output", default=True)
        control = CheckboxControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Stream Output" in text
        assert "true" in text


class TestInlineSelectControl:
    """Tests for InlineSelectControl."""

    def test_inline_select_cycle_forward(self):
        """InlineSelect cycles through options forward."""
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="model", label="Model", options=["a", "b", "c"], default="a")
        control = InlineSelectControl(item)

        assert control.value == "a"
        control.cycle(1)
        assert control.value == "b"
        control.cycle(1)
        assert control.value == "c"
        control.cycle(1)
        assert control.value == "c"  # clamped at end

    def test_inline_select_cycle_backward(self):
        """InlineSelect cycles through options backward."""
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="model", label="Model", options=["a", "b", "c"], default="a")
        control = InlineSelectControl(item)

        control.cycle(-1)
        assert control.value == "a"  # clamped at start

    def test_inline_select_renders_label_and_value(self):
        """InlineSelect renders label and current option."""
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="model", label="Model", options=["gpt-4", "gpt-3.5"], default="gpt-4")
        control = InlineSelectControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Model" in text
        assert "gpt-4" in text


class TestTextControl:
    """Tests for TextControl."""

    def test_text_control_enter_edit_mode(self):
        """TextControl enters edit mode and populates buffer."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        assert control.is_editing is False
        control.enter_edit_mode()
        assert control.is_editing is True
        assert control._buffer.text == "Alice"

    def test_text_control_confirm_edit(self):
        """TextControl confirm saves buffer value."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        control.enter_edit_mode()
        control._buffer.text = "Bob"
        control.confirm_edit()

        assert control.is_editing is False
        assert control.value == "Bob"

    def test_text_control_cancel_edit(self):
        """TextControl cancel restores original value."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        control.enter_edit_mode()
        control._buffer.text = "Bob"
        control.cancel_edit()

        assert control.is_editing is False
        assert control.value == "Alice"  # restored

    def test_text_control_renders_value(self):
        """TextControl renders label and value in view mode."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Name" in text
        assert "Alice" in text

    def test_text_control_renders_empty_placeholder(self):
        """TextControl shows (empty) for empty value."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="")
        control = TextControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "(empty)" in text

    def test_text_control_renders_password_masked(self):
        """TextControl masks password values."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="api_key", label="API Key", default="sk-secret", password=True)
        control = TextControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "sk-secret" not in text
        assert "••••••" in text

    def test_text_control_container_switches_in_edit_mode(self):
        """TextControl container returns different content in edit mode."""
        from thinking_prompt.settings_dialog import TextControl
        from prompt_toolkit.layout import DynamicContainer

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        container = control.get_container()
        # Should be a DynamicContainer
        assert isinstance(container, DynamicContainer)


class TestShowSettingsDialog:
    """Tests for session.show_settings_dialog method."""

    def test_session_has_show_settings_dialog_method(self):
        """ThinkingPromptSession has show_settings_dialog method."""
        from thinking_prompt import ThinkingPromptSession
        assert hasattr(ThinkingPromptSession, 'show_settings_dialog')


class TestSettingsDialogRefactored:
    """Tests for refactored SettingsDialog using individual controls."""

    def test_settings_dialog_creates_controls(self):
        """SettingsDialog creates SettingControl instances."""
        from thinking_prompt.settings_dialog import (
            CheckboxControl, InlineSelectControl, TextControl
        )

        items = [
            CheckboxItem(key="stream", label="Stream", default=True),
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()

        assert len(dialog._controls) == 3
        assert isinstance(dialog._controls[0], CheckboxControl)
        assert isinstance(dialog._controls[1], InlineSelectControl)
        assert isinstance(dialog._controls[2], TextControl)

    def test_settings_dialog_build_body_returns_hsplit(self):
        """build_body returns HSplit of control containers."""
        items = [
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        body = dialog.build_body()

        assert isinstance(body, HSplit)
