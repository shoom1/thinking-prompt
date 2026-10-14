"""Tests for the box presentation of dialogs (thinking_prompt.dialog_box)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.layout import FloatContainer, FormattedTextControl, HSplit, Window, to_container
from prompt_toolkit.layout.layout import walk
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.widgets import Button, Label, RadioList

from thinking_prompt.dialog import ButtonConfig, Dialog
from thinking_prompt.dialog_box import BoxPresenter, build_box
from thinking_prompt.dialog_scroll import TERMINAL_BUFFER_ROWS, ScrollRegion
from thinking_prompt.rows import OptionGroup


def _resolved_style(window: Window) -> str:
    """A Button window's style, resolved inside an app session (get_app())."""
    with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
        style = window.style
        return style() if callable(style) else style


class TestBuildBox:
    def test_builds_the_widget_with_one_button_per_config(self):
        view = build_box(Dialog("T", Label("Body"), [ButtonConfig("OK"), ButtonConfig("Cancel")]))
        assert view.widget is not None
        assert all(isinstance(b, Button) for b in view.buttons)
        assert [b.text for b in view.buttons] == ["OK", "Cancel"]

    def test_first_focused_button_is_the_initial_focus(self):
        view = build_box(Dialog("T", "B", [
            ButtonConfig("One", result=1),
            ButtonConfig("Two", result=2, focused=True),
            ButtonConfig("Three", result=3, focused=True),
        ]))
        assert view.focused_button is view.buttons[1]
        assert view.initial_focus is view.buttons[1].window

    def test_no_focused_flag_means_no_initial_focus(self):
        view = build_box(Dialog("T", "B", [ButtonConfig("One"), ButtonConfig("Two")]))
        assert view.focused_button is None
        assert view.initial_focus is None

    def test_a_text_body_is_the_text_region(self):
        view = build_box(Dialog("T", "Just text", [ButtonConfig("OK")]))
        regions = [c for c in walk(to_container(view.widget)) if isinstance(c, ScrollRegion)]
        assert len(regions) == 1
        assert view.text_region is regions[0]

    def test_a_body_with_a_cursor_stop_has_no_text_region(self):
        body = Window(FormattedTextControl("pick", focusable=True))
        view = build_box(Dialog("T", body, [ButtonConfig("OK")]))
        assert view.text_region is None

    def test_a_radio_list_body_has_no_text_region(self):
        view = build_box(Dialog("T", RadioList([("a", "A"), ("b", "B")]), [ButtonConfig("OK")]))
        assert view.text_region is None

    def test_button_style_is_added_to_the_button_window(self):
        view = build_box(Dialog("T", "B", [ButtonConfig("Danger", result=1, style="class:danger")]))
        assert "class:danger" in _resolved_style(view.buttons[0].window)

    def test_focused_and_style_apply_in_subclass_dialogs(self):
        class Styled(Dialog):
            def get_buttons(self):
                return [ButtonConfig("One"), ButtonConfig("Two", focused=True, style="class:danger")]

        view = build_box(Styled())
        assert view.focused_button is view.buttons[1]
        assert "class:danger" in _resolved_style(view.buttons[1].window)

    def test_a_button_runs_the_dialog_click_logic(self):
        loop = asyncio.new_event_loop()
        try:
            dialog = Dialog("T", "B", [ButtonConfig("A", result="a")])
            dialog._result_future = loop.create_future()
            build_box(dialog).buttons[0].handler()
            assert dialog._result_future.result() == "a"
        finally:
            loop.close()

    def test_tuple_buttons_raise_with_migration_hint(self):
        class Old(Dialog):
            def get_buttons(self):
                return [("OK", lambda: None)]

        with pytest.raises(TypeError, match=r"Use ButtonConfig\(label, handler=\.\.\.\)"):
            build_box(Old())

    def test_the_body_scrolls_in_a_region(self):
        view = build_box(Dialog("T", "B", [ButtonConfig("OK")]))
        assert any(isinstance(c, ScrollRegion) for c in walk(to_container(view.widget)))

    def test_a_list_that_scrolls_itself_is_not_in_a_region(self):
        body = HSplit([Label("Pick:"), RadioList([("a", "A"), ("b", "B")])])
        view = build_box(Dialog("T", body, [ButtonConfig("OK")]))
        assert not any(isinstance(c, ScrollRegion) for c in walk(to_container(view.widget)))

    def test_a_body_with_several_stops_scrolls_in_a_region(self):
        group = OptionGroup(["a", "b"], multiple=True)
        view = build_box(Dialog("T", HSplit([r.window for r in group.rows]), [ButtonConfig("OK")]))
        assert any(isinstance(c, ScrollRegion) for c in walk(to_container(view.widget)))

    def test_the_view_keeps_the_max_height(self):
        assert build_box(Dialog("T", "B", [ButtonConfig("OK")], max_height=7)).max_height == 7


