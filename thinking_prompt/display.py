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
from typing import Any, Callable, List, Literal, Optional, Tuple, Union

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.styles import Style

from .history import FormattedTextHistory
from .types import truncate_to_lines


# =============================================================================
# Rich and Pygments Integration Helpers
# =============================================================================

def _is_rich_renderable(obj: Any) -> bool:
    """Check if an object is a Rich renderable."""
    return hasattr(obj, '__rich_console__') or hasattr(obj, '__rich__')


def _rich_to_ansi(renderable: Any) -> str:
    """Convert a Rich renderable to an ANSI-formatted string."""
    try:
        from rich.console import Console
        from io import StringIO
        file = StringIO()
        console = Console(file=file, force_terminal=True)
        console.print(renderable)
        return file.getvalue()
    except ImportError:
        return str(renderable)


def _markdown_to_ansi(content: str) -> str:
    """Convert markdown to ANSI-formatted string using Rich."""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from io import StringIO

        file = StringIO()
        console = Console(file=file, force_terminal=True)
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
    ) -> None:
        """
        Initialize the Display.

        Args:
            style: The prompt_toolkit Style for rendering output.
            is_fullscreen: Callback that returns True if fullscreen mode is active.
                          Console output is cached in fullscreen mode.
        """
        self._style = style
        self._history = FormattedTextHistory()
        self._is_fullscreen = is_fullscreen
        # Pending console output: ('formatted', FormattedText) or ('raw', str)
        self._pending_output: List[Union[Tuple[Literal['formatted'], FormattedText], Tuple[Literal['raw'], str]]] = []
        self._pending_lock = threading.Lock()

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

    def _print_styled(self, text: str, style_class: str) -> None:
        """Print styled text to console (cached in fullscreen mode)."""
        formatted = FormattedText([(style_class, text)])
        if self._is_fullscreen():
            with self._pending_lock:
                self._pending_output.append(('formatted', formatted))
            return
        print_formatted_text(formatted, style=self._style)

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
        # History: styled prompt + message
        self._history.append("class:history.user-prefix", prompt)
        self._history.append("class:history.user-message", f"{text}\n")

        # Console: styled output (cached in fullscreen)
        formatted = FormattedText([
            ("class:history.user-prefix", prompt),
            ("class:history.user-message", f"{text}\n"),
        ])
        if self._is_fullscreen():
            with self._pending_lock:
                self._pending_output.append(('formatted', formatted))
        else:
            print_formatted_text(formatted, style=self._style)

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

        # History: full content (if requested)
        if add_to_history:
            self._history.append("class:history.thinking", f"{content}\n")

        # Console: optionally truncated (if echo enabled)
        if echo_to_console:
            if truncate_lines is not None:
                console_output = truncate_to_lines(content, truncate_lines)
            else:
                console_output = content.rstrip()

            self._print_styled(console_output + "\n", "class:history.thinking")

    def response(self, content: str) -> None:
        """
        Output assistant response to console and history.

        Args:
            content: The response content.
        """
        self._history.append("class:history.assistant-message", f"{content}\n")
        if content.strip():
            self._print_styled(content + "\n", "class:history.assistant-message")

    def system(self, content: str) -> None:
        """
        Output system message to console and history.

        Args:
            content: The system message content.
        """
        self._history.append("class:history.system", f"{content}\n")
        if content.strip():
            self._print_styled(content + "\n", "class:history.system")

    def error(self, content: str) -> None:
        """
        Output error message with [ERROR] prefix.

        Args:
            content: The error message content.
        """
        self._history.append("class:history.error", f"[ERROR] {content}\n")
        if content.strip():
            self._print_styled(f"[ERROR] {content}\n", "class:history.error")

    def warning(self, content: str) -> None:
        """
        Output warning message with [WARN] prefix.

        Args:
            content: The warning message content.
        """
        self._history.append("class:history.warning", f"[WARN] {content}\n")
        if content.strip():
            self._print_styled(f"[WARN] {content}\n", "class:history.warning")

    def success(self, content: str) -> None:
        """
        Output success message with [OK] prefix.

        Args:
            content: The success message content.
        """
        self._history.append("class:history.success", f"[OK] {content}\n")
        if content.strip():
            self._print_styled(f"[OK] {content}\n", "class:history.success")

    def markdown(self, content: str) -> None:
        """
        Output markdown content, rendered via Rich to ANSI.

        Falls back to plain text if Rich is not installed.

        Args:
            content: The markdown content.
        """
        ansi_content = _markdown_to_ansi(content)
        self._history.append("", ansi_content)
        if self._is_fullscreen():
            with self._pending_lock:
                self._pending_output.append(('raw', ansi_content))
        else:
            # Use ANSI class to preserve escape codes with print_formatted_text
            print_formatted_text(ANSI(ansi_content), style=self._style)

    def code(self, code: str, language: str = "python") -> None:
        """
        Output syntax-highlighted code.

        Uses Pygments for highlighting. Falls back to plain text if not installed.

        Args:
            code: The source code to highlight.
            language: The programming language (default: "python").
        """
        highlighted = _highlight_code(code, language)
        self._history.append("", highlighted)
        if self._is_fullscreen():
            with self._pending_lock:
                self._pending_output.append(('raw', highlighted))
        else:
            # Use ANSI class to preserve escape codes with print_formatted_text
            print_formatted_text(ANSI(highlighted), style=self._style)

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
            self.raw(str(content) + "\n")

    def formatted(self, formatted_text: FormattedText) -> None:
        """
        Output pre-formatted FormattedText directly.

        Args:
            formatted_text: A FormattedText object with (style, text) pairs.
        """
        self._history.append_formatted(formatted_text)
        if self._is_fullscreen():
            with self._pending_lock:
                self._pending_output.append(('formatted', formatted_text))
        else:
            print_formatted_text(formatted_text, style=self._style)

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
        ansi_content = _rich_to_ansi(renderable)
        self._history.append("", ansi_content)
        if self._is_fullscreen():
            with self._pending_lock:
                self._pending_output.append(('raw', ansi_content))
        else:
            print_formatted_text(ANSI(ansi_content), style=self._style)

    def raw(self, content: str, style_class: str = "") -> None:
        """
        Output raw content with optional style.

        Used for welcome messages and other content that doesn't fit
        the standard message types.

        Args:
            content: The content to output.
            style_class: Optional style class for the content.
        """
        self._history.append(style_class, content)
        if self._is_fullscreen():
            with self._pending_lock:
                if style_class:
                    formatted = FormattedText([(style_class, content)])
                    self._pending_output.append(('formatted', formatted))
                else:
                    self._pending_output.append(('raw', content))
            return
        if style_class:
            self._print_styled(content, style_class)
        else:
            print_formatted_text(ANSI(content), style=self._style)

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
        for item in pending:
            if item[0] == 'formatted':
                print_formatted_text(item[1], style=self._style)
            elif item[0] == 'raw':
                print_formatted_text(ANSI(item[1]), style=self._style)
