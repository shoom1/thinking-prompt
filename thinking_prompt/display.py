"""
Display - Handles output to console and transcript.

This module provides the Display class which manages all output for
ThinkingPromptSession, writing to both the console and the
Transcript (what a repaint prints again). Rich and
Pygments are used through rich_utils.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI, AnyFormattedText, FormattedText, to_formatted_text
from prompt_toolkit.renderer import print_formatted_text as print_to_output
from prompt_toolkit.styles import Style, default_pygments_style, default_ui_style, merge_styles

from ._text import truncate_ansi_to_lines, truncate_to_lines
from .rich_utils import (
    _highlight_code,
    _is_rich_renderable,
    _markdown_to_ansi,
    _rich_to_ansi,
)
from .transcript import Transcript
from .types import ContentFormat, Overflow

if TYPE_CHECKING:
    from prompt_toolkit.output import ColorDepth, Output

    from .styles import ThinkingPromptStyles

__all__ = ["Display"]


class Display:
    """
    Handles output to console and transcript.

    Writes output to the console and records it in the transcript, which a
    repaint prints again.
    """

    def __init__(
        self,
        get_style: Callable[[], Style],
        thinking_styles: ThinkingPromptStyles | None = None,
        get_color_depth: Callable[[], ColorDepth | None] = lambda: None,
        transcript_limit: int | None = None,
        get_width: Callable[[], int | None] = lambda: None,
    ) -> None:
        """
        Initialize the Display.

        Args:
            get_style: Callable returning the current prompt_toolkit Style for
                      rendering output. Called on every print so a runtime
                      theme change (see set_theme()) takes effect immediately.
            thinking_styles: Optional ThinkingPromptStyles for markdown rendering.
            get_color_depth: Callable that returns the effective color depth hint
                            for print_formatted_text. Defaults to a no-op
                            callable returning None.
            transcript_limit: Max transcript entries kept; oldest are trimmed.
                             None (default) means unbounded.
            get_width: Callable returning the output's width in columns,
                      which Rich lays output out at (markdown, a Panel).
                      None (the default's) leaves Rich to find the
                      terminal's.
        """
        self._get_style = get_style
        self._get_color_depth = get_color_depth
        self._get_width = get_width
        # The width the transcript's markdown was last rendered at.
        self._rendered_width: int | None = None
        self._thinking_styles = thinking_styles
        # Assigned before _transcript is constructed: the render callbacks
        # below close over self._rich_theme/_code_theme so a later
        # set_theme() swap takes effect on the next render.
        self._rich_theme = self._create_rich_theme(thinking_styles)
        self._code_theme = thinking_styles.code_theme if thinking_styles else "monokai"
        self._transcript = Transcript(
            max_entries=transcript_limit,
            render_markdown=lambda src: _markdown_to_ansi(
                src, theme=self._rich_theme, code_theme=self._code_theme, width=self.width
            ),
            render_code=lambda src, language: _highlight_code(
                src, language, code_theme=self._code_theme
            ),
        )

    def _create_rich_theme(self, thinking_styles: ThinkingPromptStyles | None) -> Any:
        """Create a Rich Theme from ThinkingPromptStyles."""
        try:
            from rich.theme import Theme

            from .styles import ThinkingPromptStyles
            styles = thinking_styles or ThinkingPromptStyles()
            return Theme(styles._rich_theme_dict())
        except ImportError:
            return None

    @property
    def transcript(self) -> Transcript:
        """What was printed, which a repaint prints again."""
        return self._transcript

    @property
    def rich_theme(self) -> Any:
        """Get the Rich theme for consistent styling."""
        return self._rich_theme

    @property
    def width(self) -> int | None:
        """The output's width in columns (None: unknown)."""
        return self._get_width()

    def set_theme(self, styles: ThinkingPromptStyles) -> None:
        """Adopt a new theme: rebuild Rich theme, re-render markdown/code.
        The Rich theme is built first: a theme Rich can't parse is refused
        with the Display unchanged."""
        rich_theme = self._create_rich_theme(styles)
        self._thinking_styles = styles
        self._rich_theme = rich_theme
        self._code_theme = styles.code_theme
        self._transcript.invalidate_render_caches()

    # =========================================================================
    # Core Output Helpers
    # =========================================================================

    def _print_to_console(self, content: AnyFormattedText) -> None:
        """Print to the console."""
        print_formatted_text(
            content, style=self._get_style(), color_depth=self._get_color_depth()
        )

    def _output_styled(self, style: str, text: str) -> None:
        """Output styled text to the transcript and console."""
        self._transcript.append(style, text)
        self._print_to_console(FormattedText([(style, text)]))

    def _output_ansi(self, content: str) -> None:
        """Output baked ANSI string to console and transcript.

        Used for rich/welcome/unstyled-raw output: this content is never
        re-themed, so it's stored as a baked ANSI entry rather than parsed
        into fragments up front.
        """
        self._transcript.append_ansi(content)
        self._print_to_console(ANSI(content))

    # =========================================================================
    # Output Methods
    # =========================================================================

    def user_input(self, prompt: str, text: str) -> None:
        """
        Output user input to console and transcript.

        Args:
            prompt: The prompt string that was shown.
            text: The user's input text.
        """
        # Store as ONE formatted entry so a repaint (transcript()) has a
        # single print matching the add-time echo below. Two styled entries
        # would be reprinted separately (each print adds a trailing newline, and
        # the prefix has none of its own), splitting ">>> hello" across
        # lines. One input is also one transcript_limit entry this way.
        self._transcript.append_formatted([
            ("class:transcript.user-prefix", prompt),
            ("class:transcript.user-message", f"{text}\n"),
        ])
        # Print as single formatted output
        self._print_to_console(FormattedText([
            ("class:transcript.user-prefix", prompt),
            ("class:transcript.user-message", f"{text}\n"),
        ]))

    def thinking(
        self,
        content: str,
        *,
        truncate_lines: int | None = None,
        content_format: ContentFormat = "plain",
        overflow: Overflow = "head",
    ) -> None:
        """
        Output thinking content to console and transcript.

        Args:
            content: The thinking content.
            truncate_lines: If set, cut the text to this many lines, at the
                           ``overflow`` end, as printed and as kept.
            content_format: Format of the content ("plain" or "ansi").
            overflow: Which end truncation keeps: "head" (first lines) or
                "tail" (last lines) — match the box it came from.
        """
        if not content.strip():
            return

        if content_format == "ansi":
            self._thinking_ansi(content, truncate_lines=truncate_lines, overflow=overflow)
            return

        if truncate_lines is not None:
            text = truncate_to_lines(content, truncate_lines, overflow=overflow) + "\n"
        else:
            text = content.rstrip() + "\n"
        self._output_styled("class:transcript.thinking", text)

    def _thinking_ansi(
        self,
        content: str,
        *,
        truncate_lines: int | None = None,
        overflow: Overflow = "head",
    ) -> None:
        """Output ANSI-formatted thinking content (baked: never re-themed)."""
        if truncate_lines is not None:
            text = truncate_ansi_to_lines(content, truncate_lines, overflow=overflow) + "\n"
        else:
            text = content.rstrip() + "\n"
        self._output_ansi(text)

    def response(self, content: str) -> None:
        """
        Output assistant response to console and transcript.

        Args:
            content: The response content.
        """
        self._output_styled("class:transcript.assistant-message", f"{content}\n")

    def system(self, content: str) -> None:
        """
        Output system message to console and transcript.

        Args:
            content: The system message content.
        """
        self._output_styled("class:transcript.system", f"{content}\n")

    def error(self, content: str) -> None:
        """
        Output error message with [ERROR] prefix.

        Args:
            content: The error message content.
        """
        self._output_styled("class:transcript.error", f"[ERROR] {content}\n")

    def warning(self, content: str) -> None:
        """
        Output warning message with [WARN] prefix.

        Args:
            content: The warning message content.
        """
        self._output_styled("class:transcript.warning", f"[WARN] {content}\n")

    def success(self, content: str) -> None:
        """
        Output success message with [OK] prefix.

        Args:
            content: The success message content.
        """
        self._output_styled("class:transcript.success", f"[OK] {content}\n")

    def markdown(self, content: str) -> None:
        """
        Output markdown content, rendered via Rich to ANSI.

        Falls back to plain text if Rich is not installed. Stored in
        the transcript by source so a later set_theme() can re-render it with
        the new Rich theme and code theme.

        Args:
            content: The markdown content.
        """
        rendered = _markdown_to_ansi(
            content, theme=self._rich_theme, code_theme=self._code_theme, width=self.width
        )
        self._transcript.append_markdown(content)
        self._print_to_console(ANSI(rendered))

    def code(self, code: str, language: str = "python") -> None:
        """
        Output syntax-highlighted code.

        Uses Pygments for highlighting. Falls back to plain text if not
        installed. Stored in the transcript by source so a later set_theme() can
        re-render it.

        Args:
            code: The source code to highlight.
            language: The programming language (default: "python").
        """
        self._transcript.append_code(code, language)
        self._print_to_console(
            ANSI(_highlight_code(code, language, code_theme=self._code_theme))
        )

    def welcome(self, content: Any) -> None:
        """
        Output welcome message content.

        Handles Rich renderables (Panel, Text, etc.) by converting to ANSI,
        or plain text directly. Empty content ("" or None) prints nothing.

        Args:
            content: The welcome content (Rich renderable or string).
        """
        if content is None or content == "":
            return
        if _is_rich_renderable(content):
            self.rich(content)
        else:
            self._output_ansi(str(content) + "\n")

    def formatted(self, formatted_text: FormattedText) -> None:
        """
        Output pre-formatted FormattedText directly.

        Args:
            formatted_text: A FormattedText object with (style, text) pairs.
        """
        self._transcript.append_formatted(formatted_text)
        self._print_to_console(formatted_text)

    def rich(self, renderable: Any) -> None:
        """
        Output a Rich renderable (Panel, Table, Text, etc.) to console and transcript.

        Converts the renderable to ANSI-formatted string using Rich's Console.
        Falls back to str() if Rich is not installed.

        Args:
            renderable: Any Rich renderable object (Panel, Table, Text, Tree, etc.).

        Example:
            from rich.panel import Panel
            from rich.table import Table

            display.rich(Panel("Hello World", title="Greeting"))

            table = Table(title="Users")
            table.add_column("Name")
            table.add_row("Alice")
            display.rich(table)
        """
        self._output_ansi(_rich_to_ansi(renderable, theme=self._rich_theme, width=self.width))

    def to_ansi(self, renderable: Any) -> ANSI:
        """
        Convert a Rich renderable to a prompt_toolkit ANSI object.

        Uses the Display's Rich theme for consistent styling.

        Args:
            renderable: Any Rich renderable object.

        Returns:
            An ANSI object with trailing newlines stripped.
        """
        ansi_str = _rich_to_ansi(renderable, theme=self._rich_theme, width=self.width)
        return ANSI(ansi_str.rstrip("\n"))

    def raw(self, content: str, style_class: str = "") -> None:
        """
        Output raw content with optional style.

        Used for welcome messages and other content that doesn't fit
        the standard message types.

        Args:
            content: The content to output.
            style_class: Optional style class for the content.
        """
        if style_class:
            self._output_styled(style_class, content)
        else:
            self._output_ansi(content)

    def clear(self) -> None:
        """Clear the transcript.

        Clearing the terminal screen itself is the caller's job: while
        an Application is running it must go through the renderer so the
        renderer's state stays in sync with the screen (see
        ThinkingPromptSession.clear()).
        """
        self._transcript.clear()

    def printed_contents(self) -> list[AnyFormattedText]:
        """Every transcript entry as the console shows it, in the current
        theme and width: what a repaint prints (print_now), as it is now.

        Each entry is what was printed; nothing is appended to the
        transcript.
        """
        # Markdown is laid out at the output's width: what was rendered at
        # another (before the terminal shrank) is rendered again.
        width = self.width
        if width != self._rendered_width:
            self._transcript.invalidate_render_caches()
            self._rendered_width = width
        return [
            FormattedText(self._transcript.render_entry(entry))
            for entry in self._transcript.iter_entries()
        ]

    def print_now(self, output: Output, contents: list[AnyFormattedText]) -> None:
        """Print ``contents`` to ``output`` at once, each as _print_to_console
        would (print_formatted_text's style and newline), for a caller that
        has the terminal to itself: a run_in_terminal job, or no app running.
        print_formatted_text itself queues one run_in_terminal job per call
        while an app runs, each redrawing the app."""
        style = merge_styles([default_ui_style(), default_pygments_style(), self._get_style()])
        color_depth = self._get_color_depth() or output.get_default_color_depth()
        for content in contents:
            fragments = [*to_formatted_text(content, auto_convert=True), ("", "\n")]
            print_to_output(output, fragments, style, color_depth=color_depth)
