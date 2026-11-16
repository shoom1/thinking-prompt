"""
Tests for the dialog system.

Note: Many dialog tests require a running Application, so we use
async fixtures and simulate button clicks via the result future.
"""
from __future__ import annotations

import asyncio
import dataclasses
import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.formatted_text import ANSI, HTML, FormattedText
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.widgets import Label

from thinking_prompt.dialog import (
    ButtonConfig,
    Dialog,
    DialogManager,
    _checklist_dialog,
    _button_dialog,
    _choice_dialog,
    _message_dialog,
    _yes_no_dialog,
)
from thinking_prompt.dialog_inline import build_inline
from thinking_prompt.fields import ChoiceField, TextField

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
    def test_focused_is_true_or_false(self):
        with pytest.raises(ValueError, match=r"^ButtonConfig focused must be True or False, got 'no'$"):
            ButtonConfig("OK", focused="no")  # type: ignore[arg-type]

    @pytest.mark.parametrize("name", ["text", "style"])
    def test_its_text_and_style_are_strs(self, name):
        """A label that isn't a str failed when the dialog was shown."""
        kwargs: dict[str, Any] = {"text": "OK", name: 5}
        with pytest.raises(ValueError, match=rf"^ButtonConfig {name} must be a str, got 5$"):
            ButtonConfig(**kwargs)

    @pytest.mark.parametrize(
        "style", ["danger", "bright_red", "red on white", "bold redd", "fg:#12"],
        ids=["a word", "Rich's name", "Rich's syntax", "a typo", "short hex"],
    )
    def test_a_style_prompt_toolkit_cant_use_is_refused(self, style):
        """Taken, it raised at every redraw of the dialog: prompt_toolkit's
        "Press ENTER" screen came back after each key, and none got out."""
        message = rf"^ButtonConfig 'Delete': style {re.escape(repr(style))} isn't one prompt_toolkit can use: "
        with pytest.raises(ValueError, match=message):
            ButtonConfig("Delete", style=style)

    def test_a_style_can_name_classes(self):
        assert ButtonConfig("Delete", style="class:danger fg:ansired bold").style == "class:danger fg:ansired bold"

    """Tests for ButtonConfig dataclass."""

    def test_button_config_defaults_and_values(self):
        """ButtonConfig's default values, and the ones it's given."""
        btn = ButtonConfig(text="OK")
        assert btn.text == "OK"
        assert btn.result is None
        assert btn.focused is False
        assert btn.style == ""
        btn = ButtonConfig(text="Save", result={"action": "save"}, focused=True, style="bg:red")
        assert (btn.result, btn.focused, btn.style) == ({"action": "save"}, True, "bg:red")

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
        d = _button_dialog("Action", "Choose:", ["A", "B", "C"])
        assert self._results(d) == ["A", "B", "C"]
        assert d.escape_result is None

    def test_dropdown_preselects_default_and_ok_returns_selection(self):
        d = _choice_dialog("Theme", "Select:", ["Light", "Dark", "System"], default="Dark")
        assert d.values == {"choice": "Dark"}
        assert [b.text for b in d.get_buttons()] == ["OK", "Cancel"]
        assert self._results(d) == ["Dark", None]

    def test_dropdown_needs_at_least_one_option(self):
        with pytest.raises(ValueError, match="at least one option"):
            _choice_dialog("Theme", "Select:", [])

    def test_inline_dropdown_is_one_action_per_option_starting_on_the_default(self):
        d = _choice_dialog("Theme", "Select:", ["Light", "Dark", "System"], default="Dark",
                             placement="inline")
        assert isinstance(d.build_body(), Label)
        buttons = d.get_buttons()
        assert [b.text for b in buttons] == ["Light", "Dark", "System"]
        assert [b.focused for b in buttons] == [False, True, False]
        assert self._results(d) == ["Light", "Dark", "System"]
        assert d.escape_result is None

    def test_checklist_ok_returns_the_checked_options_cancel_none(self):
        d = _checklist_dialog("Tools", "Pick any", ["a", "b", "c"], default=["c", "a"])
        assert [b.text for b in d.get_buttons()] == ["OK", "Cancel"]
        assert self._results(d) == [["a", "c"], None]
        assert d.escape_result is None

    def test_checklist_needs_options(self):
        with pytest.raises(ValueError, match="at least one option"):
            _checklist_dialog("Tools", "Pick any", [])

    @pytest.mark.parametrize("default", ["search", None], ids=["a str", "None"])
    def test_checklist_default_is_a_sequence_of_options(self, default):
        """A str would be taken letter by letter, none of them an option."""
        with pytest.raises(ValueError, match=r"checklist_dialog\(\): default must be a sequence of options"):
            _checklist_dialog("Tools", "Pick any", ["search", "code"], default=default)

    def test_buttons_need_options(self):
        with pytest.raises(ValueError, match=r"button_dialog\(\) needs at least one option"):
            _button_dialog("Action", "Choose:", [])

    @pytest.mark.parametrize("build,call", [
        (lambda options: _button_dialog("T", "B", options), "button_dialog()"),
        (lambda options: _choice_dialog("T", "B", options), "choice_dialog()"),
        (lambda options: _choice_dialog("T", "B", options, placement="inline"), "choice_dialog()"),
        (lambda options: _checklist_dialog("T", "B", options), "checklist_dialog()"),
        (lambda options: _checklist_dialog("T", "B", options, placement="inline"), "checklist_dialog()"),
    ], ids=["button", "choice box", "choice inline", "checklist box", "checklist inline"])
    def test_an_option_listed_twice_is_refused_naming_the_call(self, build, call):
        """In both placements, and naming the call, not the field it builds."""
        with pytest.raises(ValueError, match=rf"^{re.escape(call)}: option 'a' is listed twice"):
            build(["a", "b", "a"])

    HELPERS = [
        (lambda options: _button_dialog("T", "B", options), "button_dialog()"),
        (lambda options: _choice_dialog("T", "B", options), "choice_dialog()"),
        (lambda options: _choice_dialog("T", "B", options, placement="inline"), "choice_dialog()"),
        (lambda options: _checklist_dialog("T", "B", options), "checklist_dialog()"),
        (lambda options: _checklist_dialog("T", "B", options, placement="inline"), "checklist_dialog()"),
    ]
    HELPER_IDS = ["button", "choice box", "choice inline", "checklist box", "checklist inline"]

    @pytest.mark.parametrize("build,call", HELPERS, ids=HELPER_IDS)
    def test_an_option_that_isnt_a_str_is_refused_naming_the_call(self, build, call):
        """choice_dialog("Port", "Pick", [8080, 8081]) opened, then raised
        TypeError at every redraw: no key got out."""
        with pytest.raises(ValueError, match=rf"^{re.escape(call)}: options must be str, got 8080"):
            build([8080, 8081])

    @pytest.mark.parametrize("build,call", HELPERS, ids=HELPER_IDS)
    def test_options_given_as_one_str_are_refused_naming_the_call(self, build, call):
        with pytest.raises(ValueError, match=rf"^{re.escape(call)}: options must be a sequence of str, got 'ab'"):
            build("ab")

    @pytest.mark.parametrize("placement", ["box", "inline"])
    def test_a_choice_default_that_isnt_an_option_is_refused(self, placement):
        with pytest.raises(ValueError, match=r"^choice_dialog\(\): default 'Blue' isn't one of its options"):
            _choice_dialog("T", "B", ["Light", "Dark"], default="Blue", placement=placement)

    @pytest.mark.parametrize("placement", ["box", "inline"])
    def test_a_checklist_default_that_isnt_an_option_is_refused(self, placement):
        with pytest.raises(ValueError, match=r"^checklist_dialog\(\): default 'c' isn't one of its options"):
            _checklist_dialog("T", "B", ["a", "b"], default=["c"], placement=placement)

    @pytest.mark.parametrize("build,call", HELPERS, ids=HELPER_IDS)
    @pytest.mark.parametrize("options", [{"a", "b"}, (o for o in ["a", "b"])], ids=["set", "generator"])
    def test_options_that_arent_a_sequence_are_refused_naming_the_call(self, build, call, options):
        """A set's order changes from run to run."""
        with pytest.raises(ValueError, match=rf"^{re.escape(call)}: options must be a sequence of str, got "):
            build(options)

    def test_box_dropdown_is_a_choice_list_starting_on_the_default(self):
        d = _choice_dialog("Theme", "Select:", ["Light", "Dark", "System"], default="Dark")
        d._placement = "box"
        _, start = d._content()
        (control,) = d._form.controls
        assert isinstance(control.item, ChoiceField) and control.item.label == ""
        assert start is control._group.rows[1].window

    def test_box_dropdown_without_a_default_starts_on_the_first_option(self):
        d = _choice_dialog("Theme", "Select:", ["Light", "Dark"])
        d._placement = "box"
        _, start = d._content()
        (control,) = d._form.controls
        assert start is control._group.rows[0].window
        assert d.values == {control.item.key: "Light"}


