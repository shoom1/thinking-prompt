"""
The status bar: session.status_text, and the kinds of text it shows.
"""
from __future__ import annotations

from typing import Any

import pytest

from prompt_toolkit.formatted_text import ANSI, HTML, FormattedText
from prompt_toolkit.styles import Style

from thinking_prompt.display import Display
from thinking_prompt.layout import create_status_bar


# =============================================================================
# Display.to_ansi() Tests
# =============================================================================


class TestDisplayToAnsi:
    """Test Display.to_ansi() public method."""

    @pytest.fixture
    def display(self) -> Display:
        style = Style.from_dict({})
        return Display(get_style=lambda: style)

    def test_strips_trailing_newlines(self, display: Display):
        """Should strip trailing newlines from output."""
        pytest.importorskip("rich")
        from rich.text import Text
        result = display.to_ansi(Text("Hello"))
        # ANSI stores the raw value; check it doesn't end with newline
        assert isinstance(result, ANSI)
        assert not result.value.endswith("\n")

    def test_plain_string_works(self, display: Display):
        """Should handle plain strings (Rich prints them)."""
        result = display.to_ansi("hello")
        assert isinstance(result, ANSI)
        assert "hello" in result.value


# =============================================================================
# Layout _resolve_status_text Tests
# =============================================================================


class TestCreateStatusBarTypeDispatch:
    """Test that create_status_bar dispatches correctly on text type."""

    def test_string_wrapped_with_status_class(self):
        """str should be wrapped as FormattedText with class:status style."""
        from prompt_toolkit.layout.controls import FormattedTextControl

        bar = create_status_bar(
            get_status_text=lambda: "Hello",
            is_enabled=lambda: True,
        )
        # The bar is ConditionalContainer → Window → FormattedTextControl
        window = bar.content
        control = window.content
        assert isinstance(control, FormattedTextControl)
        # Call the text callable to get the formatted text
        result = control.text()
        assert result == FormattedText([("class:status", "Hello")])

    def test_formatted_text_passed_through(self):
        """FormattedText should be returned as-is."""

        ft = FormattedText([("bold", "Styled")])
        bar = create_status_bar(
            get_status_text=lambda: ft,
            is_enabled=lambda: True,
        )
        window = bar.content
        control = window.content
        result = control.text()
        assert result is ft

    def test_ansi_passed_through(self):
        """ANSI objects should be returned as-is."""

        ansi = ANSI("\x1b[1mBold\x1b[0m")
        bar = create_status_bar(
            get_status_text=lambda: ansi,
            is_enabled=lambda: True,
        )
        window = bar.content
        control = window.content
        result = control.text()
        assert result is ansi


# =============================================================================
# ThinkingPromptSession.status_text Tests
# =============================================================================


class TestSessionStatusText:
    """The status_text property on ThinkingPromptSession."""

    @pytest.fixture
    def session(self):
        from thinking_prompt import ThinkingPromptSession
        return ThinkingPromptSession(
            message=">>> ",
            enable_status_bar=True,
            status_text="initial",
        )

    def test_status_text_getter(self, session):
        """status_text property should return initial value."""
        assert session.status_text == "initial"

    def test_status_text_setter_plain_string(self, session):
        """Setting status_text with a string should update the value."""
        session.status_text = "updated"
        assert session.status_text == "updated"

    def test_status_text_setter_formatted_text(self, session):
        """Setting status_text with FormattedText should work."""
        ft = FormattedText([("bold", "Styled")])
        session.status_text = ft
        assert session.status_text is ft

    def test_status_text_setter_rich_renderable(self, session):
        """A Rich renderable is shown as ANSI, and read back as itself."""
        pytest.importorskip("rich")
        from rich.text import Text
        text = Text("Rich status", style="bold")
        session.status_text = text
        assert session.status_text is text
        shown = session._status_now()
        assert isinstance(shown, ANSI)
        assert "Rich status" in shown.value

    def test_a_rich_renderable_passed_to_the_session(self):
        """It was drawn as is: every redraw raised."""
        pytest.importorskip("rich")
        from rich.text import Text

        from thinking_prompt import ThinkingPromptSession

        text = Text("Rich status")
        session = ThinkingPromptSession(status_text=text)
        assert session.status_text is text
        shown = session._status_now()
        assert isinstance(shown, ANSI)
        assert "Rich status" in shown.value

    def test_a_hint_is_shown_but_not_read(self, session):
        """While the session's hint shows, status_text is still the app's."""
        session._show_hint(session._BUSY_STATUS)
        assert session._status_now() == session._BUSY_STATUS
        assert session.status_text == "initial"
        session._clear_hint()
        assert session._status_now() == "initial"

    def test_adding_to_the_status_under_a_hint_keeps_the_apps_text(self, session):
        """status_text += ... while Busy showed kept the hint for good."""
        session._show_hint(session._BUSY_STATUS)
        session.status_text += " | 2 jobs"
        assert session.status_text == "initial | 2 jobs"
        assert session._status_now() == "initial | 2 jobs"  # the app's text replaces the hint
        session._clear_hint()
        assert session._status_now() == "initial | 2 jobs"


