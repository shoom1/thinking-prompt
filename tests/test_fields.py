"""Form fields: the Field classes, their controls, and fields on a Dialog."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.widgets import Button, Label, TextArea

import thinking_prompt
from thinking_prompt import (
    ButtonConfig,
    CheckboxField,
    ChecklistField,
    Dialog,
    DropdownField,
    Field,
    RadioField,
    SelectField,
    TextField,
)
from thinking_prompt.dialog_scroll import focusable_windows

FIELD_NAMES = ("Field", "TextField", "CheckboxField", "SelectField", "DropdownField", "ChecklistField", "RadioField")


class TestFieldClasses:
    @pytest.mark.parametrize("make", [
        lambda: TextField("k", "L"),
        lambda: CheckboxField("k", "L"),
        lambda: SelectField("k", "L", options=["a"]),
        lambda: DropdownField("k", "L", options=["a"]),
        lambda: ChecklistField("k", "L", options=["a"]),
        lambda: RadioField("k", "L", options=["a"]),
    ])
    def test_fields_are_frozen(self, make):
        field = make()
        assert isinstance(field, Field)
        with pytest.raises(dataclasses.FrozenInstanceError):
            field.label = "other"

    def test_defaults(self):
        assert TextField("k", "L") == TextField(
            "k", "L", description="", default="", password=False, edit_width=15
        )
        assert CheckboxField("k", "L").default is False
        assert (DropdownField("k", "L").height, DropdownField("k", "L").width) == (4, 15)
        assert DropdownField("k", "L").max_width is None
        assert ChecklistField("k", "L").default == ()
        assert RadioField("k", "L").default is None
        assert SelectField("k", "L").default is None

    def test_exported_instead_of_the_settings_items(self):
        for name in FIELD_NAMES:
            assert name in thinking_prompt.__all__
        for name in ("SettingsItem", "InlineSelectItem", "DropdownItem", "CheckboxItem",
                     "TextItem", "ChecklistItem", "RadioItem"):
            assert not hasattr(thinking_prompt, name)
            assert name not in thinking_prompt.__all__


def _shown(dialog, placement="box"):
    """``dialog``'s content and start, as a presenter builds them."""
    dialog._placement = placement  # as show_dialog() resolves it
    return dialog._content()


def _press(kb, key, app) -> None:
    """Run the active binding ``kb`` has for ``key`` in ``app``, as a key press would."""
    active = [b for b in kb.get_bindings_for_keys((key,)) if b.filter()]
    active[-1].handler(SimpleNamespace(app=app))


