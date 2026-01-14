"""
Tests for the dialog system.

Note: Many dialog tests require a running Application, so we use
async fixtures and simulate button clicks via the result future.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, List
from unittest.mock import MagicMock, patch

import pytest
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.widgets import Label

from thinking_prompt.dialog import (
    BaseDialog,
    ButtonConfig,
    DialogConfig,
    DialogManager,
    _UNSET,
    _ConfigBasedDialog,
    _YesNoDialog,
    _MessageDialog,
    _ChoiceDialog,
    _DropdownDialog,
    create_yes_no_dialog,
    create_message_dialog,
    create_choice_dialog,
    create_dropdown_dialog,
)


# =============================================================================
# ButtonConfig Tests
# =============================================================================

class TestButtonConfig:
    """Tests for ButtonConfig dataclass."""

    def test_button_config_defaults(self):
        """ButtonConfig has correct default values."""
        btn = ButtonConfig(text="OK")
        assert btn.text == "OK"
        assert btn.result is None
        assert btn.focused is False
        assert btn.style == ""

    def test_button_config_with_result(self):
        """ButtonConfig can store any result value."""
        btn = ButtonConfig(text="Save", result={"action": "save"})
        assert btn.result == {"action": "save"}

    def test_button_config_focused(self):
        """ButtonConfig focused flag works."""
        btn = ButtonConfig(text="OK", focused=True)
        assert btn.focused is True

    def test_button_config_with_style(self):
        """ButtonConfig can have custom style."""
        btn = ButtonConfig(text="Danger", style="bg:red")
        assert btn.style == "bg:red"


# =============================================================================
# DialogConfig Tests
# =============================================================================

class TestDialogConfig:
    """Tests for DialogConfig dataclass."""

    def test_dialog_config_with_string_body(self):
        """DialogConfig accepts string body."""
        config = DialogConfig(
            title="Test",
            body="Hello World",
            buttons=[ButtonConfig(text="OK")],
        )
        assert config.title == "Test"
        assert config.body == "Hello World"
        assert len(config.buttons) == 1

    def test_dialog_config_with_container_body(self):
        """DialogConfig accepts Container body."""
        container = HSplit([Label("Test")])
        config = DialogConfig(
            title="Test",
            body=container,
            buttons=[ButtonConfig(text="OK")],
        )
        assert config.body is container

    def test_dialog_config_escape_disabled_by_default(self):
        """DialogConfig has escape disabled by default."""
        config = DialogConfig(title="Test", body="Body")
        assert isinstance(config.escape_result, type(_UNSET))

    def test_dialog_config_escape_enabled(self):
        """DialogConfig can enable escape with result."""
        config = DialogConfig(
            title="Test",
            body="Body",
            escape_result=None,
        )
        assert config.escape_result is None

    def test_dialog_config_width(self):
        """DialogConfig can have custom width."""
        config = DialogConfig(
            title="Test",
            body="Body",
            width=80,
        )
        assert config.width == 80


# =============================================================================
# BaseDialog Tests
# =============================================================================

class TestBaseDialog:
    """Tests for BaseDialog class."""

    def test_base_dialog_is_abstract(self):
        """BaseDialog cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseDialog()

    def test_custom_dialog_subclass(self):
        """Custom dialog subclass works correctly."""
        class MyDialog(BaseDialog):
            title = "My Dialog"
            escape_result = "cancelled"

            def build_body(self):
                return Label("Custom body")

            def get_buttons(self):
                return [
                    ("OK", lambda: self.set_result("ok")),
                    ("Cancel", self.cancel),
                ]

        dialog = MyDialog()
        assert dialog.title == "My Dialog"
        assert dialog.escape_result == "cancelled"

    def test_base_dialog_build_widget(self):
        """BaseDialog._build_widget creates Dialog widget."""
        class TestDialog(BaseDialog):
            title = "Test"

            def build_body(self):
                return Label("Body")

            def get_buttons(self):
                return [("OK", lambda: None)]

        dialog = TestDialog()
        widget = dialog._build_widget()
        assert dialog._widget is widget
        assert widget is not None

    def test_base_dialog_set_result(self):
        """BaseDialog.set_result sets the future."""
        class TestDialog(BaseDialog):
            title = "Test"

            def build_body(self):
                return Label("Body")

        dialog = TestDialog()

        # Simulate prepare (creates future)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            future = loop.create_future()
            dialog._result_future = future

            dialog.set_result("test_value")
            assert future.done()
            assert future.result() == "test_value"
        finally:
            loop.close()

    def test_base_dialog_cancel(self):
        """BaseDialog.cancel sets escape_result."""
        class TestDialog(BaseDialog):
            title = "Test"
            escape_result = "escaped"

            def build_body(self):
                return Label("Body")

        dialog = TestDialog()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            future = loop.create_future()
            dialog._result_future = future

            dialog.cancel()
            assert future.result() == "escaped"
        finally:
            loop.close()


