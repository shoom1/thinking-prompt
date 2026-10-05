"""Tests for dialog rows and the one-cursor navigator (thinking_prompt.rows)."""
from __future__ import annotations

from unittest.mock import MagicMock

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.widgets import TextArea

from thinking_prompt.rows import ActionRow, OptionGroup, RowNavigator


def _text(control) -> str:
    return "".join(t for _, t in control.create_content(60, 1).get_line(0))


def _styles(control) -> list[str]:
    return [s for s, _ in control.create_content(60, 1).get_line(0)]


def _app(layout: Layout) -> Application:
    return Application(layout=layout, input=DummyInput(), output=DummyOutput())


def _binding(kb: KeyBindings, key):
    (binding,) = kb.get_bindings_for_keys((key,))
    return binding


def _actions(*names: str, ran: list | None = None) -> list[ActionRow]:
    ran = ran if ran is not None else []
    return [ActionRow(i, n, lambda n=n: ran.append(n)) for i, n in enumerate(names, start=1)]


class TestActionRow:
    def test_renders_number_and_text_with_the_marker_when_focused(self):
        a, b = _actions("Delete", "Keep")
        layout = Layout(HSplit([a.window, b.window]))
        with set_app(_app(layout)):
            layout.focus(a.window)
            assert _text(a) == "❯ 1. Delete"
            assert _text(b) == "  2. Keep"
            assert _styles(a) == ["class:dialog-choice-selected"]
            assert _styles(b) == ["class:dialog-choice"]

    def test_button_style_is_appended(self):
        row = ActionRow(1, "Danger", lambda: None, style="class:danger")
        assert _styles(row) == ["class:dialog-choice class:danger"]

    def test_enter_runs_the_action(self):
        ran: list[str] = []
        (row,) = _actions("Go", ran=ran)
        _binding(row.get_key_bindings(), Keys.ControlM).handler(MagicMock())
        assert ran == ["Go"]

    def test_numbers_are_padded_to_the_given_width(self):
        nine = ActionRow(9, "nine", lambda: None, number_width=2)
        ten = ActionRow(10, "ten", lambda: None, number_width=2)
        assert (_text(nine), _text(ten)) == ("   9. nine", "  10. ten")

    def test_hides_the_terminal_cursor(self):
        """The ❯ marker shows the row: no terminal cursor drawn over it."""
        (row,) = _actions("Go")
        assert row.create_content(60, 1).show_cursor is False


class TestOptionRows:
    def test_check_list_marks_and_toggles(self):
        group = OptionGroup(["search", "code"], multiple=True, selected=["code"])
        search, code = group.rows
        assert (_text(search), _text(code)) == ("  [ ] search", "  [x] code")
        _binding(search.get_key_bindings(), " ").handler(MagicMock())
        assert group.checked == ["search", "code"]
        _binding(code.get_key_bindings(), Keys.ControlM).handler(MagicMock())
        assert group.checked == ["search"]

    def test_radio_list_picks_one(self):
        group = OptionGroup(["fast", "careful"], multiple=False, selected=["fast"])
        fast, careful = group.rows
        assert (_text(fast), _text(careful)) == ("  (•) fast", "  ( ) careful")
        _binding(careful.get_key_bindings(), " ").handler(MagicMock())
        assert group.picked == "careful"
        assert group.checked == ["careful"]

    def test_unknown_options_are_ignored_and_a_radio_list_keeps_one(self):
        assert OptionGroup(["a", "b"], multiple=True, selected=["z", "b"]).checked == ["b"]
        assert OptionGroup(["a", "b"], multiple=False, selected=["b", "a"]).picked == "b"
        assert OptionGroup(["a", "b"], multiple=False).picked is None

    def test_select_replaces_the_selection(self):
        group = OptionGroup(["a", "b", "c"], multiple=True, selected=["a"])
        group.select(["c", "b"])
        assert group.checked == ["b", "c"]

    def test_indent_mark_style_and_hint(self):
        (row,) = OptionGroup(["a"], multiple=True, indent=2).rows
        assert _text(row) == "    [ ] a"
        assert "class:checkbox-mark" in _styles(row)
        assert row.hints == {"Space toggle"}

    def test_hides_the_terminal_cursor(self):
        (row,) = OptionGroup(["a"], multiple=False).rows
        assert row.create_content(60, 1).show_cursor is False


class TestRowNavigator:
    def test_moves_between_stops_and_stops_at_the_ends(self):
        rows = _actions("a", "b", "c")
        layout = Layout(HSplit([r.window for r in rows]))
        nav = RowNavigator(lambda: [r.window for r in rows])
        layout.focus(rows[0].window)
        nav.move(layout, -1)
        assert layout.has_focus(rows[0].window)
        for _ in range(3):
            nav.move(layout, 1)
        assert layout.has_focus(rows[2].window)
        assert nav.index(layout) == 2

    def test_arrows_and_digits_act_only_on_rows(self):
        rows = _actions("a", "b")
        field = TextArea()
        layout = Layout(HSplit([field, *(r.window for r in rows)]))
        kb = RowNavigator(lambda: [field.window, *(r.window for r in rows)], actions=rows).key_bindings()
        with set_app(_app(layout)):
            layout.focus(field)
            assert not _binding(kb, Keys.Up).filter()
            assert not _binding(kb, "1").filter()
            layout.focus(rows[0].window)
            assert _binding(kb, Keys.Down).filter()
            assert _binding(kb, "1").filter()

    def test_nothing_moves_while_editing(self):
        editing = [True]
        rows = _actions("a", "b")
        layout = Layout(HSplit([r.window for r in rows]))
        kb = RowNavigator(
            lambda: [r.window for r in rows], is_editing=lambda: editing[0], tab=True
        ).key_bindings()
        with set_app(_app(layout)):
            layout.focus(rows[0].window)
            for key in (Keys.Up, Keys.Down, Keys.ControlI, Keys.BackTab):
                assert not _binding(kb, key).filter()
            editing[0] = False
            assert _binding(kb, Keys.Down).filter()

    def test_tab_only_when_enabled_and_it_leaves_a_non_row_body(self):
        rows = _actions("a", "b")
        assert RowNavigator(lambda: []).key_bindings().get_bindings_for_keys((Keys.ControlI,)) == []
        field = TextArea()
        layout = Layout(HSplit([field, *(r.window for r in rows)]))
        kb = RowNavigator(lambda: [field.window, *(r.window for r in rows)], tab=True).key_bindings()
        with set_app(_app(layout)):
            layout.focus(field)
            tab = _binding(kb, Keys.ControlI)
            assert tab.filter()
            tab.handler(MagicMock(app=MagicMock(layout=layout)))
            assert layout.has_focus(rows[0].window)

    def test_digits_run_the_first_nine_actions(self):
        ran: list[str] = []
        actions = [ActionRow(i, f"a{i}", lambda i=i: ran.append(f"a{i}")) for i in range(1, 12)]
        kb = RowNavigator(lambda: [a.window for a in actions], actions=actions).key_bindings()
        _binding(kb, "3").handler(MagicMock())
        assert ran == ["a3"]
        assert kb.get_bindings_for_keys(("0",)) == []
