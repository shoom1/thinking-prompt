"""Session options: behavior is set on the session; AppInfo is the banner."""
from __future__ import annotations

import dataclasses

import pytest
from prompt_toolkit.keys import Keys

from tests.helpers import echoed, keep_console, transcript_texts
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

    def test_ctrl_t_expands(self):
        assert (Keys.ControlT,) in _bound_keys(ThinkingPromptSession())

    def test_ctrl_e_is_left_to_prompt_toolkit(self):
        assert (Keys.ControlE,) not in _bound_keys(ThinkingPromptSession())

    def test_boxes_are_titled_thinking_with_dots_before_the_title(self):
        header = _header(ThinkingPromptSession())
        assert header.text == "Thinking"
        assert header.spinner == Spinner.DOTS
        assert header.position == "before"


class TestOptions:
    """Each option takes effect on a session without an AppInfo."""

    def test_expand_key_rebinds_expand_and_its_hint(self):
        session = ThinkingPromptSession(expand_key="c-x")
        assert (Keys.ControlX,) in _bound_keys(session)
        assert (Keys.ControlT,) not in _bound_keys(session)
        assert session._manager._expand_key == "c-x"

    def test_thinking_border_is_the_default_of_a_boxs_border(self):
        session = ThinkingPromptSession(thinking_border=False)
        assert session.start_thinking()._header.border is False
        assert session.start_thinking(border=True)._header.border is True
        assert ThinkingPromptSession().start_thinking()._header.border is True

    def test_thinking_title_titles_boxes_that_set_none(self):
        session = ThinkingPromptSession(thinking_title="Pondering")
        assert _header(session).text == "Pondering"
        assert session.start_thinking(lambda: "y", title="Own")._header.text == "Own"

    @pytest.mark.parametrize("spinner", [None, Spinner(("a", "b"), 0.25)])
    def test_spinner_and_its_position_reach_every_header(self, spinner):
        header = _header(ThinkingPromptSession(spinner=spinner, spinner_position="after"))
        assert header.spinner is spinner
        assert header.position == "after"

    def test_thinking_echo_off_keeps_boxes_off_the_console(self):
        session = ThinkingPromptSession(thinking_echo=False)
        keep_console(session._display)
        box = session.start_thinking()
        box.append("x\n")
        box.finish()
        assert echoed(session._display) == []
        assert transcript_texts(session._display) == []  # nor kept for a repaint

    def test_options_after_message_are_keyword_only(self):
        with pytest.raises(TypeError):
            ThinkingPromptSession(">>> ", AppInfo(name="t"))  # type: ignore[misc]


class TestThinkingMaxLines:
    def test_below_zero_is_refused(self):
        with pytest.raises(ValueError, match="thinking_max_lines must be at least 0"):
            ThinkingPromptSession(thinking_max_lines=-1)

    def test_zero_makes_every_box_its_title_line(self):
        session = ThinkingPromptSession(thinking_max_lines=0)
        assert session.start_thinking()._control.max_collapsed_lines == 0

    def test_one_row_is_enough(self):
        session = ThinkingPromptSession(thinking_max_lines=1)
        assert session.start_thinking()._control.max_collapsed_lines == 1

    def test_new_boxes_collapse_to_it_unless_they_set_their_own(self):
        session = ThinkingPromptSession(thinking_max_lines=3)
        assert session.start_thinking()._control.max_collapsed_lines == 3
        assert session.start_thinking(max_lines=7)._control.max_collapsed_lines == 7


def _drawn(session: ThinkingPromptSession, width: int = 40, height: int = 10) -> list[str]:
    """The session's layout drawn on a ``width`` x ``height`` screen, one string per row."""
    from prompt_toolkit.application.current import set_app
    from prompt_toolkit.layout.mouse_handlers import MouseHandlers
    from prompt_toolkit.layout.screen import Screen, WritePosition

    screen = Screen()
    with set_app(session.app):
        session.app.layout.container.write_to_screen(
            screen, MouseHandlers(), WritePosition(0, 0, width, height), "", True, None
        )
    return [
        "".join(screen.data_buffer[y][x].char for x in range(width)) for y in range(height)
    ]


class TestStatusBar:
    """enable_status_bar draws the status bar under the prompt, or leaves it
    out. (Async: drawing the input buffer starts a history-loading task,
    which needs a running loop.)"""

    @pytest.mark.parametrize("enabled", [True, False])
    async def test_enable_status_bar_shows_or_leaves_out_the_status_bar(self, enabled):
        rows = _drawn(ThinkingPromptSession(enable_status_bar=enabled, status_text="STATUS"))
        assert any("STATUS" in row for row in rows) is enabled


def _banner(app_info: AppInfo | None) -> tuple[list[str], list[str]]:
    """What the session's banner put in the transcript and on the console."""
    session = ThinkingPromptSession(app_info=app_info)
    keep_console(session._display)
    session._print_welcome()
    return transcript_texts(session._display), echoed(session._display)


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

    @pytest.mark.parametrize(
        "message", ["Hello there", lambda: "Hello there"], ids=["string", "callable"]
    )
    def test_a_welcome_message_replaces_the_name_and_version(self, message):
        _, console = _banner(AppInfo(name="App", version="1.0", welcome_message=message))
        assert console == ["Hello there\n"]

    def test_a_welcome_message_can_be_a_rich_renderable(self):
        pytest.importorskip("rich")
        from rich.panel import Panel

        app_info = AppInfo(name="App", version="1.0", welcome_message=lambda: Panel("Hello there"))
        _, console = _banner(app_info)
        (banner,) = console
        # The panel's corner: ╭, or ┌ where Rich can't tell the console
        # handles it (Windows without a console).
        assert ("╭" in banner or "┌" in banner) and "Hello there" in banner
        assert "App v1.0" not in banner

    def test_without_a_version_the_banner_shows_the_name_alone(self):
        _, console = _banner(AppInfo(name="App"))
        (banner,) = console
        assert "App" in banner
        assert " v" not in banner

    def test_clear_prints_the_banner_again(self):
        session = ThinkingPromptSession(app_info=AppInfo(name="App", version="1.0"))
        keep_console(session._display)
        session._print_welcome()
        session.add_response("x")

        session.clear()

        banner = echoed(session._display)[0]
        assert "App v1.0" in banner
        assert echoed(session._display) == [banner, "x\n", banner]
        assert [entry.source for entry in session._display.transcript.iter_entries()] == [banner]
