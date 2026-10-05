"""
Tests for the dialog system.

Note: Many dialog tests require a running Application, so we use
async fixtures and simulate button clicks via the result future.
"""
from __future__ import annotations

import asyncio
import dataclasses
from typing import Any
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.widgets import Label

from thinking_prompt.dialog import (
    ButtonConfig,
    Dialog,
    DialogManager,
    _checklist_dialog,
    _choice_dialog,
    _dropdown_dialog,
    _message_dialog,
    _yes_no_dialog,
)

_STILL_OPEN = object()  # _click() result when the click didn't close the dialog


def _click(dialog: Any, index: int) -> Any:
    """Click button ``index`` (run the dialog's click logic for it).

    Returns the dialog's result, or _STILL_OPEN if the click didn't close it.
    """
    loop = asyncio.new_event_loop()
    try:
        dialog._result_future = loop.create_future()
        dialog._click_handler(dialog._button_configs()[index])()
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

    def test_async_handler_raises_at_construction(self):
        async def fn() -> None:
            pass

        with pytest.raises(TypeError, match="not async"):
            ButtonConfig(text="Go", handler=fn)

    def test_frozen_rejects_attribute_assignment(self):
        btn = ButtonConfig("OK")
        with pytest.raises(dataclasses.FrozenInstanceError):
            btn.text = "x"

    def test_handler_runs_on_click_instead_of_closing(self):
        clicks: list[str] = []
        dialog = Dialog("T", "B", [
            ButtonConfig(text="Check", handler=lambda: clicks.append("clicked")),
            ButtonConfig(text="OK", result="ok"),
        ])
        assert _click(dialog, 0) is _STILL_OPEN
        assert clicks == ["clicked"]
        assert _click(dialog, 1) == "ok"


# =============================================================================
# Dialog Tests
# =============================================================================

class TestDialogSubclass:
    """Tests for Dialog class."""

    def test_custom_dialog_subclass(self):
        """Custom dialog subclass works correctly."""
        class MyDialog(Dialog):
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

    def test_dialog_set_result(self):
        """Dialog.set_result sets the future."""
        class TestDialog(Dialog):
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

    def test_dialog_cancel(self):
        """Dialog.cancel sets escape_result."""
        class TestDialog(Dialog):
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

    @pytest.mark.parametrize("build", [
        lambda p: _yes_no_dialog("T", "B", placement=p),
        lambda p: _message_dialog("T", "B", placement=p),
        lambda p: _choice_dialog("T", "B", ["a"], placement=p),
        lambda p: _dropdown_dialog("T", "B", ["a"], placement=p),
        lambda p: _checklist_dialog("T", "B", ["a"], placement=p),
    ], ids=["yes_no", "message", "choice", "dropdown", "checklist"])
    def test_builders_pin_the_placement_they_built_for(self, build):
        assert build("inline").placement == "inline"
        assert build("box").placement == "box"

    def test_inline_dropdown_is_one_action_per_option_starting_on_the_default(self):
        d = _dropdown_dialog("Theme", "Select:", ["Light", "Dark", "System"], default="Dark",
                             placement="inline")
        assert isinstance(d.build_body(), Label)
        buttons = d.get_buttons()
        assert [b.text for b in buttons] == ["Light", "Dark", "System"]
        assert [b.focused for b in buttons] == [False, True, False]
        assert self._results(d) == ["Light", "Dark", "System"]
        assert d.escape_result is None

    def test_checklist_ok_returns_the_checked_options_cancel_none(self):
        d = _checklist_dialog("Tools", "Pick any", ["a", "b", "c"], defaults=["c", "a", "z"])
        assert [b.text for b in d.get_buttons()] == ["OK", "Cancel"]
        assert self._results(d) == [["a", "c"], None]
        assert d.escape_result is None

    def test_checklist_needs_options(self):
        with pytest.raises(ValueError, match="at least one option"):
            _checklist_dialog("Tools", "Pick any", [])

    def test_checklist_rows_walk_with_arrows_in_a_box_only(self):
        box = _checklist_dialog("T", "", ["a", "b"], placement="box").build_body()
        assert box.key_bindings.get_bindings_for_keys((Keys.Down,)) != []
        inline = _checklist_dialog("T", "", ["a", "b"], placement="inline").build_body()
        assert inline.key_bindings is None


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
        mock_session.dialog_placement = "box"
        # A running app: show() refuses to open a dialog without one.
        mock_session.app.is_running = True
        mock_session.app.future = asyncio.get_running_loop().create_future()
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