# =============================================================================
# DialogManager Tests
# =============================================================================

class TestDialogManager:
    """Tests for DialogManager (unit tests without full Application)."""

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

        with pytest.raises(RuntimeError, match=r"already being shown.*asyncio\.Lock"):
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
            lambda s: s.button_dialog("T", "B", ["a"]),
            lambda s: s.choice_dialog("T", "B", ["a"]),
            lambda s: s.checklist_dialog("T", "B", ["a"]),
        ],
        ids=["show_dialog", "yes_no", "message", "button", "choice", "checklist"],
    )
    async def test_raises_before_the_session_runs(self, open_dialog):
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        with pytest.raises(RuntimeError, match=r"needs a running session.*`async with session:`"):
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
        assert session.app.layout.has_focus(session._default_buffer)

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


class TestDialog:
    """Dialog is concrete: built from arguments or subclassed. Its class
    attributes are the only defaults."""

    def test_a_title_that_isnt_a_str_is_refused(self):
        """Dialog(title=5) opened, then raised TypeError at every redraw."""
        with pytest.raises(ValueError, match=r"^Dialog title must be a str, got 5$"):
            Dialog(5, "B", [ButtonConfig("OK")])  # type: ignore[arg-type]

    def test_escapable_is_true_or_false(self):
        """escapable="no" left Escape working."""
        with pytest.raises(ValueError, match=r"^Dialog escapable must be True or False, got 'no'$"):
            Dialog("T", "B", [ButtonConfig("OK")], escapable="no")  # type: ignore[arg-type]

    async def test_a_subclasss_title_is_checked_when_shown(self):
        """A class attribute (or a property) is read when the dialog is shown:
        a subclass sets what a property reads after Dialog.__init__."""

        class Bad(Dialog):
            title = 5  # type: ignore[assignment]

        dialog = Bad()
        with pytest.raises(ValueError, match=r"^Dialog title must be a str, got 5$"):
            dialog._prepare(MagicMock())

    async def test_a_subclass_makes_its_title_and_body_from_its_own_attributes(self):
        """Read in Dialog.__init__, the properties raised AttributeError."""

        class Edit(Dialog):
            def __init__(self, name: str) -> None:
                super().__init__(buttons=[ButtonConfig("OK")])
                self.name = name

            @property  # type: ignore[override]
            def title(self) -> str:
                return f"Edit {self.name}"

            @property  # type: ignore[override]
            def body(self) -> str:
                return f"Editing {self.name}"

        dialog = Edit("notes")
        dialog._prepare(MagicMock())
        assert (dialog.title, dialog.body) == ("Edit notes", "Editing notes")

    @pytest.mark.parametrize(
        "body", [5, 1.5, object(), ["a", "b"], [Label("x")]],
        ids=["int", "float", "object", "list of strs", "list of widgets"],
    )
    def test_a_body_that_isnt_text_or_a_container_is_refused(self, body):
        with pytest.raises(ValueError, match=r"^Dialog body must be text \(str, HTML, ANSI, FormattedText\) or a prompt_toolkit container, got "):
            Dialog("T", body, [ButtonConfig("OK")])

    @pytest.mark.parametrize("body", [
        [("", 5)],
        [(1, "x")],
        FormattedText([("fg:nope", "x")]),
        HTML('<style fg="nope">x</style>'),
        ANSI("tool output \x1b[38;2;300;0;0mred"),
    ], ids=["text not a str", "style not a str", "bad style", "HTML bad color", "ANSI color over 255"])
    def test_a_body_prompt_toolkit_cant_draw_is_refused(self, body):
        """Taken, it raised at every redraw: yes_no_dialog("Run?",
        ANSI(tool_output)) with a color over 255 locked the screen, as it
        did a response before."""
        with pytest.raises(ValueError, match=r"^Dialog body must be "):
            Dialog("T", body, [ButtonConfig("OK")])

    @pytest.mark.parametrize("body", [
        "", "text", HTML("<b>x</b>"), ANSI("x"), FormattedText([("", "x")]), [("", "x")],
        lambda: "x", None, Label("x"), HSplit([Window()]),
    ], ids=["empty", "str", "HTML", "ANSI", "FormattedText", "pairs", "callable", "None",
            "widget", "container"])
    def test_text_and_containers_are_bodies(self, body):
        Dialog("T", body, [ButtonConfig("OK")])

    def test_defaults_come_from_class_attributes(self):
        d = Dialog()
        assert (d.title, d.body) == ("", "")
        assert d.get_buttons() == []
        assert (d.escape_result, d.escapable) == (None, True)
        assert (d.width, d.max_height) == (None, None)

    def test_positional_title_body_buttons(self):
        buttons = [ButtonConfig("Yes", result=True)]
        d = Dialog("Delete?", "Sure?", buttons)
        assert (d.title, d.body) == ("Delete?", "Sure?")
        assert d.get_buttons() == buttons

    def test_constructor_overrides_only_passed_options(self):
        class Wide(Dialog):
            width = 70
            escape_result = "dismissed"

        d = Wide(title="T", max_height=2)
        assert (d.title, d.max_height) == ("T", 2)
        assert (d.width, d.escape_result) == (70, "dismissed")

    def test_explicit_none_overrides_a_class_default(self):
        class Wide(Dialog):
            width = 70
            max_height = 3
            escape_result = "dismissed"

        d = Wide(width=None, max_height=None, escape_result=None)
        assert (d.width, d.max_height, d.escape_result) == (None, None, None)

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

    def test_tuple_buttons_shown_inline_raise_with_migration_hint(self):
        class Old(Dialog):
            def get_buttons(self):
                return [("OK", lambda: None)]

        with pytest.raises(TypeError, match=r"Use ButtonConfig\(label, handler=\.\.\.\)"):
            build_inline(Old())

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
        last = session._display.transcript.iter_entries()[-1]
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
        last = session._display.transcript.iter_entries()[-1]
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
        with pytest.raises(ValueError, match="dialog_placement must be 'box' or 'inline', got 'side'"):
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


