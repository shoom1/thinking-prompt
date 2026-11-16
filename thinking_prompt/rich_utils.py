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
from itertools import pairwise
from typing import Any

from ._text import fixed_sequences

# A hyperlink as Rich writes one (OSC 8): ESC ] 8 ; params ; URL ST, its
# text, ESC ] 8 ; ; ST, where ST is BEL or ESC \. A link Rich splits (styles
# in its text, a wrap) is one per piece, the same params (its id) on each.
_LINK = re.compile(
    r"\x1b\]8;([^;\x07\x1b]*);([^\x07\x1b]*)(?:\x07|\x1b\\)(.*?)\x1b\]8;;(?:\x07|\x1b\\)", re.S
)
_COLOR_CODE = re.compile(r"\x1b\[[0-9;]*m")
# Any other OSC sequence: text can bring one (a window title, the clipboard).
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# prompt_toolkit's ANSI() writes the text between \x01 and \x02 to the
# terminal raw; C1 controls (U+0080-U+009F) are escapes of their own
# (U+009D starts an OSC, U+009B a color code).
_RAW_MARKS = str.maketrans("", "", "\x01\x02" + "".join(map(chr, range(0x80, 0xA0))))


def _ansi_safe(text: str) -> str:
    """Rich's or Pygments' output, for prompt_toolkit's ANSI(): with no
    \x01, \x02 or C1 control (text between \x01 and \x02 would reach the
    terminal raw, so a model's answer could set the window title or the
    clipboard), and no escapes but color codes, each one prompt_toolkit's
    parser can take (see fixed_sequences). A hyperlink is left as its
    text: prompt_toolkit's parser knows only color codes, and printed the
    rest of one as text ("8;id=…;URL"). Its URL is shown as text where it
    was made (see _print_linked)."""
    text = _LINK.sub(lambda link: link.group(3), text.translate(_RAW_MARKS))
    # A sequence cut short at the end the parser would never finish.
    return fixed_sequences(_OSC.sub("", text), colors_only=True).text


def _is_url(text: str, url: str) -> bool:
    """True if a link showing ``text`` shows its URL already ("x@y" shows
    "mailto:x@y", and an autolink markdown-it's decoding of the URL it
    encoded): the URL isn't shown again."""
    decoded = _decoded(url)
    # Decoded, an escaped space would split the URL for the terminal: that
    # text doesn't show the URL.
    return text in (url, url.split(":", 1)[-1]) or (
        text == decoded and not any(char.isspace() for char in decoded)
    )


def _decoded(url: str) -> str:
    """``url`` as markdown-it shows an autolink's: percent escapes and
    punycode decoded ("…/%E6%97%A5" is "…/日")."""
    try:
        from markdown_it.common.normalize_url import normalizeLinkText
    except ImportError:
        return url
    return normalizeLinkText(url)


def _print_linked(console: Any, renderable: Any, **kwargs: Any) -> None:
    """Print ``renderable`` to ``console`` (writing to a StringIO), each link
    with its URL as text, since a terminal shows a hyperlink's URL only
    where it supports them: a Text's after each link, in brackets, laid
    out with the text; another renderable's (a Panel, a Table) listed under
    it, a line each, since Rich lays them out inside it."""
    from rich.text import Text

    if isinstance(renderable, Text):
        console.print(_with_urls(renderable, console), **kwargs)
        return
    start = len(console.file.getvalue())
    console.print(renderable, **kwargs)
    for line in _link_lines(console.file.getvalue()[start:]):
        console.print(line)


def _with_urls(text: Any, console: Any) -> Any:
    """``text`` (a Text) with each link's URL after it, in brackets (a link
    with no text shows its URL, one whose text is its URL nothing more),
    the link's text in markdown.link, the URL in markdown.link_url."""
    def url_of(style: Any) -> str | None:
        return console.get_style(style, default="none").link if style else None

    links: list[list[Any]] = []  # [start, end, URL], a link's pieces joined
    spans: list[tuple[int, int, str | None]] = [(0, len(text), url_of(text.style))]
    spans += [(span.start, span.end, url_of(span.style)) for span in text.spans]
    for start, end, url in sorted(spans, key=lambda span: span[0]):
        if not url:
            continue
        if links and links[-1][2] == url and start <= links[-1][1]:
            links[-1][1] = max(links[-1][1], end)
        else:
            links.append([start, end, url])
    if not links:
        return text
    text = text.copy()
    plain = text.plain
    # Each link's URL to show after its text, and whether in brackets.
    added: list[tuple[str, bool] | None] = []
    for start, end, url in links:
        shown = plain[start:end].strip()
        is_url = _is_url(shown, url)
        text.stylize("markdown.link_url" if is_url else "markdown.link", start, end)
        added.append(None if is_url else (url, bool(shown)))
    pieces = text.divide(link[1] for link in links)
    with_urls = text.blank_copy()
    for piece, after in zip(pieces, [*added, None], strict=True):
        with_urls.append_text(piece)
        if after is not None:
            url, bracketed = after
            with_urls.append(" (" if bracketed else "")
            with_urls.append(url, style="markdown.link_url")
            with_urls.append(")" if bracketed else "")
    return with_urls


