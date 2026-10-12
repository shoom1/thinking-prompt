"""Session options: behavior is set on the session; AppInfo is the banner."""
from __future__ import annotations

import dataclasses

import pytest
from prompt_toolkit.keys import Keys

from tests.helpers import echoed, history_texts
from thinking_prompt import AppInfo, Spinner, ThinkingPromptSession


def _bound_keys(session: ThinkingPromptSession) -> set[tuple[str, ...]]:
    return {binding.keys for binding in session.app.key_bindings.bindings}


def _header(session: ThinkingPromptSession):
    session.start_thinking(lambda: "x")
    (box,) = session._manager.get_sorted_boxes()
    return box._header


class TestAppInfo:
    def test_holds_only_the_banner(self):
        names = [field.name for field in dataclasses.fields(AppInfo)]
        assert names == ["name", "version", "welcome_message"]


class TestDefaults:
    """A session with no AppInfo."""

    def test_full_screen_is_off(self):
        session = ThinkingPromptSession()
        session.switch_to_fullscreen()
        assert not session.is_fullscreen
        assert (Keys.ControlE,) not in _bound_keys(session)

    def test_ctrl_t_expands(self):
        assert (Keys.ControlT,) in _bound_keys(ThinkingPromptSession())

    def test_boxes_are_titled_thinking_with_dots_before_the_title(self):
        header = _header(ThinkingPromptSession())
        assert header.text == "Thinking"
        assert header.spinner == Spinner.DOTS
        assert header.position == "before"


class TestOptions:
    """Each option takes effect on a session without an AppInfo."""

    def test_enable_fullscreen_turns_on_ctrl_e(self):
        session = ThinkingPromptSession(enable_fullscreen=True)
        assert (Keys.ControlE,) in _bound_keys(session)
        session.switch_to_fullscreen()
        assert session.is_fullscreen

    def test_fullscreen_key_rebinds_the_toggle(self):
        session = ThinkingPromptSession(enable_fullscreen=True, fullscreen_key="c-f")
        assert (Keys.ControlF,) in _bound_keys(session)
        assert (Keys.ControlE,) not in _bound_keys(session)

    def test_expand_key_rebinds_expand_and_its_hint(self):
        session = ThinkingPromptSession(expand_key="c-x")
        assert (Keys.ControlX,) in _bound_keys(session)
        assert (Keys.ControlT,) not in _bound_keys(session)
        assert session._manager._expand_key == "c-x"

    def test_thinking_title_titles_boxes_that_set_none(self):
        session = ThinkingPromptSession(thinking_title="Pondering")
        assert _header(session).text == "Pondering"
        assert session.start_thinking(lambda: "y", title="Own")._header.text == "Own"

    @pytest.mark.parametrize("spinner", [None, Spinner(("a", "b"), 0.25)])
    def test_spinner_and_its_position_reach_every_header(self, spinner):
        header = _header(ThinkingPromptSession(spinner=spinner, spinner_position="after"))
        assert header.spinner is spinner
        assert header.position == "after"

    def test_echo_thinking_off_keeps_boxes_off_the_console(self):
        session = ThinkingPromptSession(echo_thinking=False)
        session._is_fullscreen = True  # the Display caches console output in full screen
        box = session.start_thinking()
        box.append("x\n")
        box.finish()
        assert session._display._pending_output == []
        assert history_texts(session._display) == ["x\n\n"]

    def test_options_after_message_are_keyword_only(self):
        with pytest.raises(TypeError):
            ThinkingPromptSession(">>> ", AppInfo(name="t"))  # type: ignore[misc]


def _banner(app_info: AppInfo | None) -> tuple[list[str], list[str]]:
    """What the session's banner put in history and on the console."""
    session = ThinkingPromptSession(app_info=app_info)
    session._is_fullscreen = True  # the Display caches console output in full screen
    session._print_welcome()
    return history_texts(session._display), echoed(session._display)


class TestBanner:
    def test_no_app_info_prints_no_banner(self):
        assert _banner(None) == ([], [])

    def test_app_info_prints_its_name_and_version(self):
        _, console = _banner(AppInfo(name="App", version="1.0"))
        (banner,) = console
        assert "App v1.0" in banner

    @pytest.mark.parametrize("message", ["", lambda: "", lambda: None])
    def test_an_empty_welcome_message_prints_nothing(self, message):
        assert _banner(AppInfo(name="t", welcome_message=message)) == ([], [])