class TestDialogFields:
    def test_values_in_field_order(self):
        d = Dialog("T", fields=[
            TextField("name", "Name", default="bob"),
            CheckboxField("on", "On", default=True),
            RadioField("m", "Mode", options=["x", "y"]),
        ])
        assert list(d.values.items()) == [("name", "bob"), ("on", True), ("m", None)]

    def test_values_follow_edits(self):
        d = Dialog("T", fields=[CheckboxField("on", "On")])
        d._form.controls[0].toggle()
        assert d.values == {"on": True}

    def test_no_fields_no_values(self):
        assert Dialog("T", "text", [ButtonConfig("OK")]).values == {}

    @pytest.mark.parametrize("bad", ["name", Field("k", "L"), ButtonConfig("OK")])
    def test_fields_must_be_field_types(self, bad):
        with pytest.raises(TypeError, match="fields"):
            Dialog("T", fields=[bad])

    def test_keys_are_unique(self):
        with pytest.raises(ValueError, match="'k'"):
            Dialog("T", fields=[CheckboxField("k", "A"), TextField("k", "B")])

    @pytest.mark.parametrize("bad", [3, 0, -1, "left", True, 4.5])
    def test_align_values_is_checked(self, bad):
        with pytest.raises(ValueError, match="align_values"):
            Dialog("T", align_values=bad)

    def test_class_attribute_fields_are_shared_but_values_are_not(self):
        class Form(Dialog):
            fields = [CheckboxField("on", "On")]

        a, b = Form(), Form()
        a._form.controls[0].toggle()
        assert (a.values, b.values) == ({"on": True}, {"on": False})

    @pytest.mark.parametrize("placement", ["box", "inline"])
    def test_fields_go_under_a_text_body(self, placement):
        d = Dialog("T", "Pick:", fields=[CheckboxField("on", "On")])
        content, start = _shown(d, placement)
        assert isinstance(content, HSplit) and len(content.children) == 2
        assert start is d._form.controls[0].get_container()

    def test_an_empty_text_body_shows_just_the_fields(self):
        d = Dialog("T", fields=[CheckboxField("on", "On")])
        content, _ = _shown(d)
        assert [w.content for w in focusable_windows(content)] == [d._form.controls[0]]
        assert len(content.children) == 1

    def test_a_subclass_body_keeps_its_fields(self):
        class Custom(Dialog):
            fields = [CheckboxField("on", "On")]

            def build_body(self):
                return Label("Custom")

        d = Custom()
        content, _ = _shown(d)
        assert [w.content for w in focusable_windows(content)] == [d._form.controls[0]]
        assert len(content.children) == 2

    def test_no_fields_and_no_body_is_no_content(self):
        assert _shown(Dialog("T", buttons=[ButtonConfig("OK")])) == (None, None)

    def test_the_cursor_starts_on_a_radio_lists_picked_option(self):
        d = Dialog("T", fields=[RadioField("m", "Mode", options=["x", "y", "z"], default="y")])
        _, start = _shown(d)
        assert start is d._form.controls[0]._group.rows[1].window

    def test_with_nothing_picked_the_cursor_starts_on_the_first_option(self):
        d = Dialog("T", fields=[RadioField("m", "Mode", options=["x", "y"])])
        _, start = _shown(d)
        assert start is d._form.controls[0]._group.rows[0].window

    def test_a_body_that_takes_focus_comes_first(self):
        area = TextArea()
        d = Dialog("T", area, fields=[CheckboxField("on", "On")])
        _, start = _shown(d)
        assert start is area.window

    def test_is_editing_follows_the_fields(self):
        d = Dialog("T", fields=[TextField("t", "T")])
        assert d._is_editing() is False
        d._form.controls[0].enter_edit_mode()
        assert d._is_editing() is True

    def test_a_boxs_dropdown_menus_float_over_the_screen(self):
        d = Dialog("T", fields=[DropdownField("d", "D", options=["a"])])
        _shown(d, "box")
        assert len(d._screen_floats()) == 1
        _shown(d, "inline")
        assert d._screen_floats() == []

    def test_a_box_binds_the_arrows_inline_leaves_them_to_the_dialog(self):
        d = Dialog("T", fields=[CheckboxField("a", "A"), CheckboxField("b", "B")])
        content, _ = _shown(d, "box")
        assert content.key_bindings.get_bindings_for_keys((Keys.Down,)) != []
        assert content.key_bindings.get_bindings_for_keys((Keys.ControlS,)) == []
        content, _ = _shown(d, "inline")
        assert content.key_bindings is None

    def test_tab_moves_a_field_at_a_time_in_a_box(self):
        d = Dialog("T", fields=[
            ChecklistField("t", "Tools", options=["a", "b", "c"]),
            RadioField("m", "Mode", options=["x", "y"], default="y"),
            CheckboxField("c", "C"),
        ])
        content, start = _shown(d, "box")
        tools, mode, check = d._form.controls
        app = Application(
            layout=Layout(HSplit([content, Button("OK")]), focused_element=start),
            input=DummyInput(),
            output=DummyOutput(),
        )
        layout = app.layout
        with set_app(app):
            assert layout.has_focus(tools._group.rows[0].window)
            _press(content.key_bindings, Keys.Down, app)        # ↓: the next option
            assert layout.has_focus(tools._group.rows[1].window)
            _press(content.key_bindings, Keys.Tab, app)         # Tab: the next field, at its pick
            assert layout.has_focus(mode._group.rows[1].window)
            _press(content.key_bindings, Keys.Tab, app)
            assert layout.has_focus(check.get_container())
            _press(content.key_bindings, Keys.BackTab, app)     # Shift+Tab: back a field
            assert layout.has_focus(mode._group.rows[1].window)
            _press(content.key_bindings, Keys.BackTab, app)
            assert layout.has_focus(tools._group.rows[0].window)
            _press(content.key_bindings, Keys.BackTab, app)     # the first field stays
            assert layout.has_focus(tools._group.rows[0].window)
