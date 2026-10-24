"""
Thinking box control: draws one box's text (a FormattedTextControl).
"""
from __future__ import annotations

import logging
import re
import threading
from functools import lru_cache
from typing import Callable

from prompt_toolkit.formatted_text import (
    ANSI,
    FormattedText,
    StyleAndTextTuples,
    fragment_list_to_text,
    to_formatted_text,
)
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent
from prompt_toolkit.layout.screen import Char

from ._text import ANSI_SGR_RE, coalesce
from .types import ContentCallback, ContentFormat, Overflow

logger = logging.getLogger(__name__)

# Width assumed when formatting before the first render (size unknown).
_DEFAULT_WIDTH = 80


@lru_cache(maxsize=4096)
def _char_width(char: str) -> int:
    """Columns the window draws ``char`` in (a tab, drawn as ^I, takes 2)."""
    return Char(char).width


def _wrap(line: StyleAndTextTuples, width: int) -> list[StyleAndTextTuples]:
    """``line`` cut into the rows it takes at ``width`` columns, as the
    window wraps it: a character wider than what's left of a row starts
    the next one, even at the start of a row (one wider than the window
    leaves an empty row before it)."""
    if width <= 0:
        return [line]
    rows: list[StyleAndTextTuples] = [[]]
    used = 0
    for fragment in line:
        style, text = fragment[0], fragment[1]
        if "[ZeroWidthEscape]" in style:
            rows[-1].append((style, text))
            continue
        if text.isascii() and text.isprintable():  # a column a character
            while text:
                if used >= width:
                    rows.append([])
                    used = 0
                piece = text[: width - used]
                rows[-1].append((style, piece))
                used += len(piece)
                text = text[len(piece):]
            continue
        start = 0
        for i, char in enumerate(text):
            char_width = _char_width(char)
            if used + char_width > width:
                if i > start:
                    rows[-1].append((style, text[start:i]))
                rows.append([])
                used = 0
                start = i
            used += char_width
        if start < len(text):
            rows[-1].append((style, text[start:]))
    return rows


# An escape other than a color code. One can swallow the newline after it
# (e.g. "\x1b\n", or zero-width text "\x01...\x02"), so in ANSI text after
# one, a line can't be found by its newline.
_OTHER_ESCAPE_RE = re.compile(r"\x1b(?!\[[0-9;]*m)|[\x01\x9b]")

# Widths whose rows are kept. A box's height is counted at the terminal's
# width and it's drawn at its window's: one width, unless the window is
# narrower (or the terminal was resized).
_WIDTHS_KEPT = 4


def _resets(code: str) -> bool:
    """Whether a color code starts by resetting every style (its first
    parameter is 0 or empty, as in "\\x1b[0;32m" or "\\x1b[m")."""
    return not code[2:-1].split(";", 1)[0].strip("0")


def _in_force(replay: str, codes: list[str]) -> str:
    """The color codes that set the styles ``replay`` and then ``codes``
    leave in force: from the last one that resets every style."""
    for i in range(len(codes) - 1, -1, -1):
        if _resets(codes[i]):
            return "".join(codes[i:])
    return replay + "".join(codes)


