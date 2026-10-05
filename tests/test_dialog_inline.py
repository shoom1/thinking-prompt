"""Tests for the inline presentation of dialogs (thinking_prompt.dialog_inline)."""
from __future__ import annotations

import asyncio

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.formatted_text import fragment_list_to_text, to_formatted_text
from prompt_toolkit.input import DummyInput
from prompt_toolkit.layout import HSplit, Layout, ScrollablePane, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import walk
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.widgets import Label, TextArea

from thinking_prompt.dialog import ButtonConfig, Dialog
from thinking_prompt.dialog_inline import MAX_ROWS, _AtMost, build_inline
from thinking_prompt.rows import OptionGroup


def _text_windows(container) -> list[tuple[Window, str]]:
    """Every text window under ``container`` with its text, top to bottom."""
    out = []
    for c in walk(container):
        if isinstance(c, Window) and isinstance(c.content, FormattedTextControl):
            text = c.content.text
            out.append((c, fragment_list_to_text(to_formatted_text(text() if callable(text) else text))))
    return out


def _texts(view) -> list[str]:
    """Text of every text window in the inline dialog, top to bottom."""
    return [text for _, text in _text_windows(view.container)]


def _region(view) -> ScrollablePane:
    """The inline dialog's scrolling region."""
    (pane,) = [c for c in walk(view.container) if isinstance(c, ScrollablePane)]
    return pane


def _app(layout: Layout) -> Application:
    return Application(layout=layout, input=DummyInput(), output=DummyOutput())


def _render(container, height: int) -> Screen:
    screen = Screen()
    container.write_to_screen(screen, MouseHandlers(), WritePosition(0, 0, 40, height), "", True, None)
    return screen


def _yes_no(**kwargs) -> Dialog:
    return Dialog(
        "Delete 3 files?",
        "This can't be undone.",
        [ButtonConfig("Delete", result=True), ButtonConfig("Keep", result=False)],
        **kwargs,
    )


class TestBuildInline:
    def test_simple_dialog(self):
        view = build_inline(_yes_no())
        assert [(a.number, a.text) for a in view.actions] == [(1, "Delete"), (2, "Keep")]
        assert _texts(view) == [
            "Delete 3 files?",
            "This can't be undone.",
            "↑↓ navigate · Enter select · Esc cancel",
        ]
        assert view.focus is view.actions[0].window

    def test_empty_title_and_body_are_left_out(self):
        view = build_inline(Dialog(buttons=[ButtonConfig("OK")]))
        assert _texts(view) == ["Enter select · Esc cancel"]

    def test_hint_lists_only_the_keys_that_apply(self):
        not_escapable = Dialog("T", "B", [ButtonConfig("OK")], escapable=False)
        assert build_inline(not_escapable).hint == "Enter select"
        group = OptionGroup(["a", "b"], multiple=True)
        with_list = Dialog("T", HSplit([r.window for r in group.rows]), [ButtonConfig("OK")])
        assert build_inline(with_list).hint == "↑↓ navigate · Space toggle · Enter select · Esc cancel"

    def test_a_focused_button_starts_the_cursor(self):
        view = build_inline(Dialog("T", "B", [ButtonConfig("A"), ButtonConfig("B", focused=True)]))
        assert view.focus is view.actions[1].window

    def test_the_cursor_starts_in_a_focusable_body(self):
        field = TextArea()
        assert build_inline(Dialog("T", field, [ButtonConfig("OK")])).focus is field.window

    def test_nothing_focusable_means_no_focus(self):
        assert build_inline(Dialog("T", "just text")).focus is None

    def test_action_labels_line_up_past_nine_actions(self):
        view = build_inline(Dialog("T", "", [ButtonConfig(f"a{i}") for i in range(1, 12)]))
        texts = ["".join(t for _, t in a.create_content(60, 1).get_line(0)) for a in view.actions]
        assert (texts[0], texts[8], texts[9]) == ("   1. a1", "   9. a9", "  10. a10")
        assert len({text.index(".") for text in texts}) == 1

    def test_actions_run_the_dialog_click_logic_with_the_button_style(self):
        loop = asyncio.new_event_loop()
        try:
            dialog = Dialog("T", "B", [ButtonConfig("A", result="a", style="class:danger")])
            dialog._result_future = loop.create_future()
            view = build_inline(dialog)
            assert view.actions[0].style == "class:danger"
            view.actions[0].on_select()
            assert dialog._result_future.result() == "a"
        finally:
            loop.close()


