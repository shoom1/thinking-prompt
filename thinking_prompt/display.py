"""
Display - Handles output to console and history buffer.

This module provides the Display class which manages all output for
ThinkingPromptSession, writing to both the console (for prompt mode)
and the FormattedTextHistory (for fullscreen mode).

Also includes Rich and Pygments integration utilities for rendering
markdown, syntax highlighting, and Rich renderables.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI, AnyFormattedText, FormattedText
from prompt_toolkit.styles import Style

from .history import FormattedTextHistory
from .types import truncate_to_lines

if TYPE_CHECKING:
    from .styles import ThinkingPromptStyles


# =============================================================================
# Rich and Pygments Integration Helpers
# =============================================================================

def _is_rich_renderable(obj: Any) -> bool:
    """Check if an object is a Rich renderable."""
    return hasattr(obj, '__rich_console__') or hasattr(obj, '__rich__')


def _rich_to_ansi(renderable: Any, theme: Any = None) -> str:
    """Convert a Rich renderable to an ANSI-formatted string."""
    try:
        from rich.console import Console
        from io import StringIO
        file = StringIO()
        console = Console(file=file, force_terminal=True, theme=theme)
        console.print(renderable)
        return file.getvalue()
    except ImportError:
        return str(renderable)


def _setup_simple_heading() -> None:
    """Patch Rich's Markdown to use left-aligned headings with H1 underlined."""
    try:
        from rich.console import Console, ConsoleOptions, RenderResult
        from rich.markdown import Markdown, Heading
        from rich.text import Text

        class SimpleHeading(Heading):
            """Heading that renders left-aligned, bold, with H1 underlined."""

            def __rich_console__(
                self, console: Console, options: ConsoleOptions
            ) -> RenderResult:
                text = self.text
                text.justify = 'left'

                if self.tag == 'h1':
                    yield text
                    yield Text('─' * len(text.plain), style='markdown.h1.border')
                else:
                    if self.tag == 'h2':
                        yield Text('')
                    yield text

        Markdown.elements['heading_open'] = SimpleHeading
    except ImportError:
        pass


# Apply the simple heading patch at module load
_setup_simple_heading()


def _markdown_to_ansi(content: str, theme: Any = None) -> str:
    """Convert markdown to ANSI-formatted string using Rich."""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from io import StringIO

        file = StringIO()
        console = Console(file=file, force_terminal=True, theme=theme)
        console.print(Markdown(content))
        return file.getvalue()
    except ImportError:
        return content


def _highlight_code(code: str, language: str = "python") -> str:
    """Syntax highlight code using Pygments."""
    try:
        from pygments import highlight
        from pygments.lexers import get_lexer_by_name
        from pygments.formatters import TerminalFormatter
        lexer = get_lexer_by_name(language)
        return highlight(code, lexer, TerminalFormatter())
    except ImportError:
        return code
    except Exception:
        # Handle unknown language or other errors
        return code


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
        style: Style,
        is_fullscreen: Callable[[], bool] = lambda: False,
        thinking_styles: Optional[ThinkingPromptStyles] = None,
    ) -> None:
        """
        Initialize the Display.

        Args:
            style: The prompt_toolkit Style for rendering output.
            is_fullscreen: Callback that returns True if fullscreen mode is active.
                          Console output is cached in fullscreen mode.
            thinking_styles: Optional ThinkingPromptStyles for markdown rendering.
        """
        self._style = style
        self._history = FormattedTextHistory()
        self._is_fullscreen = is_fullscreen
        self._pending_lock = threading.Lock()
        self._pending_output: List[AnyFormattedText] = []
        self._rich_theme = self._create_rich_theme(thinking_styles)

    def _create_rich_theme(self, thinking_styles: Optional[ThinkingPromptStyles]) -> Any:
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

    def set_on_change(self, callback: Optional[Callable[[], None]]) -> None:
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
            print_formatted_text(content, style=self._style)

    def _output_styled(self, style: str, text: str) -> None:
        """Output styled text to history and console."""
        self._history.append(style, text)
        self._print_to_console(FormattedText([(style, text)]))

    def _output_ansi(self, content: str) -> None:
        """Output ANSI string to console and history."""
        self._history.append("", content)
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
        # Add to history as separate fragments
        self._history.append("class:history.user-prefix", prompt)
        self._history.append("class:history.user-message", f"{text}\n")
        # Print as single formatted output
        self._print_to_console(FormattedText([
            ("class:history.user-prefix", prompt),
            ("class:history.user-message", f"{text}\n"),
        ]))

    def thinking(
        self,
        content: str,
        *,
        truncate_lines: Optional[int] = None,
        add_to_history: bool = True,
        echo_to_console: bool = True,
    ) -> None:
        """
        Output thinking content to console and history.

        Args:
            content: The thinking content.
            truncate_lines: If set, truncate console output to this many lines.
                           History always gets full content.
            add_to_history: If True, add to history.
            echo_to_console: If True, print to console.
        """
        if not content.strip():
            return

        style = "class:history.thinking"

        # History gets full content
        if add_to_history:
            self._history.append(style, f"{content}\n")

        # Console gets possibly truncated content
        if echo_to_console:
            if truncate_lines is not None:
                console_text = truncate_to_lines(content, truncate_lines) + "\n"
            else:
                console_text = content.rstrip() + "\n"
            self._print_to_console(FormattedText([(style, console_text)]))

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

        Falls back to plain text if Rich is not installed.

        Args:
            content: The markdown content.
        """
        self._output_ansi(_markdown_to_ansi(content, theme=self._rich_theme))

    def code(self, code: str, language: str = "python") -> None:
        """
        Output syntax-highlighted code.

        Uses Pygments for highlighting. Falls back to plain text if not installed.

        Args:
            code: The source code to highlight.
            language: The programming language (default: "python").
        """
        self._output_ansi(_highlight_code(code, language))

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
        """Clear the terminal screen and history buffer."""
        # Clear terminal using ANSI escape codes
        # \033[2J clears screen, \033[H moves cursor to home position
        print("\033[2J\033[H", end="", flush=True)

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
            print_formatted_text(content, style=self._style)