class TestDialogNeedsRunningSession:
    """A dialog is answered through the running app's key bindings. Without
    a running app nothing can ever answer it, so show() used to wait
    forever. (wait_for turns such a hang into a test failure.)"""

    @pytest.mark.parametrize(
        "open_dialog",
        [
            lambda s: s.show_dialog(Dialog("T", "B", [ButtonConfig("OK")])),
            lambda s: s.yes_no_dialog("T", "B"),
            lambda s: s.message_dialog("T", "B"),
            lambda s: s.choice_dialog("T", "B", ["a"]),
            lambda s: s.dropdown_dialog("T", "B", ["a"]),
            lambda s: s.checklist_dialog("T", "B", ["a"]),
            lambda s: s.show_settings_dialog("T", []),
        ],
        ids=["show_dialog", "yes_no", "message", "choice", "dropdown", "checklist", "settings"],
    )
    async def test_raises_before_the_session_runs(self, open_dialog):
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        with pytest.raises(RuntimeError, match="needs a running session"):
            await asyncio.wait_for(open_dialog(session), timeout=1)
        assert session._dialogs._current_dialog is None


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

    async def test_failing_build_body_does_not_block_next_dialog(self, running_session):
        class Broken(Dialog):
            def build_body(self):
                raise RuntimeError("bug in build_body")

        session = running_session
        with pytest.raises(RuntimeError, match="bug in build_body"):
            await session.show_dialog(Broken())

        self._assert_closed(session)
        await self._show_and_close_message_dialog(session)

    async def test_dialog_with_nothing_focusable_raises_clear_error(self, running_session):
        """No buttons (the default) and a plain-text body: nothing can take
        keyboard focus, so typing would go to the hidden prompt instead."""
        session = running_session
        with pytest.raises(ValueError, match="nothing to focus"):
            await asyncio.wait_for(session.show_dialog(Dialog("Empty", "hi")), timeout=1)

        self._assert_closed(session)
        await self._show_and_close_message_dialog(session)


# =============================================================================
# Integration-style Tests (without full Application)
# =============================================================================

class TestDialogIntegration:
    """Integration tests for dialog result flow."""

    def test_dialog_result_flow(self):
        """A subclass button's result reaches the awaiter."""
        class ResultDialog(Dialog):
            title = "Test"

            def build_body(self):
                return Label("Test")

            def get_buttons(self):
                return [ButtonConfig("OK", result={"key": "value"})]

        assert _click(ResultDialog(), 0) == {"key": "value"}

    def test_multiple_buttons_return_correct_results(self):
        """Each button returns its configured result."""
        class MultiButtonDialog(Dialog):
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
        """A Dialog has no buttons unless it's given some."""
        class NoButtonDialog(Dialog):
            title = "Info"

            def build_body(self):
                return Label("Just info")

        assert NoButtonDialog().get_buttons() == []

    def test_dialog_escape_disabled(self):
        """A dialog opts out of Escape with escapable = False."""
        class NoEscapeDialog(Dialog):
            title = "Important"
            escapable = False

            def build_body(self):
                return Label("Must click button")

            def get_buttons(self):
                return [ButtonConfig("Acknowledge", result=True)]

        assert NoEscapeDialog().escapable is False
        assert Dialog.escapable is True

    def test_set_result_only_works_once(self):
        """Setting result multiple times doesn't change first result."""
        class TestDialog(Dialog):
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
        dialog = Dialog("Test", "Body", [
            ButtonConfig(text="One", result=1),
            ButtonConfig(text="Two", result=2),
            ButtonConfig(text="Three", result=3),
        ])
        assert [_click(dialog, i) for i in range(3)] == [1, 2, 3]


