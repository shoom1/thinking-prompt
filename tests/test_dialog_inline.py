"""Tests for the inline presentation of dialogs (thinking_prompt.dialog_inline)."""
from __future__ import annotations

import asyncio

from prompt_toolkit.formatted_text import fragment_list_to_text, to_formatted_text
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import walk
from prompt_toolkit.widgets import TextArea

from thinking_prompt.dialog import ButtonConfig, Dialog
from thinking_prompt.dialog_inline import MAX_ROWS, _AtMost, build_inline
from thinking_prompt.rows import OptionGroup


def _texts(view) -> list[str]:
    """Text of every text window in the inline dialog, top to bottom."""
    out = []
    for c in walk(view.container):
        if isinstance(c, Window) and isinstance(c.content, FormattedTextControl):
            text = c.content.text
            out.append(fragment_list_to_text(to_formatted_text(text() if callable(text) else text)))
    return out


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
