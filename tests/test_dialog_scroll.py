"""Tests for dialog scrolling (thinking_prompt.dialog_scroll)."""
from __future__ import annotations

import pytest
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput

from thinking_prompt.dialog_scroll import (
    TERMINAL_BUFFER_ROWS,
    AtMost,
    ScrollRegion,
    dialog_cap,
    focusable_windows,
)


def _lines(count: int) -> Window:
    """A text window of ``count`` lines: "line 00", "line 01", ..."""
    return Window(FormattedTextControl("\n".join(f"line {i:02}" for i in range(count))))


def _draw(region: ScrollRegion, height: int) -> list[str]:
    """Draw ``region`` ``height`` rows tall with the focus outside it (as on
    a dialog's buttons); return its rows' text."""
    outside = Window(FormattedTextControl("ok", focusable=True))
    layout = Layout(HSplit([region, outside]), focused_element=outside)
    app = Application(layout=layout, input=DummyInput(), output=DummyOutput())
    screen = Screen()
    with set_app(app):
        region.write_to_screen(
            screen, MouseHandlers(), WritePosition(0, 0, 40, height), "", True, None
        )
    return [
        "".join(screen.data_buffer[y][x].char for x in range(40)).strip()
        for y in range(height)
    ]


class TestDialogCap:
    def test_leaves_the_prompts_rows_free(self):
        assert dialog_cap(None, 24) == 24 - TERMINAL_BUFFER_ROWS

    def test_max_height_caps_it_further(self):
        assert dialog_cap(12, 24) == 12
        assert dialog_cap(30, 24) == 20

    def test_is_at_least_one_row(self):
        assert dialog_cap(None, 3) == 1


class TestAtMost:
    def test_caps_the_preferred_height(self):
        tall = HSplit([Window(height=1) for _ in range(30)])
        short = HSplit([Window(height=1) for _ in range(3)])
        assert AtMost(tall, 12).preferred_height(80, 100).preferred == 12
        assert AtMost(short, 12).preferred_height(80, 100).preferred == 3

    def test_max_is_also_capped_so_hsplit_cannot_pad_with_blank_rows(self):
        """max must equal the capped preferred, not the cap: otherwise a
        parent HSplit with spare height distributes it to this container,
        padding it with blank rows past its actual content."""
        tall = HSplit([Window(height=1) for _ in range(30)])
        short = HSplit([Window(height=1) for _ in range(3)])
        assert AtMost(tall, 12).preferred_height(80, 100).max == 12
        assert AtMost(short, 12).preferred_height(80, 100).max == 3

    def test_without_a_cap_it_takes_its_full_height_and_no_more(self):
        tall = HSplit([Window(height=1) for _ in range(30)])
        extending = Window(FormattedTextControl("one\ntwo"))  # max is unbounded on its own
        tall_dim = AtMost(tall).preferred_height(80, 100)
        extending_dim = AtMost(extending).preferred_height(80, 100)
        assert (tall_dim.preferred, tall_dim.max) == (30, 30)
        assert (extending_dim.preferred, extending_dim.max) == (2, 2)

    def test_a_cap_function_gets_the_width(self):
        tall = HSplit([Window(height=1) for _ in range(30)])
        assert AtMost(tall, lambda width: width // 10).preferred_height(80, 100).preferred == 8


class TestScrollRegion:
    """With nothing inside focused (a text body), it scrolls by keys."""

    def test_text_that_fits_neither_overflows_nor_scrolls(self):
        region = ScrollRegion(_lines(5))
        _draw(region, 10)
        assert not region.overflows
        region.scroll(3)
        assert region.vertical_scroll == 0

    def test_text_scrolls_by_lines_and_pages(self):
        region = ScrollRegion(_lines(30))
        _draw(region, 10)
        assert region.overflows
        region.scroll(3)
        assert region.vertical_scroll == 3
        region.page(1)
        assert region.vertical_scroll == 3 + 9  # a page: the visible rows less one
        region.page(-5)
        assert region.vertical_scroll == 0

    def test_scrolling_stops_at_the_last_line(self):
        region = ScrollRegion(_lines(30))
        _draw(region, 10)
        region.scroll(100)
        assert region.vertical_scroll == 20
        assert _draw(region, 10)[-1] == "line 29"

    def test_the_scrolled_rows_are_drawn(self):
        region = ScrollRegion(_lines(30))
        _draw(region, 10)
        region.scroll(5)
        assert _draw(region, 10)[0] == "line 05"

    def test_more_rows_pull_the_scroll_back(self):
        """A taller terminal shows more lines, not blank rows past the end."""
        region = ScrollRegion(_lines(30))
        _draw(region, 10)
        region.scroll(100)
        rows = _draw(region, 25)
        assert region.vertical_scroll == 5
        assert rows[-1] == "line 29"

    @pytest.mark.parametrize(
        "lines,scrollbar,shown", [(30, True, True), (5, True, False), (30, False, False)]
    )
    def test_the_scrollbar_shows_only_while_the_text_overflows(self, lines, scrollbar, shown):
        region = ScrollRegion(_lines(lines), scrollbar=scrollbar)
        _draw(region, 10)
        assert region.show_scrollbar() is shown

    def test_is_at_least_one_row(self):
        dim = ScrollRegion(_lines(30)).preferred_height(40, 100)
        assert (dim.min, dim.preferred) == (1, 30)


class TestFocusableWindows:
    def test_lists_the_windows_that_take_focus(self):
        a = Window(FormattedTextControl("a", focusable=True))
        b = Window(FormattedTextControl("b"))
        assert focusable_windows(HSplit([a, b])) == [a]