# =============================================================================
# Built-in Dialog Tests
# =============================================================================

class TestYesNoDialog:
    """Tests for Yes/No dialog."""

    def test_yes_no_dialog_creation(self):
        """Yes/No dialog is created correctly."""
        dialog = create_yes_no_dialog("Confirm", "Are you sure?")
        assert dialog.title == "Confirm"
        assert dialog.escape_result is False

    def test_yes_no_dialog_custom_buttons(self):
        """Yes/No dialog supports custom button text."""
        dialog = _YesNoDialog(
            title="Delete",
            text="Delete file?",
            yes_text="Delete",
            no_text="Keep",
        )
        buttons = dialog.get_buttons()
        assert buttons[0][0] == "Delete"
        assert buttons[1][0] == "Keep"

    def test_yes_no_dialog_body(self):
        """Yes/No dialog body is a Label."""
        dialog = _YesNoDialog("Test", "Body text")
        body = dialog.build_body()
        assert isinstance(body, Label)


class TestMessageDialog:
    """Tests for message dialog."""

    def test_message_dialog_creation(self):
        """Message dialog is created correctly."""
        dialog = create_message_dialog("Info", "Done!")
        assert dialog.title == "Info"
        assert dialog.escape_result is None

    def test_message_dialog_custom_ok(self):
        """Message dialog supports custom OK text."""
        dialog = _MessageDialog("Alert", "Warning!", ok_text="Got it")
        buttons = dialog.get_buttons()
        assert buttons[0][0] == "Got it"


class TestChoiceDialog:
    """Tests for choice dialog."""

    def test_choice_dialog_creation(self):
        """Choice dialog is created correctly."""
        dialog = create_choice_dialog("Action", "Choose:", ["A", "B", "C"])
        assert dialog.title == "Action"
        buttons = dialog.get_buttons()
        assert len(buttons) == 3
        assert buttons[0][0] == "A"
        assert buttons[1][0] == "B"
        assert buttons[2][0] == "C"

    def test_choice_dialog_escape_returns_none(self):
        """Choice dialog returns None on escape."""
        dialog = _ChoiceDialog("Test", "Choose:", ["X", "Y"])
        assert dialog.escape_result is None


class TestDropdownDialog:
    """Tests for dropdown dialog."""

    def test_dropdown_dialog_creation(self):
        """Dropdown dialog is created correctly."""
        dialog = create_dropdown_dialog(
            "Theme",
            "Select:",
            ["Light", "Dark", "System"],
        )
        assert dialog.title == "Theme"

    def test_dropdown_dialog_with_default(self):
        """Dropdown dialog respects default selection."""
        dialog = _DropdownDialog(
            "Theme",
            "Select:",
            ["Light", "Dark", "System"],
            default="Dark",
        )
        assert dialog._radio_list.current_value == "Dark"

    def test_dropdown_dialog_body_has_radiolist(self):
        """Dropdown dialog body contains RadioList."""
        dialog = _DropdownDialog("Test", "Select:", ["A", "B"])
        body = dialog.build_body()
        assert isinstance(body, HSplit)


# =============================================================================
# ConfigBasedDialog Tests
# =============================================================================

class TestConfigBasedDialog:
    """Tests for _ConfigBasedDialog wrapper."""

    def test_config_based_dialog_from_string_body(self):
        """ConfigBasedDialog handles string body."""
        config = DialogConfig(
            title="Test",
            body="String body",
            buttons=[ButtonConfig(text="OK", result=True)],
        )
        dialog = _ConfigBasedDialog(config)
        body = dialog.build_body()
        assert isinstance(body, Label)

    def test_config_based_dialog_from_container_body(self):
        """ConfigBasedDialog handles Container body."""
        container = HSplit([Label("Test")])
        config = DialogConfig(
            title="Test",
            body=container,
            buttons=[ButtonConfig(text="OK", result=True)],
        )
        dialog = _ConfigBasedDialog(config)
        body = dialog.build_body()
        assert body is container

    def test_config_based_dialog_buttons(self):
        """ConfigBasedDialog creates buttons from config."""
        config = DialogConfig(
            title="Test",
            body="Body",
            buttons=[
                ButtonConfig(text="Save", result="save"),
                ButtonConfig(text="Cancel", result=None),
            ],
        )
        dialog = _ConfigBasedDialog(config)
        buttons = dialog.get_buttons()
        assert len(buttons) == 2
        assert buttons[0][0] == "Save"
        assert buttons[1][0] == "Cancel"

    def test_config_based_dialog_escape_result(self):
        """ConfigBasedDialog inherits escape_result from config."""
        config = DialogConfig(
            title="Test",
            body="Body",
            escape_result="escaped",
        )
        dialog = _ConfigBasedDialog(config)
        assert dialog.escape_result == "escaped"


