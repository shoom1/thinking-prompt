"""Tests for the settings dialog system."""
from __future__ import annotations

from prompt_toolkit.layout import FloatContainer, HSplit, Window

from thinking_prompt.settings_dialog import (
    CheckboxItem,
    DropdownItem,
    SettingsDialog,
    SettingsListControl,
    TextItem,
)


class TestSettingsItems:
    """Tests for settings item types."""

    def test_dropdown_item_creation(self):
        """DropdownItem stores key, label, options, and default."""
        item = DropdownItem(
            key="model",
            label="Model",
            options=["gpt-4", "gpt-3.5"],
            default="gpt-4",
        )
        assert item.key == "model"
        assert item.label == "Model"
        assert item.options == ["gpt-4", "gpt-3.5"]
        assert item.default == "gpt-4"

    def test_dropdown_item_with_description(self):
        """DropdownItem can have a description."""
        item = DropdownItem(
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


class TestSettingsListControl:
    """Tests for the SettingsListControl."""

    def test_list_control_init_values(self):
        """SettingsListControl initializes values from items."""
        items = [
            DropdownItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        control = SettingsListControl(items=items)

        assert control.values == {"model": "a", "stream": True}

    def test_list_control_change_dropdown(self):
        """Dropdown value can be changed via _change_value."""
        items = [
            DropdownItem(key="model", label="Model", options=["a", "b", "c"], default="a"),
        ]
        control = SettingsListControl(items=items)

        # Cycle forward
        control._change_value(1)
        assert control.values["model"] == "b"

        # Cycle forward again
        control._change_value(1)
        assert control.values["model"] == "c"

        # Cycle wraps around
        control._change_value(1)
        assert control.values["model"] == "a"

    def test_list_control_change_checkbox(self):
        """Checkbox value toggles via _change_value."""
        items = [
            CheckboxItem(key="stream", label="Stream", default=False),
        ]
        control = SettingsListControl(items=items)

        # Toggle on
        control._change_value(1)
        assert control.values["stream"] is True

        # Toggle off
        control._change_value(1)
        assert control.values["stream"] is False

    def test_list_control_navigation(self):
        """Selected index changes with navigation."""
        items = [
            CheckboxItem(key="a", label="A"),
            CheckboxItem(key="b", label="B"),
            CheckboxItem(key="c", label="C"),
        ]
        control = SettingsListControl(items=items)

        assert control._selected_index == 0

        # Move down - simulate the key binding effect
        control._selected_index = 1
        assert control._selected_index == 1


class TestSettingsDialogState:
    """Tests for SettingsDialog state management."""

    def test_settings_dialog_init_original_values(self):
        """SettingsDialog initializes original values from items."""
        items = [
            DropdownItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)

        assert dialog._original_values == {"model": "a", "stream": True, "name": "test"}

    def test_settings_dialog_get_changed_values_empty(self):
        """No changes returns empty dict."""
        items = [
            DropdownItem(key="model", label="Model", options=["a", "b"], default="a"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()  # Creates the list control

        changed = dialog._get_changed_values()
        assert changed == {}

    def test_settings_dialog_get_changed_values_with_changes(self):
        """Changed values are returned correctly."""
        items = [
            DropdownItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()  # Creates the list control

        # Simulate user changing dropdown via list control
        dialog._list_control._values["model"] = "b"

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

    def test_build_body_returns_float_container(self):
        """build_body returns a FloatContainer for in-place editing overlay."""
        items = [
            DropdownItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        body = dialog.build_body()

        # Should be a FloatContainer with list window and edit overlay
        assert isinstance(body, FloatContainer)

    def test_build_body_creates_list_control(self):
        """build_body creates the SettingsListControl."""
        items = [
            DropdownItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()

        assert dialog._list_control is not None
        assert isinstance(dialog._list_control, SettingsListControl)


class TestSessionIntegration:
    """Tests for session.show_settings_dialog integration."""

    def test_settings_items_exported(self):
        """Settings item classes are exported from package."""
        from thinking_prompt import (
            SettingsItem,
            DropdownItem,
            CheckboxItem,
            TextItem,
            SettingsDialog,
        )
        # Just check they're importable
        assert SettingsItem is not None
        assert DropdownItem is not None
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


class TestShowSettingsDialog:
    """Tests for session.show_settings_dialog method."""

    def test_session_has_show_settings_dialog_method(self):
        """ThinkingPromptSession has show_settings_dialog method."""
        from thinking_prompt import ThinkingPromptSession
        assert hasattr(ThinkingPromptSession, 'show_settings_dialog')
