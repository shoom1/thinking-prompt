"""Tests for the inline presentation of dialogs (thinking_prompt.dialog_inline)."""
from __future__ import annotations

import asyncio

import pytest
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
from thinking_prompt.dialog_inline import MAX_ROWS, build_inline
from thinking_prompt.fields import RadioField
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
    """The inline dialog's scrolling region of cursor stops and actions."""
    (pane,) = [
        c for c in walk(view.container)
        if isinstance(c, ScrollablePane) and c is not view.text_region
    ]
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
        radio = Dialog("T", fields=[RadioField("m", "Mode", options=["a", "b"])], placement="inline")
        radio._placement = "inline"  # as show_dialog() resolves it
        assert build_inline(radio).hint == "↑↓ navigate · Enter select · Esc cancel"

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


class TestScrollingRegion:
    """Cursor stops and actions scroll in one region (within MAX_ROWS
    without max_height); a body without cursor stops (text) is drawn above
    it, in a region of its own (TestTextRegion)."""

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

    def test_regrown_on_the_first_stop_the_region_shows_its_top_again(self):
        """A shorter terminal scrolls the text above the first stop off;
        with rows back, it shows again, though the cursor never moved."""
        group = OptionGroup([f"o{i}" for i in range(6)], multiple=True)
        body = HSplit([Label("line one\nline two"), *(r.window for r in group.rows)])
        view = build_inline(Dialog("T", body, [ButtonConfig("OK")]))
        pane = _region(view)
        layout = Layout(view.container)
        with set_app(_app(layout)):
            layout.focus(group.rows[0].window)
            _render(pane, 8)
            _render(pane, 2)  # shrunk: just the first option and the row above
            assert pane.vertical_scroll > 0
            screen = _render(pane, 5)  # grown back, though not in full
        assert pane.vertical_scroll == 0
        assert _rows(screen, 3) == ["line one", "line two", "❯ [ ] o0"]

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


def _rows(screen: Screen, height: int) -> list[str]:
    return ["".join(screen.data_buffer[y][x].char for x in range(40)).strip() for y in range(height)]


LONG = "\n".join(f"line {i}" for i in range(30))


class TestTextRegion:
    def test_a_text_body_scrolls_in_its_own_region(self):
        view = build_inline(_yes_no())
        assert view.text_region is not None
        (body,) = [w for w, text in _text_windows(view.container) if text == "This can't be undone."]
        assert body in list(walk(view.text_region))
        assert body not in list(walk(_region(view)))

    def test_a_body_with_stops_has_no_text_region(self):
        group = OptionGroup(["a", "b"], multiple=True)
        view = build_inline(Dialog("T", HSplit([r.window for r in group.rows]), [ButtonConfig("OK")]))
        assert view.text_region is None

    @pytest.mark.parametrize("text,offered", [(LONG, True), ("short", False)])
    def test_the_hint_offers_scrolling_only_while_the_text_overflows(self, text, offered):
        view = build_inline(Dialog("T", text, [ButtonConfig("OK")]))
        layout = Layout(view.container)
        with set_app(_app(layout)):
            layout.focus(view.actions[0].window)
            _render(view.container, 10)
        assert ("PgUp/PgDn scroll" in view.hint) is offered

    def test_the_scroll_keys_sit_between_navigation_and_selection_in_the_hint(self):
        view = build_inline(Dialog("T", LONG, [ButtonConfig("A"), ButtonConfig("B")]))
        layout = Layout(view.container)
        with set_app(_app(layout)):
            layout.focus(view.actions[0].window)
            _render(view.container, 10)
        assert view.hint == "↑↓ navigate · PgUp/PgDn scroll · Enter select · Esc cancel"


class TestHintWrapping:
    """The hint breaks between its entries, never inside one."""

    @staticmethod
    def _hint_window(view) -> Window:
        (window,) = [w for w, text in _text_windows(view.container) if text == view.hint]
        return window

    @staticmethod
    def _lines(window: Window, width: int) -> list[str]:
        content = window.content.create_content(width, None)
        return [fragment_list_to_text(content.get_line(i)) for i in range(content.line_count)]

    def _view(self):
        group = OptionGroup(["a", "b"], multiple=True)
        return build_inline(Dialog("T", HSplit([r.window for r in group.rows]), [ButtonConfig("OK")]))

    def test_the_hint_breaks_between_entries(self):
        window = self._hint_window(self._view())
        assert self._lines(window, 30) == ["↑↓ navigate · Space toggle", "Enter select · Esc cancel"]
        assert window.preferred_height(30, 100).preferred == 2

    def test_the_hint_is_one_line_when_it_fits(self):
        view = self._view()
        assert self._lines(self._hint_window(view), 80) == [view.hint]

    def test_an_entry_wider_than_the_row_gets_a_line_of_its_own(self):
        window = self._hint_window(self._view())
        assert self._lines(window, 11) == ["↑↓ navigate", "Space toggle", "Enter select", "Esc cancel"]


class TestInlineSizes:
    """The rows share the cap: fixed rows, then the actions, then a text body."""

    @staticmethod
    def _height(view) -> int:
        # 80 columns: the hint line stays one row (at 40 it nearly wraps).
        return view.container.preferred_height(80, 100).preferred

    def test_with_max_height_the_whole_dialog_fits(self):
        view = build_inline(Dialog("T", LONG, [ButtonConfig("A"), ButtonConfig("B")], max_height=10))
        assert self._height(view) == 10

    def test_without_max_height_actions_keep_to_max_rows(self):
        view = build_inline(Dialog("T", "", [ButtonConfig(f"a{i}") for i in range(30)]))
        assert self._height(view) == 1 + MAX_ROWS + 2  # title, the region, blank, hint

    def test_max_height_lifts_the_max_rows_limit(self):
        view = build_inline(Dialog("T", "", [ButtonConfig(f"a{i}") for i in range(30)], max_height=30))
        assert self._height(view) == 30

    def test_actions_get_rows_before_the_text(self):
        view = build_inline(Dialog(
            "T", LONG, [ButtonConfig("A"), ButtonConfig("B"), ButtonConfig("C")], max_height=10
        ))
        layout = Layout(view.container)
        with set_app(_app(layout)):
            layout.focus(view.actions[0].window)
            rows = _rows(_render(view.container, 10), 10)
        assert [r for r in rows if r.endswith(("1. A", "2. B", "3. C"))] == ["❯ 1. A", "2. B", "3. C"]