class TestDialogParts:
    """A dialog's fields, buttons and values= are checked when it's made,
    and again when it's shown (they can be set after): the wrong kind of
    object raises TypeError naming the part. It was Python's own TypeError,
    one at show, or nothing: values=[("k", 1)] was ignored, and a generator
    of fields showed an empty form."""

    @pytest.mark.parametrize("kwargs,message", [
        ({"fields": None}, r"^Dialog fields must be a sequence of fields, got None$"),
        ({"fields": TextField("a", "A")}, r"^Dialog fields must be a sequence of fields, got TextField\("),
        ({"fields": (f for f in [TextField("a", "A")])}, r"^Dialog fields must be a sequence of fields, got <generator"),
        ({"fields": [("a", "b")]}, r"^Dialog fields must be TextField, .*; got tuple$"),
        ({"buttons": None}, r"^Dialog buttons must be a sequence of ButtonConfig, got None$"),
        ({"buttons": ButtonConfig("OK")}, r"^Dialog buttons must be a sequence of ButtonConfig, got ButtonConfig\("),
        ({"buttons": [("OK", print)]}, r"^Dialog buttons must be ButtonConfig items; got tuple\. Use ButtonConfig"),
        ({"values": 5}, r"^Dialog values must be a mapping of field keys to values \(or None\), got 5$"),
        ({"values": "ab"}, r"^Dialog values must be a mapping of field keys to values \(or None\), got 'ab'$"),
        ({"values": [("a", "x")]}, r"^Dialog values must be a mapping .*, got \[\('a', 'x'\)\]$"),
    ], ids=["fields None", "one field", "fields generator", "fields of tuples", "buttons None",
            "one button", "tuple buttons", "values int", "values str", "values pairs"])
    def test_the_wrong_kind_of_part_raises_type_error(self, kwargs, message):
        with pytest.raises(TypeError, match=message):
            Dialog("T", **kwargs)

    @pytest.mark.parametrize("name,value,message", [
        ("fields", None, r"^Dialog fields must be a sequence of fields, got None$"),
        ("buttons", [("OK", print)], r"^Dialog buttons must be ButtonConfig items; got tuple"),
    ], ids=["fields", "buttons"])
    def test_a_part_set_later_is_checked_when_shown(self, name, value, message):
        dialog = Dialog("T", "B", [ButtonConfig("OK")])
        setattr(dialog, name, value)
        with pytest.raises(TypeError, match=message):
            dialog._prepare(MagicMock())

    def test_a_subclass_part_is_checked_when_shown(self):
        class Old(Dialog):
            buttons = [("OK", print)]

        with pytest.raises(TypeError, match=r"^Dialog buttons must be ButtonConfig items; got tuple"):
            Old()._prepare(MagicMock())

    async def test_a_list_of_parts_is_read_again_at_each_show(self):
        """Fields are read when the dialog is created and each time it's shown."""
        fields = [TextField("a", "A")]
        dialog = Dialog("T", fields=fields)
        fields.append(TextField("b", "B"))
        dialog._prepare(MagicMock())
        assert list(dialog.values) == ["a", "b"]