class TestDialog:
    """Dialog is concrete: built from arguments or subclassed. Its class
    attributes are the only defaults."""

    def test_defaults_come_from_class_attributes(self):
        d = Dialog()
        assert (d.title, d.body) == ("", "")
        assert d.get_buttons() == []
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
        class WithOk(Dialog):
            buttons = (ButtonConfig("OK"),)

        d = WithOk()
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

    def test_tuple_buttons_raise_with_migration_hint(self):
        class Old(Dialog):
            def get_buttons(self):
                return [("OK", lambda: None)]

        with pytest.raises(TypeError, match=r"Use ButtonConfig\(label, handler=\.\.\.\)"):
            Old()._button_configs()

    async def test_handler_exception_is_reported_and_dialog_stays_open(self, caplog):
        import logging

        from thinking_prompt import ThinkingPromptSession

        def boom() -> None:
            raise KeyError("x")

        session = ThinkingPromptSession()
        d = Dialog("T", "B", [ButtonConfig("Go", handler=boom)])
        d._prepare(session._dialogs)
        with caplog.at_level(logging.ERROR, logger="thinking_prompt"):
            d._click_handler(d._button_configs()[0])()

        assert d._result_future is not None and not d._result_future.done()
        last = session._display.history.iter_entries()[-1]
        assert last.text == "[ERROR] Dialog button error: KeyError: 'x'\n"
        assert any(r.exc_info and r.exc_info[0] is KeyError for r in caplog.records)

    async def test_handler_returning_awaitable_is_closed_and_reported(self, caplog):
        import logging

        from thinking_prompt import ThinkingPromptSession

        coros: list[Any] = []

        async def coro_fn() -> None:
            pass

        def make_coro() -> Any:
            coro = coro_fn()
            coros.append(coro)
            return coro

        session = ThinkingPromptSession()
        d = Dialog("T", "B", [ButtonConfig("Go", handler=lambda: make_coro())])
        d._prepare(session._dialogs)
        with caplog.at_level(logging.ERROR, logger="thinking_prompt"):
            d._click_handler(d._button_configs()[0])()

        assert d._result_future is not None and not d._result_future.done()
        last = session._display.history.iter_entries()[-1]
        assert last.text == (
            "[ERROR] Dialog button error: TypeError: button handler returned "
            "an awaitable; handlers must be regular functions\n"
        )
        coro = coros[0]
        assert coro.cr_frame is None

    async def test_same_dialog_can_be_shown_twice(self, running_session):
        session = running_session
        d = Dialog("T", "B", [ButtonConfig("OK", result="ok")])
        for expected in ("first", "second"):
            task = asyncio.create_task(session.show_dialog(d))
            for _ in range(20):
                await asyncio.sleep(0)
                if session._dialogs._current_dialog is d:
                    break
            d.set_result(expected)
            assert await asyncio.wait_for(task, timeout=1) == expected


class TestRemovedApi:
    """0.4 removes the old dialog API outright (no deprecation period)."""

    def test_old_names_are_gone(self):
        import thinking_prompt
        import thinking_prompt.dialog as dialog_module

        for name in ("BaseDialog", "DialogConfig"):
            assert not hasattr(thinking_prompt, name)
            assert name not in thinking_prompt.__all__
        for name in ("BaseDialog", "DialogConfig", "_ConfigBasedDialog", "_UNSET", "_Unset"):
            assert not hasattr(dialog_module, name)

    async def test_show_dialog_rejects_non_dialogs_with_migration_hint(self):
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        with pytest.raises(
            TypeError, match=r"takes a thinking_prompt\.Dialog, got dict\..*DialogConfig was removed"
        ):
            await session.show_dialog({"title": "x"})
        assert session._dialogs._current_dialog is None

    async def test_show_dialog_rejects_prompt_toolkit_dialog_widget(self):
        from prompt_toolkit.widgets import Dialog as PTDialog
        from prompt_toolkit.widgets import Label

        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        with pytest.raises(TypeError, match=r"got prompt_toolkit\.widgets\.dialogs\.Dialog"):
            await session.show_dialog(PTDialog(body=Label("x")))
        assert session._dialogs._current_dialog is None

    async def test_show_dialog_rejects_the_class_itself(self):
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        with pytest.raises(TypeError, match=r"takes a Dialog instance, got the class Dialog"):
            await session.show_dialog(Dialog)
        assert session._dialogs._current_dialog is None