# =============================================================================
# DialogManager Tests
# =============================================================================

class TestDialogManager:
    """Tests for DialogManager (unit tests without full Application)."""

    def test_dialog_manager_initial_state(self):
        """DialogManager starts with correct initial state."""
        mock_session = MagicMock()
        mock_session.app = MagicMock()
        mock_session.app.layout = MagicMock()
        mock_session.app.key_bindings = None

        manager = DialogManager(mock_session)
        assert manager._visible is False
        assert manager._current_dialog is None
        assert manager._injected is False

    def test_dialog_manager_key_bindings_created(self):
        """DialogManager creates key bindings for Escape."""
        mock_session = MagicMock()
        mock_session.app = MagicMock()
        mock_session.app.layout = MagicMock()
        mock_session.app.key_bindings = None

        manager = DialogManager(mock_session)
        assert manager._key_bindings is not None


# =============================================================================
# Integration-style Tests (without full Application)
# =============================================================================

class TestDialogIntegration:
    """Integration tests for dialog result flow."""

    def test_dialog_result_flow(self):
        """Dialog result is properly passed through future."""
        class ResultDialog(BaseDialog):
            title = "Test"

            def build_body(self):
                return Label("Test")

            def get_buttons(self):
                return [("OK", lambda: self.set_result({"key": "value"}))]

        dialog = ResultDialog()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Simulate prepare
            future = loop.create_future()
            dialog._result_future = future

            # Simulate button click
            buttons = dialog.get_buttons()
            buttons[0][1]()  # Click OK

            assert future.done()
            assert future.result() == {"key": "value"}
        finally:
            loop.close()

    def test_multiple_buttons_return_correct_results(self):
        """Each button returns its configured result."""
        results = []

        class MultiButtonDialog(BaseDialog):
            title = "Test"

            def build_body(self):
                return Label("Choose")

            def get_buttons(self):
                return [
                    ("A", lambda: self.set_result("a")),
                    ("B", lambda: self.set_result("b")),
                    ("C", lambda: self.set_result("c")),
                ]

        for expected, idx in [("a", 0), ("b", 1), ("c", 2)]:
            dialog = MultiButtonDialog()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                future = loop.create_future()
                dialog._result_future = future

                buttons = dialog.get_buttons()
                buttons[idx][1]()  # Click button

                assert future.result() == expected
            finally:
                loop.close()


# =============================================================================
# Edge Cases
# =============================================================================

class TestDialogEdgeCases:
    """Edge case tests for dialogs."""

    def test_dialog_with_no_buttons(self):
        """Dialog can have no custom buttons (uses default OK)."""
        class NoButtonDialog(BaseDialog):
            title = "Info"

            def build_body(self):
                return Label("Just info")

            # Uses default get_buttons() which returns [("OK", ...)]

        dialog = NoButtonDialog()
        buttons = dialog.get_buttons()
        assert len(buttons) == 1
        assert buttons[0][0] == "OK"

    def test_dialog_escape_disabled(self):
        """Dialog with escape disabled doesn't set result."""
        class NoEscapeDialog(BaseDialog):
            title = "Important"
            escape_result = _UNSET  # Escape disabled

            def build_body(self):
                return Label("Must click button")

            def get_buttons(self):
                return [("Acknowledge", lambda: self.set_result(True))]

        dialog = NoEscapeDialog()
        from thinking_prompt.dialog import _Unset
        assert isinstance(dialog.escape_result, _Unset)

    def test_set_result_only_works_once(self):
        """Setting result multiple times doesn't change first result."""
        class TestDialog(BaseDialog):
            title = "Test"

            def build_body(self):
                return Label("Test")

        dialog = TestDialog()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            future = loop.create_future()
            dialog._result_future = future

            dialog.set_result("first")
            dialog.set_result("second")  # Should be ignored

            assert future.result() == "first"
        finally:
            loop.close()

    def test_config_button_closure_captures_correctly(self):
        """ButtonConfig results are captured correctly in closures."""
        config = DialogConfig(
            title="Test",
            body="Body",
            buttons=[
                ButtonConfig(text="One", result=1),
                ButtonConfig(text="Two", result=2),
                ButtonConfig(text="Three", result=3),
            ],
        )
        dialog = _ConfigBasedDialog(config)
        buttons = dialog.get_buttons()

        # Test each button
        for expected, idx in [(1, 0), (2, 1), (3, 2)]:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                future = loop.create_future()
                dialog._result_future = future

                buttons[idx][1]()  # Click button

                assert future.result() == expected

                # Reset for next iteration
                dialog._result_future = None
            finally:
                loop.close()