class TestMaxHeight:
    @pytest.mark.parametrize("rows", [0, -3])
    def test_must_be_at_least_one_row(self, rows):
        with pytest.raises(ValueError, match="max_height"):
            Dialog(max_height=rows)

    def test_must_be_an_int(self):
        with pytest.raises(ValueError, match=r"max_height must be an int \(or None\), got 2\.5"):
            Dialog(max_height=2.5)  # type: ignore[arg-type]

    def test_a_subclass_can_set_it(self):
        class Short(Dialog):
            max_height = 8

        assert Short().max_height == 8


class TestWidth:
    @pytest.mark.parametrize("width", [0, -1, "wide", 1.5, True])
    def test_is_columns_full_or_none(self, width):
        """None sizes the box to its content; there's no 0 or -1 for it."""
        with pytest.raises(ValueError, match=r'width must be at least 1, "full" or None, got '):
            Dialog(width=width)

    def test_a_subclass_value_is_checked_too(self):
        class Wide(Dialog):
            width = -1

        with pytest.raises(ValueError, match="width"):
            Wide()

    def test_the_inline_dropdown_builder_passes_it_on(self):
        assert _choice_dialog("T", "B", ["a"], placement="inline", max_height=9).max_height == 9


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
        lambda s, **kw: s.button_dialog("T", "B", ["a"], **kw),
        lambda s, **kw: s.choice_dialog("T", "B", ["a"], **kw),
        lambda s, **kw: s.checklist_dialog("T", "B", ["a"], **kw),
    ], ids=["yes_no", "message", "button", "choice", "checklist"])
    async def test_session_default_and_per_call_override(self, captured, call):
        session, shown = captured(dialog_placement="inline")
        await call(session)
        await call(session, placement="box")
        assert [d.placement for d in shown] == ["inline", "box"]

    @pytest.mark.parametrize("call", [
        lambda s, **kw: s.yes_no_dialog("T", "B", **kw),
        lambda s, **kw: s.message_dialog("T", "B", **kw),
        lambda s, **kw: s.button_dialog("T", "B", ["a"], **kw),
        lambda s, **kw: s.choice_dialog("T", "B", ["a"], **kw),
        lambda s, **kw: s.checklist_dialog("T", "B", ["a"], **kw),
    ], ids=["yes_no", "message", "button", "choice", "checklist"])
    async def test_max_height_passes_through(self, captured, call):
        session, shown = captured()
        await call(session, max_height=9)
        assert [d.max_height for d in shown] == [9]

    async def test_invalid_placement_raises(self, captured):
        session, shown = captured()
        with pytest.raises(ValueError, match="placement must be"):
            await session.yes_no_dialog("T", "B", placement="side")
        assert shown == []
