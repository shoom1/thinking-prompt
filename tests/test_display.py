"""
Tests for Display module utilities.
"""
from __future__ import annotations

import pytest

from thinking_prompt.rich_utils import (
    _highlight_code,
    _is_rich_renderable,
    _markdown_to_ansi,
    _renderable_to_ansi,
    _rich_to_ansi,
)
from tests.helpers import echoed, keep_console, make_display


class TestIsRichRenderable:
    """Test _is_rich_renderable function."""

    def test_plain_string_not_renderable(self):
        """Plain string should not be considered Rich renderable."""
        assert not _is_rich_renderable("Hello")

    def test_int_not_renderable(self):
        """Integer should not be considered Rich renderable."""
        assert not _is_rich_renderable(42)

    def test_none_not_renderable(self):
        """None should not be considered Rich renderable."""
        assert not _is_rich_renderable(None)

    def test_object_with_rich_console_is_renderable(self):
        """Object with __rich_console__ method should be renderable."""
        class FakeRenderable:
            def __rich_console__(self, console, options):
                pass

        assert _is_rich_renderable(FakeRenderable())

    def test_object_with_rich_is_renderable(self):
        """Object with __rich__ method should be renderable."""
        class FakeRenderable:
            def __rich__(self):
                pass

        assert _is_rich_renderable(FakeRenderable())


class TestPrivateRichToAnsi:
    """Test _rich_to_ansi, the converter Display.rich() uses (the public
    rich_to_ansi is _renderable_to_ansi, tested in TestRenderableToAnsi)."""

    def test_converts_string_to_string(self):
        """Should convert plain string to string."""
        result = _rich_to_ansi("Hello World")
        assert isinstance(result, str)
        assert "Hello" in result

    def test_handles_none_gracefully(self):
        """Should handle None gracefully."""
        result = _rich_to_ansi(None)
        assert isinstance(result, str)

    def test_rich_text_if_available(self):
        """Should convert Rich Text if available."""
        try:
            from rich.text import Text
            text = Text("Hello", style="bold")
            result = _rich_to_ansi(text)
            assert "Hello" in result
        except ImportError:
            # Rich not installed, test fallback
            result = _rich_to_ansi("Hello")
            assert "Hello" in result


class TestMarkdownToAnsi:
    """Test _markdown_to_ansi function."""

    def test_converts_markdown_string(self):
        """Should convert markdown to string."""
        result = _markdown_to_ansi("# Hello\n\nWorld")
        assert isinstance(result, str)

    def test_preserves_content(self):
        """Should preserve text content."""
        result = _markdown_to_ansi("Hello World")
        assert "Hello" in result
        assert "World" in result

    def test_handles_code_blocks(self):
        """Should handle code blocks."""
        md = "```python\nprint('hello')\n```"
        result = _markdown_to_ansi(md)
        assert "print" in result

    def test_handles_lists(self):
        """Should handle lists."""
        md = "- Item 1\n- Item 2\n- Item 3"
        result = _markdown_to_ansi(md)
        assert "Item 1" in result

    def test_empty_string(self):
        """Should handle empty string."""
        result = _markdown_to_ansi("")
        assert isinstance(result, str)

    def test_does_not_patch_rich_markdown_globally(self):
        """Importing thinking_prompt must not mutate Rich's own Markdown.

        Regression: an import-time hook replaced
        Markdown.elements['heading_open'] process-wide, changing heading
        rendering for the host application's own Rich usage."""
        rich_md = pytest.importorskip("rich.markdown")
        # Force our markdown path (which uses the scoped subclass) first.
        _markdown_to_ansi("# Heading\n\nbody")
        assert rich_md.Markdown.elements["heading_open"] is rich_md.Heading

    def test_h1_left_aligned_with_underline(self):
        """Our own markdown rendering keeps the custom heading style:
        H1 is left-aligned (not centered) and underlined with ─."""
        pytest.importorskip("rich")
        import re

        result = _markdown_to_ansi("# Hi\n\nbody")
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result)
        lines = [line for line in plain.splitlines() if line.strip()]
        # Left-aligned: no centering padding before the heading text.
        assert lines[0].startswith("Hi")
        assert "──" in plain  # H1 underline

    @pytest.mark.parametrize("level", [2, 3, 4, 5, 6])
    def test_h2_to_h6_show_their_text_left_aligned(self, level):
        pytest.importorskip("rich")
        import re

        result = _markdown_to_ansi("#" * level + " Sub\n\ntext")
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result)
        lines = [line for line in plain.splitlines() if line.strip()]
        assert lines[0].startswith("Sub")
        assert "#" not in plain