class _ParsedLines:
    """The lines a box's text shows, parsed once per text.

    Streamed text grows at its end, so a text that starts as the last one
    did, up to its last line, is parsed from that line on: the lines before
    it are kept, and for ANSI text the color codes in force there are
    replayed before it. Any other text is parsed whole, as is ANSI text
    after an escape other than a color code. A line's rows are counted once
    for each width.
    """

    def __init__(self, style: str) -> None:
        self._style = style  # plain text's
        self._format: ContentFormat | None = None
        self._text = ""
        self._lines: list[StyleAndTextTuples] = []
        self._rows: dict[int, list[int]] = {}  # width -> each line's rows
        self._shown = 0  # lines but the trailing blank ones
        # Where the last line starts, whether the lines before it can be
        # kept, and the color codes in force there (ANSI).
        self._last_start = 0
        self._keepable = True
        self._replay = ""

    def update(self, text: str, content_format: ContentFormat) -> None:
        """Parse ``text``: from the last line on, when it can."""
        if content_format == self._format and text == self._text:
            return
        start = self._last_start
        if not (
            content_format == self._format
            and self._keepable
            and text.startswith(self._text[:start])
        ):
            self._format = content_format
            self._lines.clear()
            self._rows.clear()
            self._keepable = True
            self._replay = ""
            start = 0
        self._parse_from(text, start)

    def _parse_from(self, text: str, start: int) -> None:
        """Parse ``text`` from ``start``, where the last line starts."""
        keep = max(len(self._lines) - 1, 0)
        tail = text[start:]
        new: list[StyleAndTextTuples]
        if self._format == "ansi":
            fragments = to_formatted_text(ANSI(self._replay + tail))
            new = [coalesce(line) for line in split_lines(fragments)]
        else:
            new = [[(self._style, line)] for line in tail.split("\n")]
        del self._lines[keep:]
        self._lines.extend(new)
        for width, rows in self._rows.items():
            del rows[keep:]
            rows.extend(len(_wrap(line, width)) for line in new)

        last_start = text.rfind("\n") + 1
        if self._format == "ansi" and self._keepable:
            if _OTHER_ESCAPE_RE.search(text, start, last_start):
                self._keepable = False
            else:
                codes = ANSI_SGR_RE.findall(text, start, last_start)
                self._replay = _in_force(self._replay, codes)
        self._text = text
        self._last_start = last_start
        # Trailing blank lines aren't content (a trailing newline ends the
        # last line), as in split_content_lines.
        shown = len(self._lines)
        while shown > 1 and not fragment_list_to_text(self._lines[shown - 1]).strip():
            shown -= 1
        self._shown = shown

    @property
    def lines(self) -> list[StyleAndTextTuples]:
        """The lines shown, as fragments."""
        return self._lines[: self._shown]

    def rows(self, width: int) -> list[int]:
        """The rows each line shown takes at ``width`` columns."""
        rows = self._rows.get(width)
        if rows is None:
            if len(self._rows) == _WIDTHS_KEPT:
                del self._rows[next(iter(self._rows))]
            rows = self._rows[width] = [len(_wrap(line, width)) for line in self._lines]
        return rows[: self._shown]


def _format_key_for_display(key: str) -> str:
    """
    Format a prompt_toolkit key binding for display.

    Converts key binding syntax to human-readable format.
    Examples: "c-t" → "ctrl-t", "c-e" → "ctrl-e", "escape" → "escape"

    Args:
        key: Key binding in prompt_toolkit format.

    Returns:
        Human-readable key representation.
    """
    if key.startswith("c-"):
        return f"ctrl-{key[2:]}"
    return key