def _link_lines(ansi: str) -> list[Any]:
    """The links in Rich's output ``ansi``, a Text each: its text, then its
    URL in brackets, in the styles of a markdown link; once each."""
    from rich.text import Text

    lines: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for parts in _links(ansi, list(_LINK.finditer(ansi))):
        url = parts[0].group(2)
        # A link Rich wrapped is one piece per line: a space between them.
        text = parts[0].group(3)
        for before, part in pairwise(parts):
            text += (" " if "\n" in ansi[before.end():part.start()] else "") + part.group(3)
        text = " ".join(_COLOR_CODE.sub("", text).split())
        if not url or (text, url) in seen:
            continue
        seen.add((text, url))
        if not text or _is_url(text, url):
            lines.append(Text(url, style="markdown.link_url"))
        else:
            lines.append(Text.assemble((text, "markdown.link"), " (", (url, "markdown.link_url"), ")"))
    return lines


def _links(ansi: str, matches: list[re.Match[str]]) -> list[list[re.Match[str]]]:
    """The hyperlink pieces in ``ansi`` grouped by link: pieces side by side
    (only color codes between) with the same URL (Rich gives a link's
    differently styled pieces ids of their own), and pieces with the same
    id and URL on the lines after (a link Rich wrapped: only spaces and
    borders between). Rich gives links from the same markup one id: the
    same id and URL further on is another link."""
    links: list[list[re.Match[str]]] = []
    by_id: dict[tuple[str, str], int] = {}
    previous: tuple[re.Match[str], int] | None = None  # the last piece, its link
    for match in matches:
        key = (match.group(1), match.group(2))
        if previous is not None and _beside(ansi, previous[0], match):
            index = previous[1]
        elif match.group(1) and key in by_id and _wrapped(ansi, links[by_id[key]][-1], match):
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


def _wrapped(ansi: str, first: re.Match[str], second: re.Match[str]) -> bool:
    """True if hyperlink piece ``second`` could go on from ``first`` on a
    later line: between them, a line's end and only spaces and borders."""
    between = _COLOR_CODE.sub("", ansi[first.end():second.start()])
    return "\n" in between and all(
        char.isspace() or char == "|" or "\u2500" <= char <= "\u259f" for char in between
    )


def _is_rich_renderable(obj: Any) -> bool:
    """Check if an object is a Rich renderable."""
    return hasattr(obj, '__rich_console__') or hasattr(obj, '__rich__')