class TestHighlightCode:
    """Test _highlight_code function."""

    def test_highlights_python_code(self):
        """Should return highlighted Python code."""
        code = "def hello():\n    return 'world'"
        result = _highlight_code(code, "python")
        assert isinstance(result, str)
        # Should contain the code content
        assert "def" in result or "hello" in result

    def test_handles_unknown_language(self):
        """Should handle unknown language gracefully."""
        code = "some code"
        result = _highlight_code(code, "unknown_language_xyz")
        assert isinstance(result, str)
        assert "some code" in result

    def test_handles_empty_code(self):
        """Should handle empty code."""
        result = _highlight_code("", "python")
        assert isinstance(result, str)

    def test_default_language_is_python(self):
        """Default language should be Python."""
        pytest.importorskip("pygments")
        code = "x = 1"
        result = _highlight_code(code)
        assert result == _highlight_code(code, "python")
        assert result != _highlight_code(code, "text")

    def test_javascript_code(self):
        """Should handle JavaScript code."""
        code = "const x = () => console.log('hello');"
        result = _highlight_code(code, "javascript")
        assert isinstance(result, str)
        assert "const" in result or "console" in result

    def test_code_theme_selects_pygments_style(self):
        pytest.importorskip("pygments")
        code = "def hello():\n    return 'world'"
        assert _highlight_code(code, "python", code_theme="monokai") != _highlight_code(
            code, "python", code_theme="default"
        )

    def test_ansi_code_themes_use_terminal_palette(self):
        """ansi_dark/ansi_light (as in Rich) emit only the 16 named ANSI
        colors, so the terminal's own palette applies."""
        pytest.importorskip("pygments")
        code = "def hello():\n    return 'world'"
        dark = _highlight_code(code, "python", code_theme="ansi_dark")
        light = _highlight_code(code, "python", code_theme="ansi_light")
        assert dark != light
        for out in (dark, light):
            assert "\x1b[" in out
            assert "38;2;" not in out and "38;5;" not in out

    def test_unknown_code_theme_still_highlights(self):
        pytest.importorskip("pygments")
        result = _highlight_code("x = 1", "python", code_theme="no-such-style")
        assert "\x1b[" in result
        assert "x" in result


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
    """Create a Display instance."""
    return Display(get_style=lambda: default_style)


@pytest.fixture
def kept_display(default_style: Style) -> Display:
    """A Display that keeps what it prints in ``kept`` instead of printing it."""
    return keep_console(Display(get_style=lambda: default_style))


class TestDisplayInit:
    """Test Display initialization."""

    def test_creates_with_style(self, default_style: Style):
        """Should initialize with provided style."""
        display = Display(get_style=lambda: default_style)
        assert display._get_style() is default_style

    def test_creates_empty_history(self, display: Display):
        """Should start with empty history."""
        assert display.history.is_empty


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

    def test_prints_formatted_text(self, kept_display: Display):
        kept_display.user_input(">>> ", "hello")
        assert len(kept_display.kept) == 1
        assert isinstance(kept_display.kept[0], FormattedText)


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

    def test_truncates_when_requested(self, kept_display: Display):
        """Should truncate console output when truncate_lines is set."""
        content = "\n".join([f"Line {i}" for i in range(10)])
        kept_display.thinking(content, truncate_lines=3)
        assert echoed(kept_display) == ["Line 0\nLine 1\nLine 2\n...\n"]
        # History should have full content
        formatted = kept_display.history.get_formatted_text()
        text = "".join(t for _, t in formatted)
        assert "Line 9" in text  # Full content in history

    def test_skip_history_when_requested(self, display: Display):
        """Should not add to history when add_to_history=False."""
        display.thinking("Processing...", add_to_history=False)
        assert display.history.is_empty

    def test_prints_once(self, kept_display: Display):
        kept_display.thinking("Processing...")
        assert len(kept_display.kept) == 1


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

    def test_empty_content_is_added_and_printed(self, kept_display: Display):
        """Empty content still goes to history and to the console."""
        kept_display.response("")
        assert len(kept_display.history) == 1
        assert echoed(kept_display) == ["\n"]


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

    def test_empty_content_is_added_and_printed_with_its_prefix(self, kept_display: Display):
        """Empty content still goes to history and to the console, prefixed."""
        kept_display.error("")
        assert len(kept_display.history) == 1
        assert echoed(kept_display) == ["[ERROR] \n"]


