"""
Tests for ThinkingBoxControl.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest
from prompt_toolkit.formatted_text import FormattedText

from thinking_prompt.thinking_control import ThinkingBoxControl


def _control(text: str = "", **kwargs: Any) -> ThinkingBoxControl:
    """A control showing ``text`` (max_collapsed_lines=15 unless given)."""
    kwargs.setdefault("max_collapsed_lines", 15)
    return ThinkingBoxControl(lambda: text, **kwargs)


def _expanded_control(text: str, max_collapsed_lines: int = 5, **kwargs: Any) -> ThinkingBoxControl:
    """A box whose expand mode (normally the manager's) is on."""
    return ThinkingBoxControl(
        lambda: text, max_collapsed_lines=max_collapsed_lines, expanded=lambda: True, **kwargs
    )


class TestThinkingBoxControlBasics:
    """Test basic functionality of ThinkingBoxControl."""

    def test_empty_text_shows_nothing(self):
        control = _control("")
        assert not control.is_expanded
        assert control.content == ""
        assert control._get_formatted_text() == FormattedText([])

    def test_reads_its_text(self):
        assert _control("hello world").content == "hello world"

    def test_on_draw_runs_on_every_draw(self):
        draws: list[int] = []
        control = ThinkingBoxControl(lambda: "x", on_draw=lambda: draws.append(1))
        control.create_content(40, 5)
        control.create_content(40, 5)
        assert draws == [1, 1]


class TestThinkingBoxControlExpansion:
    """Test expansion/collapse functionality."""

    def test_collapsed_without_an_expand_predicate(self):
        """A box on its own (no manager) stays collapsed."""
        control = _control("test")
        assert not control.is_expanded

    def test_can_toggle_when_expanded(self):
        """Should be able to toggle when already expanded."""
        control = _expanded_control("test", 15)
        assert control.can_toggle_expanded

    def test_cannot_toggle_when_empty(self):
        assert not _control("").can_toggle_expanded

    def test_can_toggle_counts_rows_at_the_last_width_drawn(self):
        """Five 60-column lines fit five rows at 80 columns, but wrap to
        ten at 40."""
        control = _control(("x" * 60 + "\n") * 5, max_collapsed_lines=5)
        _rendered(control, 40, 5)
        assert control.can_toggle_expanded is True
        _rendered(control, 80, 5)
        assert control.can_toggle_expanded is False


class TestThinkingBoxControlFormatting:
    """Test FormattedText output."""

    def test_formatted_text_no_hint_when_expanded(self, multiline_content: str):
        """Expanded with no height limit: all the content, and no hint."""
        control = _expanded_control(multiline_content)
        formatted = control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert text == multiline_content

    def test_formatted_text_uses_custom_key_in_hint(self, multiline_content: str):
        """Formatted text should use custom key in expand hint."""
        control = ThinkingBoxControl(
            lambda: multiline_content, max_collapsed_lines=3, expand_key="c-x"
        )
        formatted = control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert "ctrl-x to expand" in text


class TestThinkingBoxControlLineCount:
    """Test line count calculation."""

    def test_line_count_zero_when_empty(self):
        """Line count should be zero when no content."""
        assert _control("").get_line_count() == 0

    def test_line_count_counts_newlines(self):
        """Line count should count newlines correctly."""
        control = _control("line1\nline2\nline3")
        assert control.get_line_count() == 3

    def test_line_count_accounts_for_wrapping(self):
        """Line count should account for line wrapping."""
        # 100 chars should wrap at width 80
        long_line = "x" * 100
        control = _control(long_line)
        assert control.get_line_count(width=80) == 2

    def test_line_count_handles_empty_lines(self):
        """Line count should handle empty lines."""
        control = _control("line1\n\nline3")
        assert control.get_line_count() == 3

    def test_line_count_ignores_ansi_escape_bytes(self):
        """SGR escape sequences occupy no columns and must not count
        toward wrapping. 60 visible chars heavily styled used to be
        measured as >80 bytes and reported as 2 lines."""
        styled = "\x1b[1m\x1b[31m" + ("x" * 30) + "\x1b[0m\x1b[32m" + ("y" * 30) + "\x1b[0m"
        assert len(styled) > 80  # raw bytes would wrap at width 80
        control = _control(styled, content_format="ansi")
        assert control.get_line_count(width=80) == 1


class TestThinkingBoxControlAnsiFormat:
    """Test ANSI format rendering in ThinkingBoxControl."""

    def test_default_format_is_plain(self):
        """Default content format should be plain."""
        assert _control("x").content_format == "plain"

    def test_ansi_format_from_the_constructor(self):
        assert _control("test", content_format="ansi").content_format == "ansi"

    def test_set_content_format(self):
        """set_content_format should change the format dynamically."""
        control = _control("test")
        assert control.content_format == "plain"
        control.set_content_format("ansi")
        assert control.content_format == "ansi"

    def test_ansi_formatted_text_parses_escape_codes(self):
        """ANSI format should parse escape codes in formatted text."""
        # \033[32m = green, \033[0m = reset
        ansi_content = "\033[32m✓ Step 1\033[0m\n"
        control = _control(ansi_content, content_format="ansi")
        formatted = control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert text == "✓ Step 1"  # no escape bytes left
        assert all("ansigreen" in style for style, chunk in formatted if chunk)

    def test_ansi_truncation_with_hint(self):
        """ANSI content should be truncated with hint when overflowing."""
        lines = [f"\033[32mLine {i}\033[0m" for i in range(20)]
        content = "\n".join(lines)
        control = _control(content, max_collapsed_lines=5, content_format="ansi")
        formatted = control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert "ctrl-t to expand" in text

    def test_ansi_no_truncation_when_expanded(self):
        """ANSI content should show fully when expanded."""
        lines = [f"\033[32mLine {i}\033[0m" for i in range(20)]
        content = "\n".join(lines)
        control = _expanded_control(content, content_format="ansi")
        formatted = control._get_formatted_text()

        text = "".join(frag[1] for frag in formatted)
        assert text == "\n".join(f"Line {i}" for i in range(20))

    def test_plain_format_unchanged(self):
        """Plain format should work exactly as before."""
        control = _control("Hello World")
        formatted = control._get_formatted_text()
        assert len(formatted) == 1
        assert formatted[0] == ("class:thinking-box", "Hello World")


class TestTrailingNewline:
    """A trailing newline ends the last line; it does not start a new,
    hidden one. Content built with append("...\\n") — the documented
    pattern — must not report phantom hidden lines."""

    @staticmethod
    def _lines(n: int) -> str:
        return "".join(f"line {i}\n" for i in range(n))

    @staticmethod
    def _hint(control: ThinkingBoxControl) -> str:
        return "".join(t for s, t in control._get_formatted_text() if "hint" in s)

    def test_content_that_fits_shows_no_hint(self):
        content = self._lines(4)  # max_collapsed_lines=5: 4 lines fit
        control = _control(content, max_collapsed_lines=5)
        assert self._hint(control) == ""
        assert control.can_toggle_expanded is False
        assert control.get_line_count() == 4

    def test_hidden_count_excludes_trailing_newline(self):
        content = self._lines(20)  # 4 shown, 16 hidden
        control = _control(content, max_collapsed_lines=5)
        assert self._hint(control).startswith("+16 earlier lines")

    def test_ansi_hidden_count_excludes_trailing_newline(self):
        content = "".join(f"\033[32mline {i}\033[0m\n" for i in range(20))
        control = _control(content, max_collapsed_lines=5, content_format="ansi")
        assert self._hint(control).startswith("+16 earlier lines")


def _rendered(control: ThinkingBoxControl, width: int, height: int) -> list[str]:
    """The text lines the control renders into a width x height window."""
    from prompt_toolkit.formatted_text import fragment_list_to_text

    ui = control.create_content(width, height)
    return [fragment_list_to_text(ui.get_line(i)) for i in range(ui.line_count)]


def _numbered(n: int) -> str:
    return "".join(f"line {i}\n" for i in range(n))


def _wrapped(text: str, width: int) -> list[str]:
    """The rows _wrap cuts ``text`` into, as the screen shows them."""
    from prompt_toolkit.formatted_text import fragment_list_to_text
    from prompt_toolkit.layout.screen import Char

    from thinking_prompt.thinking_control import _wrap

    return [
        "".join(Char(c).char for c in fragment_list_to_text(row))
        for row in _wrap([("", text)], width)
    ]


def _drawn(text: str, width: int) -> list[str]:
    """The rows a wrapping window ``width`` columns wide draws ``text`` in."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.application.current import set_app
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.layout import FormattedTextControl, Window
    from prompt_toolkit.layout.mouse_handlers import MouseHandlers
    from prompt_toolkit.layout.screen import Screen, WritePosition
    from prompt_toolkit.output import DummyOutput

    height = 20
    with create_pipe_input() as inp, set_app(Application(output=DummyOutput(), input=inp)):
        screen = Screen()
        window = Window(FormattedTextControl(text), wrap_lines=True)
        window.write_to_screen(
            screen, MouseHandlers(), WritePosition(0, 0, width, height), "",
            erase_bg=False, z_index=None,
        )
    rows = [
        "".join(screen.data_buffer[y][x].char for x in range(width + 1)).rstrip()
        for y in range(height)
    ]
    while rows and not rows[-1]:
        rows.pop()
    return rows


def _words(n: int, start: int = 0) -> str:
    """Words w00, w01, ...: 4 columns each with the space between."""
    return " ".join(f"w{i:02d}" for i in range(start, start + n))


class TestOverflowTail:
    """Default: an overflowing box shows its newest lines under a hint."""

    def test_collapsed_shows_newest_lines_under_hint(self):
        content = _numbered(60)
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5)
        assert _rendered(control, 40, 5) == [
            "+56 earlier lines... ctrl-t to expand",
            "line 56", "line 57", "line 58", "line 59",
        ]

    def test_one_row_shows_the_newest_line_and_no_hint(self):
        """max_lines=1 leaves no row for the hint."""
        control = ThinkingBoxControl(lambda: _numbered(6), max_collapsed_lines=1)
        assert _rendered(control, 40, 1) == ["line 5"]

    def test_exactly_max_lines_fits_without_hint(self):
        content = _numbered(5)
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5)
        assert _rendered(control, 40, 5) == [f"line {i}" for i in range(5)]
        assert control.can_toggle_expanded is False

    def test_one_line_over_max_can_expand(self):
        content = _numbered(6)
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5)
        assert control.can_toggle_expanded is True

    def test_fits_by_rows_counting_wrapped_lines(self):
        """Ten 50-char lines at width 40 take two rows each: a 5-row box
        has 4 rows for content, i.e. the last two lines."""
        content = "".join(f"{i:02d}" + "x" * 48 + "\n" for i in range(10))
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5)
        rows = _rendered(control, 40, 5)
        assert rows[0].startswith("+8 earlier lines")
        assert "".join(rows[1:]).startswith("08") and "09" in "".join(rows[1:])

    def test_a_line_longer_than_the_box_shows_its_end(self):
        """A streamed paragraph longer than the box: its newest rows show,
        and the line, partly hidden, counts in the hint."""
        content = "intro\n" + _words(40)  # the paragraph: 4 rows at width 40
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=3)
        assert _rendered(control, 40, 3) == [
            "+2 earlier lines... ctrl-t to expand",
            _words(10, start=20) + " ",
            _words(10, start=30),
        ]

    @pytest.mark.parametrize(
        "content, content_format",
        [("abcd中ef中", "plain"), ("\x1b[31mabcd\x1b[0m中ef中", "ansi")],
    )
    def test_a_wide_character_that_does_not_fit_starts_the_next_row(
        self, content: str, content_format: str
    ):
        """As the window wraps it: 中 doesn't fit in the column left."""
        control = ThinkingBoxControl(
            lambda: content, max_collapsed_lines=2, content_format=content_format
        )
        assert control.get_line_count(width=5) == 3
        assert _rendered(control, 5, 2)[1:] == ["中"]

    @pytest.mark.parametrize(
        "text, width",
        [
            ("中a", 1),  # wider than the window: a row of its own, after an empty one
            ("ab中cd", 3),
            ("a\tb", 2),  # the tab is drawn as ^I
            ("abcdef", 4),
            ("中中中", 4),
        ],
    )
    def test_rows_are_the_rows_the_window_draws(self, text: str, width: int):
        assert _wrapped(text, width) == _drawn(text, width)

    def test_a_character_wider_than_the_box_ends(self):
        """It used to loop forever: 中 left the row wider than the box, and
        the next fragment then took nothing from its text, again and again.
        (Run in a thread, so a regression fails here instead of hanging.)"""
        control = ThinkingBoxControl(lambda: "\x1b[31m中\x1b[0ma", content_format="ansi")
        counted: list[int] = []
        thread = threading.Thread(
            target=lambda: counted.append(control.get_line_count(width=1)), daemon=True
        )
        thread.start()
        thread.join(timeout=2)
        assert counted == [3]

    def test_a_tab_takes_the_two_columns_it_is_drawn_in(self):
        """The window draws a tab as ^I."""
        control = ThinkingBoxControl(lambda: "x" * 39 + "\t", max_collapsed_lines=5)
        assert control.get_line_count(width=40) == 2

    def test_a_hint_wrapping_in_a_narrow_box_takes_its_rows(self):
        """At 20 columns the hint wraps onto two rows: the newest line
        gets the one left, not a row the box doesn't have."""
        control = ThinkingBoxControl(lambda: _numbered(10), max_collapsed_lines=3)
        assert _rendered(control, 20, 3) == ["+9 earlier lines... ctrl-t to expand", "line 9"]

    def test_with_no_row_left_for_content_the_hint_goes(self):
        """As in a one-row box: the newest lines rather than only a hint."""
        control = ThinkingBoxControl(lambda: _numbered(10), max_collapsed_lines=2)
        assert _rendered(control, 20, 2) == ["line 8", "line 9"]

    def test_squeezed_box_fits_the_rows_it_gets(self):
        content = _numbered(60)
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5)
        assert _rendered(control, 40, 3) == [
            "+58 earlier lines... ctrl-t to expand", "line 58", "line 59",
        ]

    def test_collapsed_box_keeps_its_cap_in_a_taller_window(self):
        content = _numbered(60)
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5)
        assert _rendered(control, 40, 30) == [
            "+56 earlier lines... ctrl-t to expand",
            "line 56", "line 57", "line 58", "line 59",
        ]

    def test_expanded_fits_given_height_and_offers_collapse(self):
        content = _numbered(60)
        control = _expanded_control(content)
        rows = _rendered(control, 40, 8)
        assert rows[0] == "+53 earlier lines... ctrl-t to collapse"
        assert rows[1:] == [f"line {i}" for i in range(53, 60)]

    def test_expanded_with_room_shows_everything(self):
        content = _numbered(12)
        control = _expanded_control(content)
        assert _rendered(control, 40, 30) == [f"line {i}" for i in range(12)]

    def test_ansi_style_carries_across_the_cut(self):
        """A color opened before the cut still applies to the lines shown."""
        from prompt_toolkit.formatted_text import fragment_list_to_text

        content = "\x1b[31m" + _numbered(10) + "\x1b[0m"
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5, content_format="ansi")
        ui = control.create_content(40, 5)
        last = ui.get_line(ui.line_count - 1)
        assert fragment_list_to_text(last) == "line 9"
        assert all("ansired" in style for style, text in last if text)


class TestOverflowHead:
    """overflow="head" keeps the first lines, hint at the bottom."""

    def test_collapsed_shows_first_lines_over_hint(self):
        content = _numbered(60)
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5, overflow="head")
        assert _rendered(control, 40, 5) == [
            "line 0", "line 1", "line 2", "line 3",
            "+56 lines... ctrl-t to expand",
        ]

    def test_a_line_longer_than_the_box_shows_its_start_over_the_hint(self):
        content = _words(40) + "\nnext\n"
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=3, overflow="head")
        assert _rendered(control, 40, 3) == [
            _words(10) + " ",
            _words(10, start=10) + " ",
            "+2 lines... ctrl-t to expand",
        ]

    def test_singular_hint_and_wrap_aware_fit(self):
        """Four short lines fill the 4 content rows; the long last line is
        the single hidden one."""
        content = "a\nb\nc\nd\n" + "x" * 45 + "\n"
        control = ThinkingBoxControl(lambda: content, max_collapsed_lines=5, overflow="head")
        assert _rendered(control, 40, 5) == ["a", "b", "c", "d", "+1 line... ctrl-t to expand"]
