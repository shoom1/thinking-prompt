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
        """A Rich renderable is converted to ANSI."""
        pytest.importorskip("rich")
        from rich.text import Text
        session.status_text = Text("Rich status", style="bold")
        assert isinstance(session.status_text, ANSI)
        assert "Rich status" in session.status_text.value