def _rich_to_ansi(renderable: Any, theme: Any = None, width: int | None = None) -> str:
    """Convert a Rich renderable (or a markup string) to an ANSI-formatted
    string, as printing it to a console ``width`` columns wide would (None:
    the terminal's, as Rich finds it): text wraps, and a Panel or Table
    spans the width. Links show their URLs (see _print_linked)."""
    try:
        from io import StringIO

        from rich.console import Console
        file = StringIO()
        console = Console(
            file=file, force_terminal=True, legacy_windows=False, theme=theme, width=width
        )
        if isinstance(renderable, str):
            renderable = console.render_str(renderable)
        _print_linked(console, renderable)
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
    their last line's newline. Links show their URLs (see _print_linked).

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
            # The output goes through prompt_toolkit, never to a legacy
            # Windows console: Rich would drop links (and colors) for one.
            legacy_windows=False,
            no_color=False,
            width=width,
            theme=theme,
        )
        if isinstance(renderable, str):
            renderable = console.render_str(renderable, highlight=False)
        if isinstance(renderable, Text):
            renderable = _with_urls(renderable, console)
            # Unwrapped, so any width that holds it all is the same: before
            # Rich 14.3, text wider than the console lost a space that ended
            # it, and words streamed a piece at a time ran together.
            console.width = max(console.width, renderable.cell_len + 1)
            console.print(renderable, end="", highlight=False, soft_wrap=True)
        else:
            _print_linked(console, renderable, end="", highlight=False)
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
    from markdown_it.token import Token
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
                # As wide as its widest line: a link's URL can wrap it.
                lines = text.wrap(console, options.max_width)
                width = max((line.cell_len for line in lines), default=0)
                yield Text('─' * width, style='markdown.h1.border')
            else:
                if self.tag == 'h2':
                    yield Text('')
                yield text

    def styled(tag: str, tokens: list[Token]) -> list[Token]:
        """``tokens`` in the style markdown.<tag>, as Rich styles an inline
        tag (its token types its own: "link_open" is Rich's hyperlink)."""
        return [Token(f"styled_{tag}_open", tag, 1), *tokens, Token(f"styled_{tag}_close", tag, -1)]

    def text(content: str) -> Token:
        return Token("text", "", 0, content=content)

    def plain(tokens: list[Token]) -> str:
        return "".join(
            " " if token.type == "softbreak" else token.content
            for token in tokens
            if token.type in ("text", "code_inline", "softbreak")
        ).strip()

    def link(tokens: list[Token], url: str) -> list[Token]:
        """A link showing ``tokens``: them, then " (URL)"; the URL alone if
        they show nothing or are the URL."""
        shown = plain(tokens)
        if not shown:
            return styled("link_url", [text(url)])
        if _is_url(shown, url):
            return styled("link_url", tokens)
        if shown == _decoded(url):
            # An autolink with an escaped space: the URL as written, once.
            return styled("link_url", [text(url)])
        return [*styled("link", tokens), text(" ("), *styled("link_url", [text(url)]), text(")")]

    def links_shown(tokens: list[Token], listed: list[tuple[str, str]] | None) -> list[Token]:
        """A paragraph's tokens with each link as its text and URL (see
        link()), and an image as a link to it, "🌆 " first as Rich shows
        one (inside a link, its text alone): Rich lays the URL out with the
        text, within the width. ``listed``: a table cell's, where Rich cuts
        a word longer than the column with "…": each link shows its text
        alone and goes in ``listed`` (its text and URL), for under the
        table."""
        shown: list[Token] = []
        opened: list[tuple[str, int]] = []  # an open link's URL, where its text starts
        for token in tokens:
            if token.type == "link_open":
                opened.append((str(token.attrs.get("href", "")), len(shown)))
            elif token.type == "link_close" and opened:
                url, start = opened.pop()
                if listed is None:
                    shown[start:] = link(shown[start:], url)
                else:
                    listed.append((plain(shown[start:]), url))
                    shown[start:] = styled("link", shown[start:])
            elif token.type == "image":
                alt = plain(token.children or [])
                url = str(token.attrs.get("src", ""))
                shown.append(text("🌆 "))
                if opened:
                    shown.append(text(alt))
                elif listed is not None:
                    listed.append((alt, url))
                    shown += styled("link", [text(alt)])
                else:
                    shown += link([text(alt)], url)
            else:
                shown.append(token)
        return shown

    def listing(listed: list[tuple[str, str]]) -> list[Token]:
        """A paragraph of ``listed``'s links (see link()), a line each."""
        children: list[Token] = []
        for shown, url in dict.fromkeys(listed):
            if children:
                children.append(Token("hardbreak", "br", 0))
            children += link([text(shown)], url)
        inline = Token("inline", "", 0, children=children)
        return [Token("paragraph_open", "p", 1), inline, Token("paragraph_close", "p", -1)]

    class _LeftAlignedMarkdown(Markdown):
        elements = {**Markdown.elements, 'heading_open': SimpleHeading}
        # The styles of a link's text and its URL (see links_shown()).
        inlines = Markdown.inlines | {"link", "link_url"}

        def __init__(self, markup: str, **kwargs: Any) -> None:
            super().__init__(markup, **kwargs)
            parsed: list[Token] = []
            listed: list[tuple[str, str]] | None = None  # in a table: its links
            for token in self.parsed:
                if token.type == "table_open":
                    listed = []
                if token.type == "inline" and token.children:
                    token.children = links_shown(token.children, listed)
                parsed.append(token)
                if token.type == "table_close":
                    parsed += listing(listed) if listed else []
                    listed = None
            self.parsed = parsed

    return _LeftAlignedMarkdown


def _markdown_to_ansi(
    content: str, theme: Any = None, code_theme: str = "monokai", width: int | None = None
) -> str:
    """Convert markdown to ANSI-formatted string using Rich, laid out
    ``width`` columns wide (None: the terminal's, as Rich finds it). A link
    shows its text, then its URL in brackets, laid out with the text."""
    try:
        from io import StringIO

        from rich.console import Console

        markdown_cls = _get_markdown_cls()
        file = StringIO()
        console = Console(
            file=file, force_terminal=True, legacy_windows=False, theme=theme, width=width
        )
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