class TestDisplayMarkdownAndCode:
    """Test Display.markdown and Display.code methods."""

    def test_markdown_prints_ansi(self, kept_display: Display):
        from prompt_toolkit.formatted_text import ANSI
        kept_display.markdown("# Title")
        assert len(kept_display.kept) == 1
        assert isinstance(kept_display.kept[0], ANSI)

    def test_code_prints_ansi(self, kept_display: Display):
        from prompt_toolkit.formatted_text import ANSI
        kept_display.code("x = 1")
        assert len(kept_display.kept) == 1
        assert isinstance(kept_display.kept[0], ANSI)


class TestDisplayWelcome:
    """Test Display.welcome method."""

    def test_plain_text_adds_to_history(self, display: Display):
        """Plain text welcome should be added to history."""
        display.welcome("Welcome!")
        text = "".join(t for _, t in display.history.get_formatted_text())
        assert "Welcome!" in text

    def test_rich_renderable_converted(self, kept_display: Display):
        """Rich renderable should be converted to ANSI."""
        pytest.importorskip("rich")

        class FakeRenderable:
            def __rich__(self):
                return "Rich content"

        kept_display.welcome(FakeRenderable())
        text = "".join(t for _, t in kept_display.history.get_formatted_text())
        assert text == "Rich content\n"
        assert echoed(kept_display) == ["Rich content\n"]

    @pytest.mark.parametrize("content", ["", None])
    def test_empty_content_prints_nothing(self, content):
        display = make_display()
        display.welcome(content)
        assert display.history.is_empty
        assert echoed(display) == []


class TestDisplayFormatted:
    """Test Display.formatted method."""

    def test_adds_to_history(self, display: Display):
        """FormattedText should be added to history."""
        ft = FormattedText([("bold", "Hello")])
        display.formatted(ft)
        formatted = display.history.get_formatted_text()
        assert len(formatted) > 0

    def test_prints_formatted_text(self, kept_display: Display):
        ft = FormattedText([("bold", "Hello")])
        kept_display.formatted(ft)
        assert len(kept_display.kept) == 1
        assert isinstance(kept_display.kept[0], FormattedText)


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

    def test_raw_prints_ansi(self, kept_display: Display):
        """Raw without style prints as ANSI."""
        from prompt_toolkit.formatted_text import ANSI
        kept_display.raw("Content")
        assert isinstance(kept_display.kept[0], ANSI)

    def test_raw_with_style_prints_formatted_text(self, kept_display: Display):
        """Raw with style prints as FormattedText."""
        kept_display.raw("Content", style_class="class:custom")
        assert isinstance(kept_display.kept[0], FormattedText)


class TestDisplayClear:
    """Test Display.clear method."""

    def test_clears_history(self, display: Display):
        """Should clear the history buffer."""
        display.response("Hello")
        assert not display.history.is_empty
        display.clear()
        assert display.history.is_empty


# =============================================================================
# Display ANSI Thinking Tests
# =============================================================================


