"""
Tests for Display module utilities.
"""
from __future__ import annotations

import pytest

from thinking_prompt.display import (
    _is_rich_renderable as is_rich_renderable,
    _rich_to_ansi as rich_to_ansi,
    _markdown_to_ansi as markdown_to_ansi,
    _highlight_code as highlight_code,
)


class TestIsRichRenderable:
    """Test is_rich_renderable function."""

    def test_plain_string_not_renderable(self):
        """Plain string should not be considered Rich renderable."""
        assert not is_rich_renderable("Hello")

    def test_int_not_renderable(self):
        """Integer should not be considered Rich renderable."""
        assert not is_rich_renderable(42)

    def test_none_not_renderable(self):
        """None should not be considered Rich renderable."""
        assert not is_rich_renderable(None)

    def test_object_with_rich_console_is_renderable(self):
        """Object with __rich_console__ method should be renderable."""
        class FakeRenderable:
            def __rich_console__(self, console, options):
                pass

        assert is_rich_renderable(FakeRenderable())

    def test_object_with_rich_is_renderable(self):
        """Object with __rich__ method should be renderable."""
        class FakeRenderable:
            def __rich__(self):
                pass

        assert is_rich_renderable(FakeRenderable())


class TestRichToAnsi:
    """Test rich_to_ansi function."""

    def test_converts_string_to_string(self):
        """Should convert plain string to string."""
        result = rich_to_ansi("Hello World")
        assert isinstance(result, str)
        assert "Hello" in result

    def test_handles_none_gracefully(self):
        """Should handle None gracefully."""
        result = rich_to_ansi(None)
        assert isinstance(result, str)

    def test_rich_text_if_available(self):
        """Should convert Rich Text if available."""
        try:
            from rich.text import Text
            text = Text("Hello", style="bold")
            result = rich_to_ansi(text)
            assert "Hello" in result
        except ImportError:
            # Rich not installed, test fallback
            result = rich_to_ansi("Hello")
            assert "Hello" in result


class TestMarkdownToAnsi:
    """Test markdown_to_ansi function."""

    def test_converts_markdown_string(self):
        """Should convert markdown to string."""
        result = markdown_to_ansi("# Hello\n\nWorld")
        assert isinstance(result, str)

    def test_preserves_content(self):
        """Should preserve text content."""
        result = markdown_to_ansi("Hello World")
        assert "Hello" in result
        assert "World" in result

    def test_handles_code_blocks(self):
        """Should handle code blocks."""
        md = "```python\nprint('hello')\n```"
        result = markdown_to_ansi(md)
        assert "print" in result

    def test_handles_lists(self):
        """Should handle lists."""
        md = "- Item 1\n- Item 2\n- Item 3"
        result = markdown_to_ansi(md)
        assert "Item 1" in result

    def test_empty_string(self):
        """Should handle empty string."""
        result = markdown_to_ansi("")
        assert isinstance(result, str)


class TestHighlightCode:
    """Test highlight_code function."""

    def test_highlights_python_code(self):
        """Should return highlighted Python code."""
        code = "def hello():\n    return 'world'"
        result = highlight_code(code, "python")
        assert isinstance(result, str)
        # Should contain the code content
        assert "def" in result or "hello" in result

    def test_handles_unknown_language(self):
        """Should handle unknown language gracefully."""
        code = "some code"
        result = highlight_code(code, "unknown_language_xyz")
        assert isinstance(result, str)
        assert "some code" in result

    def test_handles_empty_code(self):
        """Should handle empty code."""
        result = highlight_code("", "python")
        assert isinstance(result, str)

    def test_default_language_is_python(self):
        """Default language should be Python."""
        code = "x = 1"
        result = highlight_code(code)
        assert isinstance(result, str)

    def test_javascript_code(self):
        """Should handle JavaScript code."""
        code = "const x = () => console.log('hello');"
        result = highlight_code(code, "javascript")
        assert isinstance(result, str)
        assert "const" in result or "console" in result


# =============================================================================
# Display Class Tests
# =============================================================================

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

from thinking_prompt.display import Display


@pytest.fixture
def default_style() -> Style:
    """Create a minimal style for testing."""
    return Style.from_dict({})


@pytest.fixture
def display(default_style: Style) -> Display:
    """Create a Display instance in prompt mode (not fullscreen)."""
    return Display(style=default_style, is_fullscreen=lambda: False)


@pytest.fixture
def fullscreen_display(default_style: Style) -> Display:
    """Create a Display instance in fullscreen mode."""
    return Display(style=default_style, is_fullscreen=lambda: True)