class TestBoxPresenter:
    @staticmethod
    def _presenter() -> BoxPresenter:
        session = MagicMock()
        session.app.layout.container = Window()
        return BoxPresenter(session)

    def test_install_wraps_the_layout_once(self):
        presenter = self._presenter()
        presenter.install()
        presenter.install()
        root = presenter._session.app.layout.container
        assert isinstance(root, FloatContainer)
        assert not isinstance(root.content, FloatContainer)

    def test_a_width_never_makes_the_box_narrower_than_its_buttons(self):
        """Two 12-column buttons, a column between them, and the frame."""
        view = build_box(Dialog("T", "B", [ButtonConfig("Delete"), ButtonConfig("Cancel")], width=14))
        assert to_container(view.widget).preferred_width(80).preferred == 12 + 1 + 12 + 2
        wide = build_box(Dialog("T", "B", [ButtonConfig("OK")], width=40))
        assert to_container(wide.widget).preferred_width(80).preferred == 40

    @staticmethod
    def _long(**kwargs) -> Dialog:
        return Dialog("T", "\n".join(f"line {i}" for i in range(30)), [ButtonConfig("OK")], **kwargs)

    def test_open_sets_the_view_and_close_clears_it(self):
        presenter = self._presenter()
        view = presenter.open(Dialog("T", "B", [ButtonConfig("OK")]))
        assert presenter.view is view
        presenter.close()
        assert presenter.view is None
        assert presenter.rows(80, 24) == 0

    def test_rows_fit_the_terminal_less_the_prompts_rows(self):
        presenter = self._presenter()
        presenter.open(self._long())
        assert presenter.rows(80, 24) == 24 - TERMINAL_BUFFER_ROWS

    def test_rows_stop_at_max_height(self):
        presenter = self._presenter()
        presenter.open(self._long(max_height=12))
        assert presenter.rows(80, 24) == 12

    def test_a_short_dialog_takes_its_own_rows(self):
        presenter = self._presenter()
        view = presenter.open(Dialog("T", "B", [ButtonConfig("OK")], max_height=12))
        own = to_container(view.widget).preferred_height(80, 24).preferred
        assert own < 12
        assert presenter.rows(80, 24) == own

    def test_rows_never_go_below_what_the_frame_and_one_body_row_need(self):
        presenter = self._presenter()
        view = presenter.open(self._long(max_height=2))
        smallest = to_container(view.widget).preferred_height(80, 24).min
        assert presenter.rows(80, 24) == smallest > 2


class TestBoxTooSmall:
    @staticmethod
    def _open() -> tuple[BoxPresenter, Dialog]:
        session = MagicMock()
        session.app.layout.container = Window()
        presenter = BoxPresenter(session)
        dialog = Dialog("Delete files?", "Gone.", [ButtonConfig("Yes"), ButtonConfig("No")])
        presenter.open(dialog)
        return presenter, dialog

    def test_rows_are_the_notices_while_the_box_is_too_narrow(self):
        presenter, _ = self._open()
        box = presenter.rows(80, 24)
        assert box > 3
        # The notice, wrapped to 14 columns inside its frame: 4 lines and 2 borders.
        assert presenter.rows(16, 24) == 6
        assert presenter.rows(80, 24) == box

    def test_rows_are_the_notices_while_the_box_is_too_short(self):
        presenter, _ = self._open()
        assert presenter.rows(80, 3) == 3
        assert presenter.rows(80, 24) > 3

    def test_a_box_exactly_as_wide_as_it_needs_is_drawn(self):
        presenter, _ = self._open()
        needs_width, needs_rows = presenter._smallest(80, 24)
        assert needs_width == 27
        assert presenter._notice(needs_width, 24) is None
        assert presenter._notice(needs_width - 1, 24) is not None

    def test_a_box_exactly_as_tall_as_it_needs_is_drawn(self):
        presenter, _ = self._open()
        needs_width, needs_rows = presenter._smallest(80, 24)
        assert needs_rows == 4
        assert presenter._notice(80, needs_rows) is None
        assert presenter._notice(80, needs_rows - 1) is not None
        assert presenter.rows(80, needs_rows) == needs_rows
        assert presenter.rows(80, needs_rows - 1) == needs_rows - 1


class TestSmallestIsMeasuredOncePerDraw:
    @staticmethod
    def _counting() -> tuple[BoxPresenter, list]:
        session = MagicMock()
        session.app.layout.container = Window()
        presenter = BoxPresenter(session)
        presenter.open(Dialog("T", "B", [ButtonConfig("OK")]))
        calls: list = []
        measure = presenter._measure_smallest
        presenter._measure_smallest = lambda w, r: (calls.append((w, r)), measure(w, r))[1]
        return presenter, calls

    def test_repeated_questions_in_one_render_measure_once(self):
        presenter, calls = self._counting()
        for _ in range(3):
            presenter.rows(80, 24)
        assert calls == [(80, 24)]

    def test_another_terminal_size_measures_again(self):
        presenter, calls = self._counting()
        presenter.rows(80, 24)
        presenter.rows(40, 24)
        presenter.rows(40, 10)
        assert calls == [(80, 24), (40, 24), (40, 10)]