class TestDisplayThinkingAnsi:
    """Test Display.thinking() with ANSI format."""

    def test_ansi_adds_to_history(self, display: Display):
        """ANSI thinking content should be added to history as fragments."""
        content = "\033[32m✓ Done\033[0m"
        display.thinking(content, content_format="ansi")
        formatted = display.history.get_formatted_text()
        assert len(formatted) > 0
        text = "".join(t for _, t in formatted)
        assert "✓ Done" in text

    def test_ansi_history_has_no_thinking_style(self, display: Display):
        """ANSI content in history should NOT use class:history.thinking style."""
        content = "\033[32m✓ Done\033[0m"
        display.thinking(content, content_format="ansi")
        formatted = display.history.get_formatted_text()
        styles = [s for s, _ in formatted]
        # Should not use the plain thinking style
        assert "class:history.thinking" not in styles

    def test_ansi_skips_empty_content(self, display: Display):
        """ANSI thinking should skip empty content."""
        display.thinking("", content_format="ansi")
        display.thinking("   ", content_format="ansi")
        assert display.history.is_empty

    def test_ansi_skip_history_when_requested(self, display: Display):
        """ANSI thinking should not add to history when add_to_history=False."""
        display.thinking("\033[32mtext\033[0m", add_to_history=False, content_format="ansi")
        assert display.history.is_empty

    def test_ansi_truncates_when_requested(self, kept_display: Display):
        """ANSI thinking should truncate console output when truncate_lines is set."""
        lines = [f"\033[32mLine {i}\033[0m" for i in range(10)]
        content = "\n".join(lines)
        kept_display.thinking(content, truncate_lines=3, content_format="ansi")
        assert echoed(kept_display) == ["Line 0\nLine 1\nLine 2\n...\n"]
        # History should have full content
        formatted = kept_display.history.get_formatted_text()
        text = "".join(t for _, t in formatted)
        assert "Line 9" in text

    def test_ansi_prints_ansi(self, kept_display: Display):
        from prompt_toolkit.formatted_text import ANSI
        kept_display.thinking("\033[32mtext\033[0m", content_format="ansi")
        assert len(kept_display.kept) == 1
        assert isinstance(kept_display.kept[0], ANSI)

    def test_plain_format_unchanged(self, display: Display):
        """Plain format should work the same as before."""
        display.thinking("Processing...", content_format="plain")
        formatted = display.history.get_formatted_text()
        styles = [s for s, _ in formatted]
        assert "class:history.thinking" in styles


class TestRenderableToAnsi:
    """Test _renderable_to_ansi function."""

    def test_converts_markup_string(self):
        pytest.importorskip("rich")
        result = _renderable_to_ansi("[green]hello[/green]")
        assert "hello" in result
        assert "\033[" in result

    def test_converts_rich_text_object(self):
        pytest.importorskip("rich")
        from rich.text import Text
        result = _renderable_to_ansi(Text("hello", style="bold"))
        assert "hello" in result

    def test_no_trailing_whitespace(self):
        result = _renderable_to_ansi("[green]hello[/green]")
        assert not result.endswith(" ")
        assert not result.endswith("\n")

    def test_plain_string(self):
        result = _renderable_to_ansi("plain text")
        assert "plain text" in result

    def test_produces_ansi_under_no_color(self, monkeypatch):
        """The ANSI converter must ignore NO_COLOR.

        NO_COLOR is honored at terminal-output layers, not at this converter.
        Since the function's contract is "produce ANSI", silently stripping
        styling under NO_COLOR breaks public APIs (rich_to_ansi, append_rich,
        set_line_rich) that promise styled output.
        """
        pytest.importorskip("rich")
        monkeypatch.setenv("NO_COLOR", "1")
        result = _renderable_to_ansi("[green]hello[/green]")
        assert "hello" in result
        assert "\033[" in result, (
            f"Expected ANSI escape under NO_COLOR=1, got plain output: {result!r}"
        )


