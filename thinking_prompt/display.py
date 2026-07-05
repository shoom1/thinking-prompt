"""
Display - Handles output to console and history buffer.

This module provides the Display class which manages all output for
ThinkingPromptSession, writing to both the console (for prompt mode)
and the FormattedTextHistory (for fullscreen mode).

Rich and Pygments integration utilities live in rich_utils; the names
are re-exported here for backward compatibility.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI, AnyFormattedText, FormattedText
from prompt_toolkit.styles import Style

from .history import FormattedTextHistory
from .rich_utils import (
    _highlight_code,
    _is_rich_renderable,
    _markdown_to_ansi,
    _renderable_to_ansi,
    _rich_to_ansi,
)
from .types import ContentFormat, truncate_ansi_to_lines, truncate_to_lines

if TYPE_CHECKING:
    from prompt_toolkit.output import ColorDepth

    from .styles import ThinkingPromptStyles

__all__ = [
    "Display",
    # Backward-compat re-exports (moved to rich_utils)
    "_highlight_code",
    "_is_rich_renderable",
    "_markdown_to_ansi",
    "_renderable_to_ansi",
    "_rich_to_ansi",
]


class Display:
    """
    Handles output to console and history buffer.

    Output behavior depends on mode:
    - Prompt mode: Write to both console and history
    - Fullscreen mode: Cache console output, write only to history

    When exiting fullscreen, call flush_pending() to output cached content.
    """

    def __init__(
        self,
        get_style: Callable[[], Style],
        is_fullscreen: Callable[[], bool] = lambda: False,
        thinking_styles: ThinkingPromptStyles | None = None,
        get_color_depth: Callable[[], ColorDepth | None] = lambda: None,
        history_limit: int | None = None,
    ) -> None:
        """
        Initialize the Display.

        Args:
            get_style: Callable returning the current prompt_toolkit Style for
                      rendering output. Called on every print so a runtime
                      theme change (see set_theme()) takes effect immediately.
            is_fullscreen: Callback that returns True if fullscreen mode is active.
                          Console output is cached in fullscreen mode.
            thinking_styles: Optional ThinkingPromptStyles for markdown rendering.
            get_color_depth: Callable that returns the effective color depth hint
                            for print_formatted_text. Defaults to a no-op
                            callable returning None.
            history_limit: Max transcript entries kept; oldest are trimmed.
                          None (default) means unbounded.
        """
        self._get_style = get_style
        self._is_fullscreen = is_fullscreen
        self._get_color_depth = get_color_depth
        self._pending_lock = threading.Lock()
        self._pending_output: list[AnyFormattedText] = []
        self._thinking_styles = thinking_styles
        # Assigned before _history is constructed: the render callbacks
        # below close over self._rich_theme/_markdown_code_theme so a
        # later set_theme() swap takes effect on the next render.
        self._rich_theme = self._create_rich_theme(thinking_styles)
        self._markdown_code_theme = (
            thinking_styles.markdown_code_theme if thinking_styles else "monokai"
        )
        self._history = FormattedTextHistory(
            max_entries=history_limit,
            render_markdown=lambda src: _markdown_to_ansi(
                src, theme=self._rich_theme, code_theme=self._markdown_code_theme
            ),
            render_code=_highlight_code,
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
        """Get the history buffer for fullscreen display."""
        return self._history

    @property
    def rich_theme(self) -> Any:
        """Get the Rich theme for consistent styling."""
        return self._rich_theme

    def set_theme(self, styles: ThinkingPromptStyles) -> None:
        """Adopt a new theme: rebuild Rich theme, re-render markdown/code."""
        self._thinking_styles = styles
        self._rich_theme = self._create_rich_theme(styles)
        self._markdown_code_theme = styles.markdown_code_theme
        self._history.invalidate_render_caches()

    def set_on_change(self, callback: Callable[[], None]) -> None:
        """
        Set callback for history changes (for UI invalidation).

        Args:
            callback: Function to call when history changes.
        """
        self._history.set_on_change(callback)

    # =========================================================================
    # Core Output Helpers
    # =========================================================================

    def _print_to_console(self, content: AnyFormattedText) -> None:
        """Print to console or cache if in fullscreen mode."""
        if self._is_fullscreen():
            with self._pending_lock:
                self._pending_output.append(content)
        else:
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
        # Store as ONE formatted entry so reprint_transcript emits a single
        # print matching the add-time echo below. Two styled entries would
        # be reprinted separately (each print adds a trailing newline, and
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
        """
        if not content.strip():
            return

        if content_format == "ansi":
            self._thinking_ansi(
                content,
                truncate_lines=truncate_lines,
                add_to_history=add_to_history,
                echo_to_console=echo_to_console,
            )
            return

        style = "class:history.thinking"

        # History gets full content, truncated on repaint to match console
        if add_to_history:
            self._history.append(style, f"{content}\n", truncate_lines=truncate_lines)

        # Console gets possibly truncated content
        if echo_to_console:
            if truncate_lines is not None:
                console_text = truncate_to_lines(content, truncate_lines) + "\n"
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
    ) -> None:
        """Output ANSI-formatted thinking content."""
        # History gets full content as baked ANSI, truncated on repaint to
        # match the console (never re-themed: ANSI escapes are already baked).
        if add_to_history:
            self._history.append_ansi(
                content.rstrip() + "\n", truncate_lines=truncate_lines
            )

        # Console gets possibly truncated content
        if echo_to_console:
            if truncate_lines is not None:
                console_content = truncate_ansi_to_lines(content, truncate_lines) + '\n'
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
            content, theme=self._rich_theme, code_theme=self._markdown_code_theme
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
        self._print_to_console(ANSI(_highlight_code(code, language)))

    def welcome(self, content: Any) -> None:
        """
        Output welcome message content.

        Handles Rich renderables (Panel, Text, etc.) by converting to ANSI,
        or plain text directly.

        Args:
            content: The welcome content (Rich renderable or string).
        """
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
        self._output_ansi(_rich_to_ansi(renderable, theme=self._rich_theme))

    def to_ansi(self, renderable: Any) -> ANSI:
        """
        Convert a Rich renderable to a prompt_toolkit ANSI object.

        Uses the Display's Rich theme for consistent styling.

        Args:
            renderable: Any Rich renderable object.

        Returns:
            An ANSI object with trailing newlines stripped.
        """
        ansi_str = _rich_to_ansi(renderable, theme=self._rich_theme)
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
        """Clear the history buffer and any pending console output.

        Clearing the terminal screen itself is the caller's job: while
        an Application is running it must go through the renderer so the
        renderer's state stays in sync with the screen (see
        ThinkingPromptSession.clear()).
        """
        # Clear history buffer
        self._history.clear()

        # Clear any pending output
        with self._pending_lock:
            self._pending_output.clear()

    def flush_pending(self) -> None:
        """
        Flush cached console output.

        Call this when exiting fullscreen mode to output content that was
        cached during fullscreen.
        """
        with self._pending_lock:
            pending = list(self._pending_output)
            self._pending_output.clear()
        for content in pending:
            print_formatted_text(
                content, style=self._get_style(), color_depth=self._get_color_depth()
            )

    def drop_pending(self) -> None:
        """Discard cached fullscreen console output (superseded by repaint)."""
        with self._pending_lock:
            self._pending_output.clear()

    def reprint_transcript(self) -> None:
        """Re-print every transcript entry to the console in the current theme.

        Console-only: nothing is appended to history. Thinking entries are
        truncated to their recorded truncate_lines, reproducing the form
        originally echoed. Runs on the event loop (called from set_theme).
        """
        for entry in self._history.iter_entries():
            if entry.kind == "styled":
                # Mirror the add-time console normalization: stored text
                # carries an unconditional trailing "\n" (on top of
                # whatever the caller's content already had), which would
                # otherwise throw off truncate_to_lines' line count and
                # add a spurious "..." marker on repaint.
                text = entry.text.rstrip("\n")
                if entry.truncate_lines is not None:
                    text = truncate_to_lines(text, entry.truncate_lines) + "\n"
                else:
                    text = text + "\n"
                self._print_to_console(FormattedText([(entry.style, text)]))
            elif entry.kind == "formatted":
                self._print_to_console(FormattedText(entry.fragments))
            elif entry.kind == "ansi" and entry.truncate_lines is not None:
                self._print_to_console(
                    ANSI(
                        truncate_ansi_to_lines(
                            entry.source.rstrip("\n"), entry.truncate_lines
                        )
                        + "\n"
                    )
                )
            else:  # markdown/code (fresh render via cache) and untruncated ansi
                self._print_to_console(FormattedText(self._history.render_entry(entry)))
