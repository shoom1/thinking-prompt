"""
Display - Handles output to console and history buffer.

This module provides the Display class which manages all output for
ThinkingPromptSession, writing to both the console and the
FormattedTextHistory (the transcript a repaint reprints). Rich and
Pygments are used through rich_utils.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI, AnyFormattedText, FormattedText, to_formatted_text
from prompt_toolkit.renderer import print_formatted_text as print_to_output
from prompt_toolkit.styles import Style, default_pygments_style, default_ui_style, merge_styles

from ._text import truncate_ansi_to_lines, truncate_to_lines
from .history import FormattedTextHistory
from .rich_utils import (
    _highlight_code,
    _is_rich_renderable,
    _markdown_to_ansi,
    _rich_to_ansi,
)
from .types import ContentFormat, Overflow

if TYPE_CHECKING:
    from prompt_toolkit.output import ColorDepth, Output

    from .styles import ThinkingPromptStyles

__all__ = ["Display"]


class Display:
    """
    Handles output to console and history buffer.

    Writes output to the console and records it in the history: the
    transcript a repaint prints again.
    """

    def __init__(
        self,
        get_style: Callable[[], Style],
        thinking_styles: ThinkingPromptStyles | None = None,
        get_color_depth: Callable[[], ColorDepth | None] = lambda: None,
        history_limit: int | None = None,
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
            history_limit: Max transcript entries kept; oldest are trimmed.
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
        # Assigned before _history is constructed: the render callbacks
        # below close over self._rich_theme/_code_theme so a later
        # set_theme() swap takes effect on the next render.
        self._rich_theme = self._create_rich_theme(thinking_styles)
        self._code_theme = thinking_styles.code_theme if thinking_styles else "monokai"
        self._history = FormattedTextHistory(
            max_entries=history_limit,
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
            if thinking_styles:
                return Theme(thinking_styles.to_rich_theme_dict())
            # Default simple theme with no colors
            from .styles import DEFAULT_STYLES
            return Theme(DEFAULT_STYLES.to_rich_theme_dict())
        except ImportError:
            return None

    @property
    def history(self) -> FormattedTextHistory:
        """Get the history buffer (the transcript)."""
        return self._history

    @property
    def rich_theme(self) -> Any:
        """Get the Rich theme for consistent styling."""
        return self._rich_theme

    @property
    def width(self) -> int | None:
        """The output's width in columns (None: unknown)."""
        return self._get_width()

    def set_theme(self, styles: ThinkingPromptStyles) -> None:
        """Adopt a new theme: rebuild Rich theme, re-render markdown/code."""
        self._thinking_styles = styles
        self._rich_theme = self._create_rich_theme(styles)
        self._code_theme = styles.code_theme
        self._history.invalidate_render_caches()

    # =========================================================================
    # Core Output Helpers
    # =========================================================================

    def _print_to_console(self, content: AnyFormattedText) -> None:
        """Print to the console."""
        print_formatted_text(
            content, style=self._get_style(), color_depth=self._get_color_depth()
        )

    def _output_styled(self, style: str, text: str) -> None:
        """Output styled text to history and console."""
        self._history.append(style, text)
        self._print_to_console(FormattedText([(style, text)]))

    def _output_ansi(self, content: str) -> None:
        """Output baked ANSI string to console and history.

        Used for rich/welcome/unstyled-raw output: this content is never
        re-themed, so it's stored as a baked ANSI entry rather than parsed
        into fragments up front.
        """
        self._history.append_ansi(content)
        self._print_to_console(ANSI(content))

    # =========================================================================
    # Output Methods
    # =========================================================================

    def user_input(self, prompt: str, text: str) -> None:
        """
        Output user input to console and history.

        Args:
            prompt: The prompt string that was shown.
            text: The user's input text.
        """
        # Store as ONE formatted entry so a repaint (transcript()) has a
        # single print matching the add-time echo below. Two styled entries
        # would be reprinted separately (each print adds a trailing newline, and
        # the prefix has none of its own), splitting ">>> hello" across
        # lines. One input is also one history_limit entry this way.
        self._history.append_formatted([
            ("class:history.user-prefix", prompt),
            ("class:history.user-message", f"{text}\n"),
        ])
        # Print as single formatted output
        self._print_to_console(FormattedText([
            ("class:history.user-prefix", prompt),
            ("class:history.user-message", f"{text}\n"),
        ]))

    def thinking(
        self,
        content: str,
        *,
        truncate_lines: int | None = None,
        add_to_history: bool = True,
        echo_to_console: bool = True,
        content_format: ContentFormat = "plain",
        overflow: Overflow = "head",
    ) -> None:
        """
        Output thinking content to console and history.

        Args:
            content: The thinking content.
            truncate_lines: If set, truncate console output to this many lines.
                           History always gets full content.
            add_to_history: If True, add to history.
            echo_to_console: If True, print to console.
            content_format: Format of the content ("plain" or "ansi").
            overflow: Which end truncation keeps: "head" (first lines) or
                "tail" (last lines) — match the box it came from.
        """
        if not content.strip():
            return

        if content_format == "ansi":
            self._thinking_ansi(
                content,
                truncate_lines=truncate_lines,
                add_to_history=add_to_history,
                echo_to_console=echo_to_console,
                overflow=overflow,
            )
            return

        style = "class:history.thinking"

        # History gets full content, truncated on repaint to match console
        if add_to_history:
            self._history.append(
                style, f"{content}\n",
                truncate_lines=truncate_lines, truncate_overflow=overflow,
            )

        # Console gets possibly truncated content
        if echo_to_console:
            if truncate_lines is not None:
                console_text = truncate_to_lines(content, truncate_lines, overflow=overflow) + "\n"
            else:
                console_text = content.rstrip() + "\n"
            self._print_to_console(FormattedText([(style, console_text)]))

    def _thinking_ansi(
        self,
        content: str,
        *,
        truncate_lines: int | None = None,
        add_to_history: bool = True,
        echo_to_console: bool = True,
        overflow: Overflow = "head",
    ) -> None:
        """Output ANSI-formatted thinking content."""
        # History gets full content as baked ANSI, truncated on repaint to
        # match the console (never re-themed: ANSI escapes are already baked).
        if add_to_history:
            self._history.append_ansi(
                content.rstrip() + "\n",
                truncate_lines=truncate_lines, truncate_overflow=overflow,
            )

        # Console gets possibly truncated content
        if echo_to_console:
            if truncate_lines is not None:
                console_content = truncate_ansi_to_lines(
                    content, truncate_lines, overflow=overflow
                ) + '\n'
            else:
                console_content = content.rstrip() + '\n'
            self._print_to_console(ANSI(console_content))

    def response(self, content: str) -> None:
        """
        Output assistant response to console and history.

        Args:
            content: The response content.
        """
        self._output_styled("class:history.assistant-message", f"{content}\n")

    def system(self, content: str) -> None:
        """
        Output system message to console and history.

        Args:
            content: The system message content.
        """
        self._output_styled("class:history.system", f"{content}\n")

    def error(self, content: str) -> None:
        """
        Output error message with [ERROR] prefix.

        Args:
            content: The error message content.
        """
        self._output_styled("class:history.error", f"[ERROR] {content}\n")

    def warning(self, content: str) -> None:
        """
        Output warning message with [WARN] prefix.

        Args:
            content: The warning message content.
        """
        self._output_styled("class:history.warning", f"[WARN] {content}\n")

    def success(self, content: str) -> None:
        """
        Output success message with [OK] prefix.

        Args:
            content: The success message content.
        """
        self._output_styled("class:history.success", f"[OK] {content}\n")

    def markdown(self, content: str) -> None:
        """
        Output markdown content, rendered via Rich to ANSI.

        Falls back to plain text if Rich is not installed. Stored in
        history by source so a later set_theme() can re-render it with
        the new Rich theme and code theme.

        Args:
            content: The markdown content.
        """
        rendered = _markdown_to_ansi(
            content, theme=self._rich_theme, code_theme=self._code_theme, width=self.width
        )
        self._history.append_markdown(content)
        self._print_to_console(ANSI(rendered))

    def code(self, code: str, language: str = "python") -> None:
        """
        Output syntax-highlighted code.

        Uses Pygments for highlighting. Falls back to plain text if not
        installed. Stored in history by source so a later set_theme() can
        re-render it.

        Args:
            code: The source code to highlight.
            language: The programming language (default: "python").
        """
        self._history.append_code(code, language)
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
        self._history.append_formatted(formatted_text)
        self._print_to_console(formatted_text)

    def rich(self, renderable: Any) -> None:
        """
        Output a Rich renderable (Panel, Table, Text, etc.) to console and history.

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
        """Clear the history buffer.

        Clearing the terminal screen itself is the caller's job: while
        an Application is running it must go through the renderer so the
        renderer's state stays in sync with the screen (see
        ThinkingPromptSession.clear()).
        """
        self._history.clear()

    def transcript(self) -> list[AnyFormattedText]:
        """Every transcript entry as the console shows it, in the current
        theme and width: what a repaint prints (print_now), as it is now.

        Nothing is appended to history. Thinking entries are truncated to
        their recorded truncate_lines, reproducing the form originally
        echoed.
        """
        # Markdown is laid out at the output's width: what was rendered at
        # another (before the terminal shrank) is rendered again.
        width = self.width
        if width != self._rendered_width:
            self._history.invalidate_render_caches()
            self._rendered_width = width
        contents: list[AnyFormattedText] = []
        for entry in self._history.iter_entries():
            if entry.kind == "styled":
                # Mirror the add-time console normalization: stored text
                # carries an unconditional trailing "\n" (on top of
                # whatever the caller's content already had); strip it so
                # the entry ends with exactly one newline, as echoed.
                text = entry.text.rstrip("\n")
                if entry.truncate_lines is not None:
                    text = truncate_to_lines(
                        text, entry.truncate_lines, overflow=entry.truncate_overflow
                    ) + "\n"
                else:
                    text = text + "\n"
                contents.append(FormattedText([(entry.style, text)]))
            elif entry.kind == "formatted":
                contents.append(FormattedText(entry.fragments))
            elif entry.kind == "ansi" and entry.truncate_lines is not None:
                contents.append(
                    ANSI(
                        truncate_ansi_to_lines(
                            entry.source.rstrip("\n"),
                            entry.truncate_lines,
                            overflow=entry.truncate_overflow,
                        )
                        + "\n"
                    )
                )
            else:  # markdown/code (fresh render via cache) and untruncated ansi
                contents.append(FormattedText(self._history.render_entry(entry)))
        return contents

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