class TestTranscriptWiring:
    def _display(self):
        from thinking_prompt.display import Display
        from thinking_prompt.styles import DEFAULT_STYLES
        style = DEFAULT_STYLES.to_style()
        return Display(get_style=lambda: style, thinking_styles=DEFAULT_STYLES)

    def test_markdown_stored_as_source(self, capsys):
        pytest.importorskip("rich")
        # print_formatted_text() writes through the process-wide
        # AppSession's Output, which lazily binds sys.stdout the first
        # time *any* test triggers it and then caches that binding for
        # the rest of the run (create_app_session() with no explicit
        # output= even inherits the parent session's cached output).
        # Building the Output here, with capsys already patching
        # sys.stdout, and passing it explicitly is what actually forces
        # a fresh binding — so this assertion doesn't depend on
        # suite/test ordering.
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.output.defaults import create_output
        d = self._display()
        with create_app_session(output=create_output()):
            d.markdown("# Hello")
        entries = d.history.iter_entries()
        assert entries[-1].kind == "markdown"
        assert entries[-1].source == "# Hello"
        assert "Hello" in capsys.readouterr().out

    def test_code_stored_as_source(self, capsys):
        d = self._display()
        d.code("x = 1", "python")
        entries = d.history.iter_entries()
        assert entries[-1].kind == "code"
        assert entries[-1].language == "python"

    def test_rich_stored_as_baked_ansi(self, capsys):
        pytest.importorskip("rich")
        from rich.text import Text
        d = self._display()
        d.rich(Text("boxed"))
        assert d.history.iter_entries()[-1].kind == "ansi"

    def test_set_theme_invalidates_markdown_cache_and_code_theme(self, monkeypatch):
        pytest.importorskip("rich")
        from thinking_prompt.styles import ThinkingPromptStyles
        # The themes differ only in color, which rich leaves out under NO_COLOR.
        monkeypatch.delenv("NO_COLOR", raising=False)
        d = self._display()
        d.markdown("```python\nx = 1\n```")
        before = list(d.history.get_formatted_text())
        d.set_theme(ThinkingPromptStyles.light())
        after = list(d.history.get_formatted_text())
        assert before != after  # monokai vs default code theme

    def test_set_theme_rerenders_add_code_in_new_theme(self):
        pytest.importorskip("pygments")
        from thinking_prompt.styles import ThinkingPromptStyles
        d = self._display()
        d.code("def hello():\n    return 'world'", "python")
        before = list(d.history.get_formatted_text())
        d.set_theme(ThinkingPromptStyles.light())
        after = list(d.history.get_formatted_text())
        assert before != after

    def test_add_code_console_echo_follows_theme(self):
        pytest.importorskip("pygments")
        from thinking_prompt.styles import ThinkingPromptStyles

        def echoed(styles: ThinkingPromptStyles) -> str:
            style = styles.to_style()
            d = keep_console(Display(get_style=lambda: style, thinking_styles=styles))
            d.code("def hello():\n    return 'world'", "python")
            return d.kept[0].value

        assert echoed(ThinkingPromptStyles.dark()) != echoed(ThinkingPromptStyles.light())

    def test_thinking_truncate_lines_recorded(self):
        d = self._display()
        d.thinking("l1\nl2\nl3", truncate_lines=2, echo_to_console=False)
        assert d.history.iter_entries()[-1].truncate_lines == 2


def _texts(contents) -> list[str]:
    from prompt_toolkit.formatted_text import fragment_list_to_text, to_formatted_text

    return [fragment_list_to_text(to_formatted_text(c)) for c in contents]


class TestThinkingEchoRepaintParity:
    """The console echo of a finished thinking box and its repaint (after
    set_theme(repaint=True)) must print the same text."""

    @staticmethod
    def _printed(display: Display) -> list[str]:
        return _texts(display.kept)

    @pytest.mark.parametrize("fmt", ["plain", "ansi"])
    def test_content_that_fits_is_not_marked_truncated(self, kept_display, fmt):
        kept_display.thinking("a\nb\n", truncate_lines=2, content_format=fmt)
        echoed = self._printed(kept_display)
        repainted = _texts(kept_display.transcript())

        assert echoed == ["a\nb\n"]
        assert repainted == echoed


class TestThinkingEchoTail:
    """A tail box echoes "..." then its last lines; repaint matches."""

    _printed = staticmethod(TestThinkingEchoRepaintParity._printed)

    def test_tail_echo_keeps_last_lines(self, kept_display):
        content = "".join(f"line {i}\n" for i in range(10))
        kept_display.thinking(content, truncate_lines=3, overflow="tail")
        assert self._printed(kept_display) == ["...\nline 7\nline 8\nline 9\n"]

    @pytest.mark.parametrize("fmt", ["plain", "ansi"])
    def test_tail_repaint_matches_echo(self, kept_display, fmt):
        content = "".join(f"line {i}\n" for i in range(10))
        kept_display.thinking(
            content, truncate_lines=3, content_format=fmt, overflow="tail"
        )
        echoed = self._printed(kept_display)
        assert _texts(kept_display.transcript()) == echoed
        assert echoed == ["...\nline 7\nline 8\nline 9\n"]