class TestPlacement:
    """placement: per dialog (attribute or argument), else the session default."""

    def test_default_is_none_meaning_the_session_default(self):
        assert Dialog().placement is None

    def test_constructor_argument_and_class_attribute(self):
        class Inline(Dialog):
            placement = "inline"

        assert Dialog(placement="inline").placement == "inline"
        assert Inline().placement == "inline"
        assert Inline(placement="box").placement == "box"

    def test_invalid_placement_raises(self):
        with pytest.raises(ValueError, match="placement must be 'box' or 'inline', got 'side'"):
            Dialog(placement="side")

    def test_session_default(self):
        from thinking_prompt import ThinkingPromptSession

        assert ThinkingPromptSession().dialog_placement == "box"
        assert ThinkingPromptSession(dialog_placement="inline").dialog_placement == "inline"
        with pytest.raises(ValueError, match="placement must be"):
            ThinkingPromptSession(dialog_placement="side")

    @staticmethod
    async def _open(session, dialog) -> asyncio.Task:
        task = asyncio.create_task(session.show_dialog(dialog))
        for _ in range(20):
            await asyncio.sleep(0)
            if session._dialogs._current_dialog is dialog:
                break
        assert session._dialogs._current_dialog is dialog
        return task

    async def test_dialog_placement_wins_over_the_session_default(self, run_session):
        async with run_session(dialog_placement="inline") as session:
            boxed = Dialog("T", "B", [ButtonConfig("OK")], placement="box")
            task = await self._open(session, boxed)
            assert session._dialogs.inline_view is None
            boxed.set_result("box")
            assert await asyncio.wait_for(task, timeout=1) == "box"

            default = Dialog("T", "B", [ButtonConfig("OK")])
            task = await self._open(session, default)
            assert session._dialogs.inline_view is not None
            default.set_result("inline")
            assert await asyncio.wait_for(task, timeout=1) == "inline"
            assert default.placement is None  # showing never writes placement
            assert session._dialogs.inline_view is None

    async def test_same_dialog_inline_then_as_a_box(self, running_session):
        dialog = Dialog("T", "B", [ButtonConfig("OK", result="ok")])
        for placement in ("inline", "box"):
            dialog.placement = placement
            task = await self._open(running_session, dialog)
            assert (running_session._dialogs.inline_view is not None) == (placement == "inline")
            dialog.set_result(placement)
            assert await asyncio.wait_for(task, timeout=1) == placement

    async def test_bad_class_attribute_raises_when_shown(self, running_session):
        class Bad(Dialog):
            placement = "side"

        with pytest.raises(ValueError, match="placement must be"):
            await asyncio.wait_for(
                running_session.show_dialog(Bad("T", "B", [ButtonConfig("OK")])), timeout=1
            )
        assert running_session._dialogs._current_dialog is None

    async def test_inline_dialog_with_nothing_focusable_raises(self, running_session):
        with pytest.raises(ValueError, match="nothing to focus"):
            await asyncio.wait_for(
                running_session.show_dialog(Dialog("Empty", "hi", placement="inline")), timeout=1
            )
        assert running_session._dialogs._current_dialog is None
        assert running_session._dialogs.inline_view is None


class TestHelperPlacement:
    """Every helper takes placement=; None means the session's dialog_placement."""

    @pytest.fixture
    def captured(self, monkeypatch):
        from thinking_prompt import ThinkingPromptSession

        def make(**kwargs):
            session = ThinkingPromptSession(**kwargs)
            shown: list = []

            async def capture(dialog):
                shown.append(dialog)

            monkeypatch.setattr(session._dialogs, "show", capture)
            return session, shown

        return make

    @pytest.mark.parametrize("call", [
        lambda s, **kw: s.yes_no_dialog("T", "B", **kw),
        lambda s, **kw: s.message_dialog("T", "B", **kw),
        lambda s, **kw: s.choice_dialog("T", "B", ["a"], **kw),
        lambda s, **kw: s.dropdown_dialog("T", "B", ["a"], **kw),
        lambda s, **kw: s.checklist_dialog("T", "B", ["a"], **kw),
    ], ids=["yes_no", "message", "choice", "dropdown", "checklist"])
    async def test_session_default_and_per_call_override(self, captured, call):
        session, shown = captured(dialog_placement="inline")
        await call(session)
        await call(session, placement="box")
        assert [d.placement for d in shown] == ["inline", "box"]

    async def test_invalid_placement_raises(self, captured):
        session, shown = captured()
        with pytest.raises(ValueError, match="placement must be"):
            await session.yes_no_dialog("T", "B", placement="side")
        assert shown == []
