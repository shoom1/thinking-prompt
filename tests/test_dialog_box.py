"""Tests for the box presentation of dialogs (thinking_prompt.dialog_box)."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.layout import FloatContainer, Window
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.widgets import Button, Label

from thinking_prompt import dialog_box
from thinking_prompt.dialog import ButtonConfig, Dialog
from thinking_prompt.dialog_box import (
    MIN_DIALOG_HEIGHT,
    TERMINAL_BUFFER_ROWS,
    TERMINAL_TOO_SMALL,
    BoxPresenter,
    build_box,
)


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
        presenter.open(Dialog("T", "B", [ButtonConfig("OK")], top=top), None)
        assert (presenter._float.top, presenter._float.bottom) == expected

    def test_open_pins_the_float_height_and_close_clears_the_view(self):
        presenter = self._presenter()
        view = presenter.open(Dialog("T", "B", [ButtonConfig("OK")]), 15)
        assert presenter.view is view
        assert presenter._float.height == 15
        presenter.close()
        assert presenter.view is None

    def test_effective_height_clamps_to_the_terminal(self, monkeypatch):
        monkeypatch.setattr(dialog_box, "shutil", SimpleNamespace(get_terminal_size=lambda: os.terminal_size((80, 20))))
        presenter = self._presenter()
        assert presenter.effective_height(Dialog()) is None
        assert presenter.effective_height(Dialog(height=10)) == 10
        assert presenter.effective_height(Dialog(height=50)) == 20 - TERMINAL_BUFFER_ROWS

    def test_effective_height_reports_a_terminal_that_is_too_small(self, monkeypatch):
        rows = MIN_DIALOG_HEIGHT + TERMINAL_BUFFER_ROWS - 1
        monkeypatch.setattr(dialog_box, "shutil", SimpleNamespace(get_terminal_size=lambda: os.terminal_size((80, rows))))
        presenter = self._presenter()
        assert presenter.effective_height(Dialog(height=10)) is TERMINAL_TOO_SMALL
        presenter._session.add_error.assert_called_once()