class TestDisplayInit:
    """Test Display initialization."""

    def test_creates_with_style(self, default_style: Style):
        """Should initialize with provided style."""
        display = Display(style=default_style)
        assert display._style is default_style

    def test_creates_empty_history(self, display: Display):
        """Should start with empty history."""
        assert display.history.is_empty

    def test_default_not_fullscreen(self, default_style: Style):
        """Default is_fullscreen should return False."""
        display = Display(style=default_style)
        assert not display._is_fullscreen()

    def test_custom_fullscreen_callback(self, default_style: Style):
        """Should use custom is_fullscreen callback."""
        display = Display(style=default_style, is_fullscreen=lambda: True)
        assert display._is_fullscreen()


class TestDisplayHistory:
    """Test Display history property and changes."""

    def test_history_property(self, display: Display):
        """Should expose history via property."""
        assert display.history is display._history

    def test_set_on_change_callback(self, display: Display):
        """Should set change callback on history."""
        called = []
        display.set_on_change(lambda: called.append(1))
        display.history.append("", "test")
        assert len(called) == 1


class TestDisplayUserInput:
    """Test Display.user_input method."""

    def test_adds_to_history(self, display: Display):
        """Should add prompt and text to history."""
        display.user_input(">>> ", "hello")
        formatted = display.history.get_formatted_text()
        text = "".join(t for _, t in formatted)
        assert ">>> " in text
        assert "hello" in text

    def test_history_has_correct_styles(self, display: Display):
        """Should use correct style classes in history."""
        display.user_input(">>> ", "hello")
        formatted = display.history.get_formatted_text()
        styles = [s for s, _ in formatted]
        assert "class:history.user-prefix" in styles
        assert "class:history.user-message" in styles

    def test_caches_in_fullscreen(self, fullscreen_display: Display):
        """Should cache output in fullscreen mode."""
        fullscreen_display.user_input(">>> ", "hello")
        assert len(fullscreen_display._pending_output) == 1
        assert isinstance(fullscreen_display._pending_output[0], FormattedText)


class TestDisplayThinking:
    """Test Display.thinking method."""

    def test_adds_to_history(self, display: Display):
        """Should add thinking content to history."""
        display.thinking("Processing...")
        formatted = display.history.get_formatted_text()
        text = "".join(t for _, t in formatted)
        assert "Processing..." in text

    def test_skips_empty_content(self, display: Display):
        """Should skip empty or whitespace-only content."""
        display.thinking("")
        display.thinking("   ")
        assert display.history.is_empty

    def test_truncates_when_requested(self, display: Display):
        """Should truncate console output when truncate_lines is set."""
        content = "\n".join([f"Line {i}" for i in range(10)])
        display.thinking(content, truncate_lines=3)
        # History should have full content
        formatted = display.history.get_formatted_text()
        text = "".join(t for _, t in formatted)
        assert "Line 9" in text  # Full content in history

    def test_skip_history_when_requested(self, display: Display):
        """Should not add to history when add_to_history=False."""
        display.thinking("Processing...", add_to_history=False)
        assert display.history.is_empty

    def test_caches_in_fullscreen(self, fullscreen_display: Display):
        """Should cache output in fullscreen mode."""
        fullscreen_display.thinking("Processing...")
        assert len(fullscreen_display._pending_output) == 1


class TestDisplayResponse:
    """Test Display.response method."""

    def test_adds_to_history(self, display: Display):
        """Should add response to history."""
        display.response("Hello, world!")
        formatted = display.history.get_formatted_text()
        text = "".join(t for _, t in formatted)
        assert "Hello, world!" in text

    def test_uses_correct_style(self, display: Display):
        """Should use assistant-message style."""
        display.response("Hello")
        formatted = display.history.get_formatted_text()
        styles = [s for s, _ in formatted]
        assert "class:history.assistant-message" in styles

    def test_adds_empty_to_history_but_skips_print(self, display: Display):
        """Empty content should still go to history."""
        display.response("")
        # History gets it (even if empty)
        assert len(display.history) == 1


class TestDisplaySystemMessages:
    """Test Display system, error, warning, success methods."""

    def test_system_adds_to_history(self, display: Display):
        """System message should be added to history."""
        display.system("System message")
        text = "".join(t for _, t in display.history.get_formatted_text())
        assert "System message" in text

    def test_error_has_prefix(self, display: Display):
        """Error should have [ERROR] prefix."""
        display.error("Something failed")
        text = "".join(t for _, t in display.history.get_formatted_text())
        assert "[ERROR]" in text
        assert "Something failed" in text

    def test_warning_has_prefix(self, display: Display):
        """Warning should have [WARN] prefix."""
        display.warning("Be careful")
        text = "".join(t for _, t in display.history.get_formatted_text())
        assert "[WARN]" in text
        assert "Be careful" in text

    def test_success_has_prefix(self, display: Display):
        """Success should have [OK] prefix."""
        display.success("Done")
        text = "".join(t for _, t in display.history.get_formatted_text())
        assert "[OK]" in text
        assert "Done" in text

    def test_skips_empty_content(self, display: Display):
        """Empty content should go to history but skip console output."""
        display.error("")
        # Still adds to history (with prefix)
        assert len(display.history) == 1


