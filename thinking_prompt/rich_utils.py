"""
Rich and Pygments integration utilities.

Optional-dependency helpers used across the package: conversion of Rich
renderables, markup, and markdown to ANSI strings, plus Pygments syntax
highlighting. All rich/pygments imports are local to each function so
the package works without them installed.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any


def _is_rich_renderable(obj: Any) -> bool:
    """Check if an object is a Rich renderable."""
    return hasattr(obj, '__rich_console__') or hasattr(obj, '__rich__')


def _rich_to_ansi(renderable: Any, theme: Any = None) -> str:
    """Convert a Rich renderable to an ANSI-formatted string.

    Unlike ``_renderable_to_ansi``, this respects terminal width so that
    layout-aware renderables (Panel, Table, etc.) size correctly.
    """
    try:
        from io import StringIO

        from rich.console import Console
        file = StringIO()
        console = Console(file=file, force_terminal=True, theme=theme)
        console.print(renderable)
        return file.getvalue()
    except ImportError:
        return str(renderable)


def _renderable_to_ansi(renderable: Any, theme: Any = None) -> str:
    """Convert a Rich renderable or markup string to ANSI (no trailing newline/padding).

    Handles both markup strings like "[green]text[/green]" and Rich objects
    like Text("text", style="green").

    NO_COLOR is intentionally ignored here. The contract of this helper, and
    of the public APIs that build on it (rich_to_ansi, StreamingContent's
    append_rich/set_line_rich), is to produce ANSI-styled output for the
    thinking box. Stripping styling at this layer would silently neuter that
    promise. NO_COLOR semantics belong at the terminal-output layer, not at
    a converter that exists to emit ANSI.
    """
    try:
        from io import StringIO

        from rich.console import Console
        f = StringIO()
        console = Console(
            file=f,
            force_terminal=True,
            no_color=False,
            width=9999,
            theme=theme,
        )
        console.print(renderable, end="", highlight=False, soft_wrap=True)
        return f.getvalue().rstrip()
    except ImportError:
        return str(renderable)


@lru_cache(maxsize=1)
def _get_markdown_cls() -> Any:
    """Return a Markdown subclass with left-aligned headings (H1 underlined).

    Scoped on purpose: ``rich.markdown.Markdown`` itself is NOT modified,
    so a host application's own Rich markdown rendering is unaffected.
    (An earlier version patched ``Markdown.elements`` globally at import
    time, changing heading rendering process-wide.)

    Raises:
        ImportError: If Rich is not installed.
    """
    from rich.console import Console, ConsoleOptions, RenderResult
    from rich.markdown import Heading, Markdown
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

    class _LeftAlignedMarkdown(Markdown):
        elements = {**Markdown.elements, 'heading_open': SimpleHeading}

    return _LeftAlignedMarkdown


def _markdown_to_ansi(content: str, theme: Any = None, code_theme: str = "monokai") -> str:
    """Convert markdown to ANSI-formatted string using Rich."""
    try:
        from io import StringIO

        from rich.console import Console

        markdown_cls = _get_markdown_cls()
        file = StringIO()
        console = Console(file=file, force_terminal=True, theme=theme)
        console.print(markdown_cls(content, code_theme=code_theme))
        return file.getvalue()
    except ImportError:
        return content


def _highlight_code(code: str, language: str = "python", code_theme: str = "monokai") -> str:
    """Syntax highlight code using Pygments, in the given code theme.

    ``code_theme`` follows Rich's conventions, so one setting
    (``ThinkingPromptStyles.code_theme``) drives both fenced code in
    markdown and ``add_code()``: a Pygments style name ("monokai",
    "default", ...) renders in that style's colors; "ansi_dark" and
    "ansi_light" use the 16 named ANSI colors, inheriting the terminal's
    palette. An unknown name falls back to Pygments' "default" style, as
    Rich does.
    """
    try:
        from pygments import highlight
        from pygments.formatter import Formatter
        from pygments.formatters import TerminalFormatter, TerminalTrueColorFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.styles import get_style_by_name
        from pygments.util import ClassNotFound
    except ImportError:
        return code
    try:
        lexer = get_lexer_by_name(language)
        formatter: Formatter[str]
        if code_theme in ("ansi_dark", "ansi_light"):
            formatter = TerminalFormatter(bg="dark" if code_theme == "ansi_dark" else "light")
        else:
            try:
                style = get_style_by_name(code_theme)
            except ClassNotFound:
                style = get_style_by_name("default")
            formatter = TerminalTrueColorFormatter(style=style)
        return highlight(code, lexer, formatter)
    except Exception:
        # Handle unknown language or other errors
        return code