class ThinkingBoxControl(FormattedTextControl):
    """
    Draws one thinking box's text.

    It reads the text from ``get_text`` each time it's drawn, parses what
    changed since (streamed text: from its last line on), and fits it
    to the rows it gets: when it overflows, one end is kept (``overflow``:
    "tail" = newest lines, "head" = first lines) and a hint names the
    hidden lines. Collapsed, the rows are capped at ``max_collapsed_lines``;
    expanded, only by the window's height.

    Whether the box is expanded isn't its own state: it reads the
    ``expanded`` predicate it's given (ThinkingBoxManager passes the one
    mode all its boxes share). The box's life (its content, finishing it)
    is ThinkingBox's; the control only draws.

    Example:
        expanded = False
        chunks: list[str] = []
        control = ThinkingBoxControl(
            lambda: "".join(chunks), max_collapsed_lines=10, expanded=lambda: expanded
        )
        Window(content=control, ...)

        chunks.append("Processing...\\n")
        # Shown at the next redraw: the control reads its text when drawn.
        # on_draw= can ask for that redraw (ThinkingBoxManager's does).

        expanded = True  # e.g. the user pressed Ctrl+T
    """

    def __init__(
        self,
        get_text: ContentCallback,
        *,
        max_collapsed_lines: int = 15,
        style: str = "class:thinking-box",
        expand_key: str = "c-t",
        overflow: Overflow = "tail",
        content_format: ContentFormat = "plain",
        expanded: Callable[[], bool] | None = None,
        on_draw: Callable[[], None] | None = None,
    ) -> None:
        """
        Initialize the thinking box control.

        Args:
            get_text: Returns the text to draw; read on every draw. If it
                raises, the box draws nothing (logged once).
            max_collapsed_lines: Max lines when collapsed (must be >= 2).
            style: Style class for the content.
            expand_key: Key binding for expand/collapse (prompt_toolkit format).
            overflow: Which end of overflowing content stays visible:
                "tail" (newest lines, default) or "head" (first lines).
            content_format: "plain" or "ansi" (set_content_format() changes it).
            expanded: Whether the box is expanded right now (default:
                never). ThinkingBoxManager passes its shared mode.
            on_draw: Called each time the box is drawn. A box fed by a
                content callback uses it to be redrawn again shortly:
                nothing tells it when the callback's content changes.
        """
        self._get_text = get_text
        self._max_collapsed_lines = max_collapsed_lines
        self._box_style = style
        self._expand_key = expand_key
        self._overflow: Overflow = overflow
        # Width of the last render, for wrap-aware checks made between
        # renders (e.g. whether the expand key applies).
        self._last_width = _DEFAULT_WIDTH
        self._expanded = expanded or (lambda: False)
        self._on_draw = on_draw
        self._content_format: ContentFormat = content_format
        # A raising get_text is logged once, not on every redraw.
        self._callback_failed = False
        self._parsed = _ParsedLines(style)
        self._lock = threading.RLock()

        # Pass our formatting function to parent
        super().__init__(
            text=self._get_formatted_text,
            style=style,
            focusable=False,
            show_cursor=False,
        )

    @property
    def content_format(self) -> ContentFormat:
        """Get the current content format."""
        with self._lock:
            return self._content_format

    def set_content_format(self, fmt: ContentFormat) -> None:
        """Set the content format (e.g. to switch to ANSI mode dynamically)."""
        with self._lock:
            self._content_format = fmt

    def _get_formatted_text(self) -> FormattedText:
        """
        Get content as FormattedText, fitted as if rendered at the last
        known width with no height limit beyond the collapsed cap.

        Rendering goes through create_content(), which knows the real size;
        this is FormattedTextControl's text callable (and a test hook).
        """
        return self._format(self._last_width, None)

    def create_content(self, width: int, height: int | None) -> UIContent:
        """Render content fitted to the window's actual width and height.

        Bypasses FormattedTextControl's per-render text cache: the fit
        depends on the size, which its text callable can't see.
        """
        self._last_width = width
        if self._on_draw is not None:
            self._on_draw()
        fragments = to_formatted_text(self._format(width, height), style=self.style)
        lines = [list(line) for line in split_lines(fragments)]
        return UIContent(
            get_line=lambda i: lines[i], line_count=len(lines), show_cursor=False
        )

    def _format(self, width: int, height: int | None) -> FormattedText:
        """Fit the current content into ``height`` rows of ``width`` columns."""
        content = self.content
        if not content:
            return FormattedText([])

        with self._lock:
            if self.is_expanded:
                limit = height
            elif height is None:
                limit = self._max_collapsed_lines
            else:
                limit = min(height, self._max_collapsed_lines)
            parsed = self._parse(content)
            return self._fit(parsed.lines, parsed.rows(width), width, limit)

    def _parse(self, content: str) -> _ParsedLines:
        """The content's lines, parsed only as far as the text changed.

        ANSI content is parsed in order, so a style opened on an earlier
        line still applies to later lines even when the earlier ones are
        cut off.
        """
        self._parsed.update(content, self._content_format)
        return self._parsed

    def _fit(
        self,
        lines: list[StyleAndTextTuples],
        rows: list[int],
        width: int,
        limit: int | None,
    ) -> FormattedText:
        """Keep the rows that fit in ``limit`` rows (None = no limit).

        ``rows`` is the rows each line takes at ``width`` columns. On
        overflow the hint takes the rows it wraps to and the rest go to
        the rows at the ``overflow`` end: whole lines, then as many rows of
        the next line as fit (its end in tail mode, its start in head mode).
        A line cut so is hidden in part, and the hint counts it. With no row
        left for content beside the hint, the box shows content only.
        """
        if limit is None or sum(rows) <= limit:
            return self._join(lines)

        tail = self._overflow == "tail"
        order = range(len(lines) - 1, -1, -1) if tail else range(len(lines))
        # The hint's rows, counted at its longest (every line hidden): the
        # count it names can't make it wrap onto a row it wasn't given.
        hint_rows = len(_wrap([("", self._hint(len(lines)))], width))
        show_hint = hint_rows < limit
        room = limit - hint_rows if show_hint else limit
        body: list[StyleAndTextTuples] = []  # from the overflow end
        whole = 0
        for i in order:
            if rows[i] <= room:
                body.append(lines[i])
                whole += 1
                room -= rows[i]
                continue
            if room:
                wrapped = _wrap(lines[i], width)
                body.extend(reversed(wrapped[-room:]) if tail else wrapped[:room])
            break
        if tail:
            body.reverse()
        if not show_hint:
            return self._join(body)

        hint: StyleAndTextTuples = [
            ("class:thinking-box.hint", self._hint(len(lines) - whole))
        ]
        return self._join([hint, *body] if tail else [*body, hint])

    def _hint(self, hidden: int) -> str:
        """The line naming how many lines are hidden, and the toggle key."""
        noun = "line" if hidden == 1 else "lines"
        earlier = "earlier " if self._overflow == "tail" else ""
        action = "collapse" if self.is_expanded else "expand"
        key = _format_key_for_display(self._expand_key)
        return f"+{hidden} {earlier}{noun}... {key} to {action}"

    @staticmethod
    def _join(lines: list[StyleAndTextTuples]) -> FormattedText:
        """Join fragment lines with newlines."""
        out: StyleAndTextTuples = []
        for i, line in enumerate(lines):
            if i:
                out.append(("", "\n"))
            out.extend(line)
        return FormattedText(out)

    @property
    def content(self) -> str:
        """The text to draw ("" if get_text raises; logged once per box)."""
        try:
            return self._get_text()
        except Exception:
            if not self._callback_failed:
                self._callback_failed = True
                logger.exception("Error in content callback")
            return ""

    @property
    def is_expanded(self) -> bool:
        """Whether the box is expanded (read from its ``expanded`` predicate)."""
        return self._expanded()

    @property
    def max_collapsed_lines(self) -> int:
        """Get max lines for collapsed state."""
        return self._max_collapsed_lines

    @property
    def overflow(self) -> Overflow:
        """Which end of overflowing content stays visible."""
        return self._overflow

    @property
    def can_toggle_expanded(self) -> bool:
        """
        Check if expand toggle should be available.

        Returns True when:
        - Already expanded (can collapse), OR
        - Content overflows the collapsed rows (hint is visible)
        """
        with self._lock:
            if self.is_expanded:
                return True

            return self.get_line_count(self._last_width) > self._max_collapsed_lines

    def get_line_count(self, width: int = _DEFAULT_WIDTH) -> int:
        """
        Count display rows of the content, wrapped at ``width`` columns.

        Args:
            width: Terminal width for wrapping calculation.

        Returns:
            Number of display rows (0 when there is no content).
        """
        content = self.content
        if not content:
            return 0

        with self._lock:
            return sum(self._parse(content).rows(width))