# =============================================================================
# Text the session draws: checked when set, a callable's result when drawn
# =============================================================================

_NOT_TEXT = [2, object(), [("bold", 1)], HTML('<style fg="nope">x</style>'), ANSI("\x1b[38;2;300;0;0mX")]
_NOT_TEXT_IDS = ["int", "object", "text not a str", "HTML bad color", "ANSI color over 255"]


class TestStatusAndPromptChecked:
    """status_text = 2 (a job count) or message = 7, taken, raised at every
    redraw: prompt_toolkit's "Press ENTER" screen came back after each key,
    and none got out."""

    @pytest.mark.parametrize("name", ["status_text", "message"])
    @pytest.mark.parametrize("value", _NOT_TEXT, ids=_NOT_TEXT_IDS)
    def test_set_on_the_session_it_is_refused(self, name, value):
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession(**{name: "kept"})
        with pytest.raises(ValueError, match=rf"^{name} must be "):
            setattr(session, name, value)
        assert getattr(session, name) == "kept"

    @pytest.mark.parametrize("name", ["status_text", "message"])
    @pytest.mark.parametrize("value", _NOT_TEXT, ids=_NOT_TEXT_IDS)
    def test_passed_to_the_session_it_is_refused(self, name, value):
        from thinking_prompt import ThinkingPromptSession

        with pytest.raises(ValueError, match=rf"^{name} must be "):
            ThinkingPromptSession(**{name: value})

    @pytest.mark.parametrize("name", ["status_text", "message"])
    @pytest.mark.parametrize(
        "value",
        ["text", HTML("<b>x</b>"), ANSI("\x1b[1mx"), FormattedText([("bold", "x")]), [("bold", "x")], lambda: "x", None],
        ids=["str", "HTML", "ANSI", "FormattedText", "pairs", "callable", "None"],
    )
    def test_text_of_every_kind_is_taken(self, name, value):
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        setattr(session, name, value)
        assert getattr(session, name) is value
        ThinkingPromptSession(**{name: value})

    def test_the_prompt_takes_no_rich_renderable(self):
        pytest.importorskip("rich")
        from rich.text import Text

        from thinking_prompt import ThinkingPromptSession

        with pytest.raises(ValueError, match=r"^message must be "):
            ThinkingPromptSession(message=Text("> "))


class TestCallablesThatDontReturnText:
    """A callable can't be checked when it's set: what it returns is, when
    it's drawn. One that returns something that isn't text draws nothing,
    as one that raises does, and is logged once."""

    async def test_the_app_keeps_drawing(self, caplog):
        import asyncio
        import logging

        from tests.test_end_to_end import piped_session, run_with, screen_lines, wait_until

        state = {"n": 0}
        with piped_session(rows=12) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                with caplog.at_level(logging.ERROR, logger="thinking_prompt"):
                    session.status_text = lambda: state["n"]
                    session.message = lambda: state["n"]
                    box = session.start_thinking(lambda: state["n"], title="Progress")
                    for n in range(3):
                        state["n"] = n
                        await asyncio.sleep(0.15)
                    assert box.finish() == ""
                    session.status_text = "Ready"
                    await wait_until(lambda: "Ready" in screen_lines(session))
                assert run.done() is False
                errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
                # One line per callable: the status, the prompt and the box.
                assert len(errors) == 3, [r.getMessage() for r in errors]

            await run_with(session, lambda text: None, script)


def _three_jobs_kinds() -> list[Any]:
    from prompt_toolkit.formatted_text import Template, merge_formatted_text

    return [
        (("bold", "3 jobs"), ("", " | idle")),
        lambda: merge_formatted_text([HTML("<b>3 jobs</b>"), " | idle"]),
        lambda: Template("{} | idle").format(HTML("<b>3 jobs</b>")),
        lambda: lambda: "3 jobs | idle",
    ]


_THREE_JOBS_IDS = ["tuple of pairs", "merge_formatted_text", "Template", "callable returning a callable"]


class TestTextOfEveryKindIsDrawn:
    """A tuple of pairs passed the check and then raised at every redraw;
    a callable returning a callable (merge_formatted_text(),
    Template.format()), which prompt_toolkit calls again, drew nothing."""

    @pytest.mark.parametrize("name", ["status_text", "message"])
    @pytest.mark.parametrize("index", range(4), ids=_THREE_JOBS_IDS)
    async def test_it_is_drawn(self, name, index):
        import asyncio

        from tests.test_end_to_end import piped_session, run_with, screen_lines, wait_until

        value = _three_jobs_kinds()[index]
        with piped_session(rows=12) as (session, inp):

            async def script(run: asyncio.Task[None]) -> None:
                setattr(session, name, value)
                await wait_until(lambda: any("3 jobs | idle" in line for line in screen_lines(session)))
                assert run.done() is False

            await run_with(session, lambda text: None, script)