class TestAtMost:
    def test_caps_the_preferred_height(self):
        tall = HSplit([Window(height=1) for _ in range(30)])
        short = HSplit([Window(height=1) for _ in range(3)])
        tall_dim = _AtMost(tall, MAX_ROWS).preferred_height(80, 100)
        short_dim = _AtMost(short, MAX_ROWS).preferred_height(80, 100)
        assert tall_dim.preferred == MAX_ROWS
        assert short_dim.preferred == 3

    def test_max_is_also_capped_so_hsplit_cannot_pad_with_blank_rows(self):
        """max must equal the capped preferred, not self.rows: otherwise a
        parent HSplit with spare height distributes it to this container,
        padding it with blank rows past its actual content."""
        tall = HSplit([Window(height=1) for _ in range(30)])
        short = HSplit([Window(height=1) for _ in range(3)])
        assert _AtMost(tall, MAX_ROWS).preferred_height(80, 100).max == MAX_ROWS
        assert _AtMost(short, MAX_ROWS).preferred_height(80, 100).max == 3

    def test_without_a_cap_it_takes_its_full_height_and_no_more(self):
        """A text body drawn above the scrolling region: in full, never padded."""
        tall = HSplit([Window(height=1) for _ in range(30)])
        extending = Window(FormattedTextControl("one\ntwo"))  # max is unbounded on its own
        tall_dim = _AtMost(tall).preferred_height(80, 100)
        extending_dim = _AtMost(extending).preferred_height(80, 100)
        assert (tall_dim.preferred, tall_dim.max) == (30, 30)
        assert (extending_dim.preferred, extending_dim.max) == (2, 2)


class TestScrollingRegion:
    """Rows and actions scroll within MAX_ROWS; a body without cursor stops
    (text) is drawn in full above them."""

    def test_a_text_body_is_drawn_above_the_scrolling_region(self):
        view = build_inline(_yes_no())
        region = list(walk(_region(view)))
        (body,) = [w for w, text in _text_windows(view.container) if text == "This can't be undone."]
        assert body not in region
        assert all(action.window in region for action in view.actions)

    def test_a_body_with_nothing_focusable_is_drawn_above_too(self):
        body = HSplit([Label("one"), Label("two")])
        view = build_inline(Dialog("T", body, [ButtonConfig("OK")]))
        region = list(walk(_region(view)))
        assert body not in region and body in list(walk(view.container))

    def test_a_body_with_stops_scrolls_with_the_actions(self):
        group = OptionGroup(["a", "b"], multiple=True)
        view = build_inline(Dialog("T", HSplit([r.window for r in group.rows]), [ButtonConfig("OK")]))
        region = list(walk(_region(view)))
        assert all(row.window in region for row in group.rows)
        assert view.actions[0].window in region

    def test_the_first_stop_scrolls_the_region_back_to_its_top(self):
        """Back on the first option, the text above it in the region shows again."""
        group = OptionGroup([f"o{i}" for i in range(6)], multiple=True)
        body = HSplit([Label("line one\nline two"), *(r.window for r in group.rows)])
        view = build_inline(Dialog("T", body, [ButtonConfig("OK")]))
        pane = _region(view)
        layout = Layout(view.container)
        with set_app(_app(layout)):
            layout.focus(group.rows[0].window)
            pane.vertical_scroll = 4  # as left by moving down the list and back
            _render(pane, 4)
            assert pane.vertical_scroll == 0
            # Further down the list, the region keeps its scroll.
            layout.focus(group.rows[5].window)
            _render(pane, 4)
            assert pane.vertical_scroll > 0

    async def test_a_tall_first_stop_keeps_the_scroll_while_its_cursor_moves(self):
        """The region goes back to its top when the cursor arrives at the
        first stop, not on every redraw: in a tall text field there, the
        text cursor isn't pinned to the region's bottom row. (Async: the
        text field loads its history in a task while it renders.)"""
        field = TextArea(text="\n".join(f"line {i}" for i in range(1, 31)))
        field.buffer.cursor_position = field.document.translate_row_col_to_index(19, 0)
        view = build_inline(Dialog("T", field, [ButtonConfig("OK")]))
        pane = _region(view)
        layout = Layout(view.container)
        with set_app(_app(layout)):
            layout.focus(field)
            _render(pane, MAX_ROWS)
            opened = pane.vertical_scroll
            assert opened == 19 - (MAX_ROWS - 1)  # line 20 on the bottom row
            field.buffer.cursor_up(count=3)
            _render(pane, MAX_ROWS)
            assert pane.vertical_scroll == opened  # line 17: three rows above the bottom

    def test_a_one_row_region_shows_the_cursor_row(self):
        """Squeezed to one row (a short terminal), the region shows the
        highlighted action, not the row above it."""
        view = build_inline(Dialog("T", "", [ButtonConfig("A"), ButtonConfig("B"), ButtonConfig("C")]))
        pane = _region(view)
        layout = Layout(view.container)
        with set_app(_app(layout)):
            layout.focus(view.actions[1].window)
            screen = _render(pane, 1)
        assert "".join(screen.data_buffer[0][x].char for x in range(40)).strip() == "❯ 2. B"
