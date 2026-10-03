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
    Dialog,
    DialogConfig,
    DialogManager,
    _UNSET,
    _ConfigBasedDialog,
    _choice_dialog,
    _dropdown_dialog,
    _message_dialog,
    _yes_no_dialog,
)

_STILL_OPEN = object()  # _click() result when the click didn't close the dialog


def _click(dialog: Any, index: int) -> Any:
    """Build the dialog's widget and click button ``index``.

    Returns the dialog's result, or _STILL_OPEN if the click didn't close it.
    """
    loop = asyncio.new_event_loop()
    try:
        dialog._result_future = loop.create_future()
        dialog._build_widget()
        dialog._buttons[index].handler()
        future = dialog._result_future
        return future.result() if future.done() else _STILL_OPEN
    finally:
        loop.close()


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

    def test_handler_defaults_to_none(self):
        assert ButtonConfig(text="OK").handler is None

    def test_result_and_handler_together_raise(self):
        with pytest.raises(ValueError, match="result or a handler, not both"):
            ButtonConfig(text="OK", result=1, handler=lambda: None)

    def test_handler_runs_on_click_instead_of_closing(self):
        clicks: list[str] = []
        config = DialogConfig(title="T", body="B", buttons=[
            ButtonConfig(text="Check", handler=lambda: clicks.append("clicked")),
            ButtonConfig(text="OK", result="ok"),
        ])
        dialog = _ConfigBasedDialog(config)
        assert _click(dialog, 0) is _STILL_OPEN
        assert clicks == ["clicked"]
        assert _click(dialog, 1) == "ok"


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

    def test_dialog_config_escape_enabled_by_default(self):
        """Like every other dialog, a DialogConfig closes on Escape with None."""
        config = DialogConfig(title="Test", body="Body")
        assert config.escapable is True
        assert config.escape_result is None

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

    def test_custom_dialog_subclass(self):
        """Custom dialog subclass works correctly."""
        class MyDialog(BaseDialog):
            title = "My Dialog"
            escape_result = "cancelled"

            def build_body(self):
                return Label("Custom body")

            def get_buttons(self):
                return [
                    ButtonConfig("OK", result="ok"),
                    ButtonConfig("Cancel", handler=self.cancel),
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
                return [ButtonConfig("OK")]

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

class TestBuiltinDialogs:
    """The session's built-in dialogs are plain Dialogs."""

    @staticmethod
    def _results(dialog: Dialog) -> list[Any]:
        return [_click(dialog, i) for i in range(len(dialog.get_buttons()))]

    def test_yes_no(self):
        d = _yes_no_dialog("Delete", "Delete file?", yes_text="Delete", no_text="Keep")
        assert isinstance(d, Dialog) and d.title == "Delete"
        assert isinstance(d.build_body(), Label)
        assert [b.text for b in d.get_buttons()] == ["Delete", "Keep"]
        assert self._results(d) == [True, False]
        assert (d.escape_result, d.escapable) == (False, True)

    def test_message(self):
        d = _message_dialog("Alert", "Warning!", ok_text="Got it")
        assert [b.text for b in d.get_buttons()] == ["Got it"]
        assert self._results(d) == [None]
        assert d.escape_result is None

    def test_choice(self):
        d = _choice_dialog("Action", "Choose:", ["A", "B", "C"])
        assert self._results(d) == ["A", "B", "C"]
        assert d.escape_result is None

    def test_dropdown_preselects_default_and_ok_returns_selection(self):
        d = _dropdown_dialog("Theme", "Select:", ["Light", "Dark", "System"], default="Dark")
        assert isinstance(d.build_body(), HSplit)
        assert [b.text for b in d.get_buttons()] == ["OK", "Cancel"]
        assert self._results(d) == ["Dark", None]

    def test_dropdown_without_default_selects_first(self):
        assert _click(_dropdown_dialog("Theme", "Select:", ["Light", "Dark"]), 0) == "Light"

    def test_dropdown_needs_at_least_one_option(self):
        with pytest.raises(ValueError, match="at least one option"):
            _dropdown_dialog("Theme", "Select:", [])


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
        assert [b.text for b in dialog.get_buttons()] == ["Save", "Cancel"]

    def test_config_based_dialog_escape_result(self):
        """ConfigBasedDialog inherits escape_result from config."""
        config = DialogConfig(
            title="Test",
            body="Body",
            escape_result="escaped",
        )
        dialog = _ConfigBasedDialog(config)
        assert dialog.escape_result == "escaped"

    def test_config_based_dialog_inherits_width(self):
        """ConfigBasedDialog forwards DialogConfig.width to BaseDialog.width."""
        config = DialogConfig(
            title="Test",
            body="Body",
            width=80,
        )
        dialog = _ConfigBasedDialog(config)
        assert dialog.width == 80

    def test_config_based_dialog_default_width_is_none(self):
        """When DialogConfig.width is None, BaseDialog.width stays None."""
        config = DialogConfig(title="Test", body="Body")
        dialog = _ConfigBasedDialog(config)
        assert dialog.width is None


class TestButtonConfigBehavior:
    """ButtonConfig.focused and ButtonConfig.style must affect the built widget."""

    def _build(self, buttons):
        config = DialogConfig(title="T", body="B", buttons=buttons)
        dialog = _ConfigBasedDialog(config)
        widget = dialog._build_widget()
        return dialog, widget

    def test_focused_button_recorded_for_initial_focus(self):
        """ButtonConfig(focused=True) marks that button as the initial focus target."""
        buttons = [
            ButtonConfig(text="One", result=1),
            ButtonConfig(text="Two", result=2, focused=True),
            ButtonConfig(text="Three", result=3),
        ]
        dialog, _ = self._build(buttons)

        # BaseDialog should expose the button window that wants focus on show.
        # `_initial_focus` is None when no button is focused; otherwise it is
        # the button's containing Window so DialogManager can call
        # app.layout.focus(...) on it.
        assert dialog._initial_focus is not None
        # And the focused-flag positions the second button:
        from prompt_toolkit.widgets import Button
        assert isinstance(dialog._focused_button, Button)
        assert dialog._focused_button.text == "Two"

    def test_no_focused_flag_means_no_initial_focus_override(self):
        """Without focused=True on any button, _initial_focus stays None."""
        buttons = [
            ButtonConfig(text="One", result=1),
            ButtonConfig(text="Two", result=2),
        ]
        dialog, _ = self._build(buttons)
        assert dialog._initial_focus is None
        assert dialog._focused_button is None

    def test_button_style_applied_to_window(self):
        """ButtonConfig.style is appended to the Button window's style classes."""
        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        buttons = [ButtonConfig(text="Danger", result=1, style="class:danger")]
        dialog, _ = self._build(buttons)

        # Find the Button window we built. _build_widget caches the buttons
        # in the Dialog body; we walk the get_buttons output and rebuild
        # is wasteful, so we expose the styled buttons via dialog._buttons.
        from prompt_toolkit.widgets import Button
        assert hasattr(dialog, "_buttons")
        btns = dialog._buttons
        assert len(btns) == 1
        btn = btns[0]
        assert isinstance(btn, Button)

        # Button.window.style is callable. Resolve it inside an app session
        # so get_app() works.
        with create_pipe_input() as inp:
            with create_app_session(input=inp, output=DummyOutput()):
                style = btn.window.style
                resolved = style() if callable(style) else style
                assert "class:danger" in resolved


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

    async def test_show_while_dialog_open_raises_and_first_still_resolves(self):
        """show() must refuse a second concurrent dialog.

        Overwriting _current_dialog would orphan the first dialog's
        result future — its awaiter would hang forever. Failing loudly
        is the contract; callers must close one dialog before opening
        the next."""
        mock_session = MagicMock()
        # _inject_float_container wraps the real layout container; a
        # MagicMock is rejected by FloatContainer, so provide a real one.
        mock_session.app.layout.container = Window()
        mock_session.app.key_bindings = None
        manager = DialogManager(mock_session)

        first = _message_dialog("First", "body")
        show_task = asyncio.create_task(manager.show(first))

        # Let show() advance to awaiting the first dialog's result.
        for _ in range(20):
            await asyncio.sleep(0)
            if manager._current_dialog is first:
                break
        assert manager._current_dialog is first

        with pytest.raises(RuntimeError, match="already being shown"):
            await manager.show(_message_dialog("Second", "body"))

        # The first dialog is unaffected and still resolvable.
        first.set_result("done")
        assert await asyncio.wait_for(show_task, timeout=1) == "done"
        assert manager._current_dialog is None


class TestDialogManagerFailureRecovery:
    """An exception while opening a dialog must not leave the manager
    believing a dialog is open — that would refuse every later dialog."""

    @staticmethod
    async def _show_and_close_message_dialog(session) -> None:
        task = asyncio.create_task(session.message_dialog("Next", "ok"))
        for _ in range(20):
            await asyncio.sleep(0)
            if session._dialogs._current_dialog is not None:
                break
        session._dialogs._current_dialog.set_result(None)
        await asyncio.wait_for(task, timeout=1)

    @staticmethod
    def _assert_closed(session) -> None:
        manager = session._dialogs
        assert manager._current_dialog is None
        assert manager._visible is False
        assert session.app.layout.has_focus(session.default_buffer)

    async def test_failing_build_body_does_not_block_next_dialog(self):
        from thinking_prompt import ThinkingPromptSession

        class Broken(BaseDialog):
            def build_body(self):
                raise RuntimeError("bug in build_body")

        session = ThinkingPromptSession()
        with pytest.raises(RuntimeError, match="bug in build_body"):
            await session.show_dialog(Broken())

        self._assert_closed(session)
        await self._show_and_close_message_dialog(session)

    async def test_dialog_with_nothing_focusable_raises_clear_error(self):
        """DialogConfig's buttons default to []; with a plain-text body the
        dialog has nothing to focus, so it could never be closed."""
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        with pytest.raises(ValueError, match="no focusable element"):
            await session.show_dialog(DialogConfig(title="Empty", body="hi"))

        self._assert_closed(session)
        await self._show_and_close_message_dialog(session)


# =============================================================================
# Integration-style Tests (without full Application)
# =============================================================================

class TestDialogIntegration:
    """Integration tests for dialog result flow."""

    def test_dialog_result_flow(self):
        """A subclass button's result reaches the awaiter."""
        class ResultDialog(BaseDialog):
            title = "Test"

            def build_body(self):
                return Label("Test")

            def get_buttons(self):
                return [ButtonConfig("OK", result={"key": "value"})]

        assert _click(ResultDialog(), 0) == {"key": "value"}

    def test_multiple_buttons_return_correct_results(self):
        """Each button returns its configured result."""
        class MultiButtonDialog(BaseDialog):
            title = "Test"

            def build_body(self):
                return Label("Choose")

            def get_buttons(self):
                return [ButtonConfig(t, result=t.lower()) for t in ("A", "B", "C")]

        dialog = MultiButtonDialog()
        assert [_click(dialog, i) for i in range(3)] == ["a", "b", "c"]


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
        assert [b.text for b in dialog.get_buttons()] == ["OK"]
        assert _click(dialog, 0) is None

    def test_dialog_escape_disabled(self):
        """A dialog opts out of Escape with escapable = False."""
        class NoEscapeDialog(BaseDialog):
            title = "Important"
            escapable = False

            def build_body(self):
                return Label("Must click button")

            def get_buttons(self):
                return [("Acknowledge", lambda: self.set_result(True))]

        assert NoEscapeDialog().escapable is False
        assert BaseDialog.escapable is True

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
        assert [_click(dialog, i) for i in range(3)] == [1, 2, 3]



class TestDeprecatedUnsetEscape:
    """escape_result=_UNSET (the old, private way to disable Escape) still
    works, but warns — and its sentinel never reaches the caller."""

    @staticmethod
    def _unset_dialog():
        class Legacy(BaseDialog):
            title = "Legacy"
            escape_result = _UNSET

            def build_body(self):
                return Label("body")

            def get_buttons(self):
                return [ButtonConfig("OK", result="ok"), ButtonConfig("Cancel", handler=self.cancel)]

        return Legacy()

    async def test_unset_disables_escape_and_warns(self):
        from prompt_toolkit.keys import Keys

        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        dialog = self._unset_dialog()
        with pytest.warns(DeprecationWarning, match="escapable"):
            task = asyncio.create_task(session.show_dialog(dialog))
            for _ in range(20):
                await asyncio.sleep(0)
                if session._dialogs._current_dialog is dialog:
                    break
        escape = next(
            b for b in session._dialogs._key_bindings.bindings if b.keys == (Keys.Escape,)
        )
        escape.handler(MagicMock())
        await asyncio.sleep(0)
        assert not task.done()
        dialog.set_result("ok")
        assert await asyncio.wait_for(task, timeout=1) == "ok"

    def test_cancel_returns_none_not_the_sentinel(self):
        dialog = self._unset_dialog()
        loop = asyncio.new_event_loop()
        try:
            dialog._result_future = loop.create_future()
            dialog.cancel()
            assert dialog._result_future.result() is None
        finally:
            loop.close()


class TestDialog:
    """Dialog is concrete: built from arguments or subclassed. Its class
    attributes are the only defaults."""

    def test_defaults_come_from_class_attributes(self):
        d = Dialog()
        assert (d.title, d.body) == ("", "")
        assert [b.text for b in d.get_buttons()] == ["OK"]
        assert (d.escape_result, d.escapable) == (None, True)
        assert (d.width, d.top, d.height) == (None, None, None)

    def test_positional_title_body_buttons(self):
        buttons = [ButtonConfig("Yes", result=True)]
        d = Dialog("Delete?", "Sure?", buttons)
        assert (d.title, d.body) == ("Delete?", "Sure?")
        assert d.get_buttons() == buttons

    def test_constructor_overrides_only_passed_options(self):
        class Wide(Dialog):
            width = 70
            escape_result = "dismissed"

        d = Wide(title="T", top=2)
        assert (d.title, d.top) == ("T", 2)
        assert (d.width, d.escape_result) == (70, "dismissed")

    def test_explicit_none_overrides_a_class_default(self):
        class Wide(Dialog):
            width = 70
            top = 3
            escape_result = "dismissed"

        d = Wide(width=None, top=None, escape_result=None)
        assert (d.width, d.top, d.escape_result) == (None, None, None)

    def test_subclass_attributes_and_super_init_arguments(self):
        class Confirm(Dialog):
            title = "Confirm"
            escapable = False

            def __init__(self) -> None:
                super().__init__(width=50)

        d = Confirm()
        assert (d.title, d.escapable, d.width) == ("Confirm", False, 50)

    def test_text_body_becomes_label_container_body_is_kept(self):
        assert isinstance(Dialog(body="hi").build_body(), Label)
        container = HSplit([Label("x")])
        assert Dialog(body=container).build_body() is container

    def test_formatted_text_body_becomes_label(self):
        from prompt_toolkit.formatted_text import HTML

        assert isinstance(Dialog(body=HTML("<b>hi</b>")).build_body(), Label)

    def test_explicit_empty_buttons_means_no_buttons(self):
        assert Dialog("T", "B", buttons=[]).get_buttons() == []

    def test_get_buttons_returns_a_fresh_list(self):
        d = Dialog()
        d.get_buttons().append(ButtonConfig("Extra"))
        assert [b.text for b in d.get_buttons()] == ["OK"]


class TestDialogButtons:
    """One button form: ButtonConfig, with a fixed result or a handler."""

    def test_result_button_closes_with_its_result(self):
        d = Dialog("T", "B", [ButtonConfig("A", result="a"), ButtonConfig("B", result="b")])
        assert [_click(d, 0), _click(d, 1)] == ["a", "b"]

    def test_handler_runs_and_can_leave_the_dialog_open(self):
        attempts: list[str] = []

        def submit() -> None:
            attempts.append("submit")
            if len(attempts) == 2:
                d.set_result("done")

        d = Dialog("T", "B", [ButtonConfig("Submit", handler=submit)])
        assert _click(d, 0) is _STILL_OPEN
        assert _click(d, 0) == "done"
        assert attempts == ["submit", "submit"]

    def test_handler_can_cancel(self):
        class Asks(Dialog):
            escape_result = "dismissed"

            def get_buttons(self):
                return [ButtonConfig("Cancel", handler=self.cancel)]

        assert _click(Asks(), 0) == "dismissed"

    def test_focused_and_style_apply_in_subclass_dialogs(self):
        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class Styled(Dialog):
            def get_buttons(self):
                return [ButtonConfig("One"), ButtonConfig("Two", focused=True, style="class:danger")]

        d = Styled()
        d._build_widget()
        assert d._focused_button is d._buttons[1]
        assert d._initial_focus is d._buttons[1].window
        with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
            style = d._buttons[1].window.style
            assert "class:danger" in (style() if callable(style) else style)

    def test_tuple_buttons_raise_with_migration_hint(self):
        class Old(Dialog):
            def get_buttons(self):
                return [("OK", lambda: None)]

        with pytest.raises(TypeError, match=r"Use ButtonConfig\(label, handler=\.\.\.\)"):
            Old()._build_widget()

    async def test_handler_exception_is_reported_and_dialog_stays_open(self, caplog):
        import logging

        from thinking_prompt import ThinkingPromptSession

        def boom() -> None:
            raise KeyError("x")

        session = ThinkingPromptSession()
        d = Dialog("T", "B", [ButtonConfig("Go", handler=boom)])
        d._prepare(session._dialogs)
        d._build_widget()
        with caplog.at_level(logging.ERROR, logger="thinking_prompt"):
            d._buttons[0].handler()

        assert d._result_future is not None and not d._result_future.done()
        last = session._display.history.iter_entries()[-1]
        assert last.text == "[ERROR] Dialog button error: KeyError: 'x'\n"
        assert any(r.exc_info and r.exc_info[0] is KeyError for r in caplog.records)

    async def test_same_dialog_can_be_shown_twice(self):
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        d = Dialog("T", "B", [ButtonConfig("OK", result="ok")])
        for expected in ("first", "second"):
            task = asyncio.create_task(session.show_dialog(d))
            for _ in range(20):
                await asyncio.sleep(0)
                if session._dialogs._current_dialog is d:
                    break
            d.set_result(expected)
            assert await asyncio.wait_for(task, timeout=1) == expected