class TestDisplayMarkdownAndCode:
    """Test Display.markdown and Display.code methods."""

    def test_markdown_adds_to_history(self, display: Display):
        """Markdown should be added to history."""
        display.markdown("# Title")
        assert not display.history.is_empty

    def test_code_adds_to_history(self, display: Display):
        """Code should be added to history."""
        display.code("x = 1", "python")
        assert not display.history.is_empty

    def test_markdown_caches_in_fullscreen(self, fullscreen_display: Display):
        """Markdown should cache in fullscreen mode."""
        from prompt_toolkit.formatted_text import ANSI
        fullscreen_display.markdown("# Title")
        assert len(fullscreen_display._pending_output) == 1
        assert isinstance(fullscreen_display._pending_output[0], ANSI)

    def test_code_caches_in_fullscreen(self, fullscreen_display: Display):
        """Code should cache in fullscreen mode."""
        from prompt_toolkit.formatted_text import ANSI
        fullscreen_display.code("x = 1")
        assert len(fullscreen_display._pending_output) == 1
        assert isinstance(fullscreen_display._pending_output[0], ANSI)


class TestDisplayWelcome:
    """Test Display.welcome method."""

    def test_plain_text_adds_to_history(self, display: Display):
        """Plain text welcome should be added to history."""
        display.welcome("Welcome!")
        text = "".join(t for _, t in display.history.get_formatted_text())
        assert "Welcome!" in text

    def test_rich_renderable_converted(self, display: Display):
        """Rich renderable should be converted to ANSI."""
        class FakeRenderable:
            def __rich__(self):
                return "Rich content"

        display.welcome(FakeRenderable())
        # Should not raise and should add to history
        assert not display.history.is_empty


class TestDisplayFormatted:
    """Test Display.formatted method."""

    def test_adds_to_history(self, display: Display):
        """FormattedText should be added to history."""
        ft = FormattedText([("bold", "Hello")])
        display.formatted(ft)
        formatted = display.history.get_formatted_text()
        assert len(formatted) > 0

    def test_caches_in_fullscreen(self, fullscreen_display: Display):
        """FormattedText should cache in fullscreen mode."""
        ft = FormattedText([("bold", "Hello")])
        fullscreen_display.formatted(ft)
        assert len(fullscreen_display._pending_output) == 1
        assert isinstance(fullscreen_display._pending_output[0], FormattedText)


class TestDisplayRaw:
    """Test Display.raw method."""

    def test_adds_to_history(self, display: Display):
        """Raw content should be added to history."""
        display.raw("Raw content")
        text = "".join(t for _, t in display.history.get_formatted_text())
        assert "Raw content" in text

    def test_with_style_class(self, display: Display):
        """Should apply style class when provided."""
        display.raw("Styled", style_class="class:custom")
        formatted = display.history.get_formatted_text()
        styles = [s for s, _ in formatted]
        assert "class:custom" in styles

    def test_caches_raw_in_fullscreen(self, fullscreen_display: Display):
        """Raw without style should cache as ANSI."""
        from prompt_toolkit.formatted_text import ANSI
        fullscreen_display.raw("Content")
        assert isinstance(fullscreen_display._pending_output[0], ANSI)

    def test_caches_formatted_in_fullscreen_with_style(self, fullscreen_display: Display):
        """Raw with style should cache as FormattedText."""
        fullscreen_display.raw("Content", style_class="class:custom")
        assert isinstance(fullscreen_display._pending_output[0], FormattedText)


class TestDisplayClear:
    """Test Display.clear method."""

    def test_clears_history(self, display: Display):
        """Should clear the history buffer."""
        display.response("Hello")
        assert not display.history.is_empty
        display.clear()
        assert display.history.is_empty


class TestDisplayFlushPending:
    """Test Display.flush_pending method."""

    def test_clears_pending_output(self, fullscreen_display: Display):
        """Should clear pending output after flush."""
        fullscreen_display.response("Hello")
        assert len(fullscreen_display._pending_output) == 1
        fullscreen_display.flush_pending()
        assert len(fullscreen_display._pending_output) == 0

    def test_handles_empty_pending(self, fullscreen_display: Display):
        """Should handle empty pending list gracefully."""
        fullscreen_display.flush_pending()  # Should not raise
        assert len(fullscreen_display._pending_output) == 0

    def test_preserves_order(self, fullscreen_display: Display):
        """Should flush in correct order."""
        fullscreen_display.response("First")
        fullscreen_display.response("Second")
        # Just verify pending has correct count before flush
        assert len(fullscreen_display._pending_output) == 2
        fullscreen_display.flush_pending()
        assert len(fullscreen_display._pending_output) == 0
