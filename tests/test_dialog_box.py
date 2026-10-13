"""Tests for the box presentation of dialogs (thinking_prompt.dialog_box)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.layout import FloatContainer, Window, to_container
from prompt_toolkit.layout.layout import walk
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.widgets import Button, Label

from thinking_prompt.dialog import ButtonConfig, Dialog
from thinking_prompt.dialog_box import BoxPresenter, build_box
from thinking_prompt.dialog_scroll import TERMINAL_BUFFER_ROWS, ScrollRegion


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

    @pytest.mark.parametrize("top,expected", [(None, (None, None)), (2, (2, None)), (-1, (None, 1))])
    def test_open_positions_the_float_by_top(self, top, expected):
        presenter = self._presenter()
        presenter.open(Dialog("T", "B", [ButtonConfig("OK")], top=top))
        assert (presenter._float.top, presenter._float.bottom) == expected

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

    def test_the_float_takes_the_rows_in_the_apps_terminal(self):
        presenter = self._presenter()
        presenter.open(self._long())
        assert presenter._float.get_height() == presenter.rows(80, 40)  # DummyOutput: 80x40
