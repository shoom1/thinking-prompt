"""
The status bar: session.status_text, and the kinds of text it shows.
"""
from __future__ import annotations

import pytest

from prompt_toolkit.formatted_text import ANSI, FormattedText
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
