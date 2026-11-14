"""
Rich and Pygments integration utilities.

Optional-dependency helpers used across the package: conversion of Rich
renderables, markup, and markdown to ANSI strings, plus Pygments syntax
highlighting. All rich/pygments imports are local to each function so
the package works without them installed.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

# A hyperlink as Rich writes one (OSC 8): ESC ] 8 ; params ; URL ST, its
# text, ESC ] 8 ; ; ST, where ST is BEL or ESC \. A link Rich splits (styles
# in its text, a wrap) is one per piece, the same params (its id) on each.
_LINK = re.compile(
    r"\x1b\]8;([^;\x07\x1b]*);([^\x07\x1b]*)(?:\x07|\x1b\\)(.*?)\x1b\]8;;(?:\x07|\x1b\\)", re.S
)
_COLOR_CODE = re.compile(r"\x1b\[[0-9;]*m")
# Any other OSC sequence: text can bring one (a window title, the clipboard).
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# An escape that doesn't start a color code: what's left of one cut short.
_STRAY_ESCAPE = re.compile(r"\x1b(?!\[)")
# prompt_toolkit's ANSI() writes the text between \x01 and \x02 to the
# terminal raw; C1 controls (U+0080-U+009F) are escapes of their own
# (U+009D starts an OSC, U+009B a color code).
_RAW_MARKS = str.maketrans("", "", "\x01\x02" + "".join(map(chr, range(0x80, 0xA0))))


def _ansi_safe(text: str) -> str:
    """Rich's or Pygments' output, for prompt_toolkit's ANSI(): with no
    \x01, \x02 or C1 control (text between \x01 and \x02 would reach the
    terminal raw, so a model's answer could set the window title or the
    clipboard), and no escapes but color codes. A hyperlink shows as its
    text, then its URL (_links_as_text): prompt_toolkit's parser knows only
    color codes, and printed the rest of one as text ("8;id=…;URL")."""
    text = _links_as_text(text.translate(_RAW_MARKS))
    return _STRAY_ESCAPE.sub("", _OSC.sub("", text))


def _links_as_text(ansi: str) -> str:
    """Rich's hyperlinks as their text, then " (URL)" after a link's last
    piece, unless its text is the URL: a terminal shows a hyperlink's URL
    only where it supports them, and one left open across the UI's partial
    redraws could spread to what's drawn after it. A URL shown as text, on
    its line, the terminal can open. It takes the spaces Rich padded the
    end of its line with, where there are some."""
    matches = list(_LINK.finditer(ansi))
    if not matches:
        return ansi
    url_after: dict[int, str] = {}  # a link's last piece (its start) -> " (URL)"
    for parts in _links(ansi, matches):
        url = parts[0].group(2)
        shown = _COLOR_CODE.sub("", "".join(part.group(3) for part in parts)).strip()
        if url and shown not in (url, url.split(":", 1)[-1]):  # "x@y" for "mailto:x@y"
            url_after[parts[-1].start()] = f" ({url})"
    out: list[str] = []
    added: list[tuple[int, int]] = []  # where a URL went in the output, how long
    done, pos = 0, 0
    for match in matches:
        out.append(ansi[pos:match.start()] + match.group(3))
        done += len(out[-1])
        extra = url_after.get(match.start())
        if extra:
            out.append(extra)
            added.append((done, len(extra)))
            done += len(extra)
        pos = match.end()
    out.append(ansi[pos:])
    text = "".join(out)
    if not added:
        return text
    # Each line as wide as before, where its padding allows.
    lines = text.split("\n")
    for index, columns in _per_line(text, added).items():
        line = lines[index]
        padding = len(line) - len(line.rstrip(" "))
        lines[index] = line[: len(line) - min(columns, padding)]
    return "\n".join(lines)


def _links(ansi: str, matches: list[re.Match[str]]) -> list[list[re.Match[str]]]:
    """The hyperlink pieces in ``ansi`` grouped by link: pieces side by side
    (only color codes between) with the same URL (Rich gives a link's
    differently styled pieces ids of their own), and pieces with the same
    id and URL (a link Rich wrapped)."""
    links: list[list[re.Match[str]]] = []
    by_id: dict[tuple[str, str], int] = {}
    previous: tuple[re.Match[str], int] | None = None  # the last piece, its link
    for match in matches:
        key = (match.group(1), match.group(2))
        if previous is not None and _beside(ansi, previous[0], match):
            index = previous[1]
        elif match.group(1) and key in by_id:
            index = by_id[key]
        else:
            index = len(links)
            links.append([])
        links[index].append(match)
        by_id[key] = index
        previous = (match, index)
    return links


def _beside(ansi: str, first: re.Match[str], second: re.Match[str]) -> bool:
    """True if hyperlink piece ``second`` goes on from ``first``: the same
    URL, with only color codes between them."""
    return first.group(2) == second.group(2) and not _COLOR_CODE.sub(
        "", ansi[first.end():second.start()]
    )


def _per_line(text: str, added: list[tuple[int, int]]) -> dict[int, int]:
    """The columns put in each line of ``text``: by line index."""
    per_line: dict[int, int] = {}
    for offset, length in added:
        index = text.count("\n", 0, offset)
        per_line[index] = per_line.get(index, 0) + length
    return per_line


def _is_rich_renderable(obj: Any) -> bool:
    """Check if an object is a Rich renderable."""
    return hasattr(obj, '__rich_console__') or hasattr(obj, '__rich__')


def _rich_to_ansi(renderable: Any, theme: Any = None, width: int | None = None) -> str:
    """Convert a Rich renderable to an ANSI-formatted string, as printing
    it to a console ``width`` columns wide would (None: the terminal's, as
    Rich finds it): text wraps, and a Panel or Table spans the width.
    """
    try:
        from io import StringIO

        from rich.console import Console
        file = StringIO()
        console = Console(file=file, force_terminal=True, theme=theme, width=width)
        console.print(renderable)
        return _ansi_safe(file.getvalue())
    except ImportError:
        return _ansi_safe(str(renderable))


def _renderable_to_ansi(renderable: Any, theme: Any = None, width: int | None = None) -> str:
    """Convert a Rich renderable or markup string to ANSI.

    Text (a markup string like "[green]text[/green]", or a Text) isn't
    wrapped: where it's shown wraps it. Its own whitespace is kept (a
    newline that ends it, a space before the next streamed word) and none
    is added. Other renderables (Panel, Table) are laid out ``width``
    columns wide (None: the terminal's, as Rich finds it), ending with
    their last line's newline.

    NO_COLOR is intentionally ignored here. The contract of this helper, and
    of the public APIs that build on it (a box's append_rich/set_line_rich),
    is to produce ANSI-styled output for the thinking box. Stripping styling at this layer would silently neuter that
    promise. NO_COLOR semantics belong at the terminal-output layer, not at
    a converter that exists to emit ANSI.
    """
    try:
        from io import StringIO

        from rich.console import Console
        from rich.text import Text
        f = StringIO()
        console = Console(
            file=f,
            force_terminal=True,
            no_color=False,
            width=width,
            theme=theme,
        )
        if isinstance(renderable, str):
            renderable = console.render_str(renderable, highlight=False)
        is_text = isinstance(renderable, Text)
        if is_text:
            # Unwrapped, so any width that holds it all is the same: before
            # Rich 14.3, text wider than the console lost a space that ended
            # it, and words streamed a piece at a time ran together.
            console.width = max(console.width, renderable.cell_len + 1)
        console.print(renderable, end="", highlight=False, soft_wrap=is_text)
        return _ansi_safe(f.getvalue())
    except ImportError:
        return _ansi_safe(str(renderable))


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


def _markdown_to_ansi(
    content: str, theme: Any = None, code_theme: str = "monokai", width: int | None = None
) -> str:
    """Convert markdown to ANSI-formatted string using Rich, laid out
    ``width`` columns wide (None: the terminal's, as Rich finds it). A link
    shows its text, then its URL (see _ansi_safe)."""
    try:
        from io import StringIO

        from rich.console import Console

        markdown_cls = _get_markdown_cls()
        file = StringIO()
        console = Console(file=file, force_terminal=True, theme=theme, width=width)
        console.print(markdown_cls(content, code_theme=code_theme))
        return _ansi_safe(file.getvalue())
    except ImportError:
        return _ansi_safe(content)


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
        return _ansi_safe(code)
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
        return _ansi_safe(highlight(code, lexer, formatter))
    except Exception:
        # Handle unknown language or other errors
        return _ansi_safe(code)
