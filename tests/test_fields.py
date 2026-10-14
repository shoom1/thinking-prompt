"""Form fields: the Field classes, their controls, and fields on a Dialog."""
from __future__ import annotations

import dataclasses
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import BufferControl, FloatContainer, HSplit, Layout
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.processors import PasswordProcessor
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.utils import get_cwidth
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
from thinking_prompt.fields import (
    CheckboxFieldControl,
    DropdownFieldControl,
    OptionsFieldControl,
    SelectFieldControl,
    TextFieldControl,
    _DropdownMenuControl,
    _RowValue,
    _ValueColumn,
)

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

    def test_tab_crosses_from_a_body_into_the_fields_and_back(self):
        area = TextArea()
        d = Dialog("T", area, fields=[RadioField("m", "Mode", options=["x", "y", "z"], default="z")])
        content, start = _shown(d, "box")
        mode = d._form.controls[0]
        app = Application(
            layout=Layout(HSplit([content, Button("OK")]), focused_element=start),
            input=DummyInput(),
            output=DummyOutput(),
        )
        layout = app.layout
        with set_app(app):
            assert layout.has_focus(area.window)
            _press(content.key_bindings, Keys.Tab, app)        # the picked option, not the first
            assert layout.has_focus(mode._group.rows[2].window)
            _press(content.key_bindings, Keys.BackTab, app)     # back to the body
            assert layout.has_focus(area.window)
            _press(content.key_bindings, Keys.BackTab, app)     # the first group stays
            assert layout.has_focus(area.window)

    def test_align_values_is_read_when_shown(self):
        d = Dialog("T", fields=[CheckboxField("a", "A")])
        d.align_values = "right"
        _shown(d)
        assert d._form.controls[0]._value_column is None


class TestFieldAttributes:
    """Tests for the field classes' attributes."""

    def test_inline_select_item_creation(self):
        """SelectField stores key, label, options, and default."""
        item = SelectField(
            key="model",
            label="Model",
            options=["gpt-4", "gpt-3.5"],
            default="gpt-4",
        )
        assert item.key == "model"
        assert item.label == "Model"
        assert item.options == ["gpt-4", "gpt-3.5"]
        assert item.default == "gpt-4"

    def test_inline_select_item_with_description(self):
        """SelectField can have a description."""
        item = SelectField(
            key="model",
            label="Model",
            description="Select the AI model to use",
            options=["gpt-4", "gpt-3.5"],
            default="gpt-4",
        )
        assert item.description == "Select the AI model to use"

    def test_checkbox_item_creation(self):
        """CheckboxField stores key, label, and default bool."""
        item = CheckboxField(
            key="stream",
            label="Stream Output",
            default=True,
        )
        assert item.key == "stream"
        assert item.label == "Stream Output"
        assert item.default is True

    def test_checkbox_item_default_false(self):
        """CheckboxField defaults to False."""
        item = CheckboxField(key="debug", label="Debug")
        assert item.default is False

    def test_text_item_creation(self):
        """TextField stores key, label, default, and password flag."""
        item = TextField(
            key="api_key",
            label="API Key",
            default="sk-xxx",
            password=True,
        )
        assert item.key == "api_key"
        assert item.label == "API Key"
        assert item.default == "sk-xxx"
        assert item.password is True

    def test_text_item_defaults(self):
        """TextField has sensible defaults."""
        item = TextField(key="name", label="Name")
        assert item.default == ""
        assert item.password is False


class TestSettingsDialogLayout:
    """Dialog(fields=...): the layout."""

    def test_build_body_returns_hsplit(self):
        """build_body returns an HSplit of control containers."""
        items = [
            SelectField(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxField(key="stream", label="Stream", default=True),
        ]
        dialog = Dialog("Settings", fields=items)
        content, _ = dialog._content()

        assert isinstance(content, HSplit)

    def test_build_body_creates_controls(self):
        """build_body creates individual FieldControl instances."""
        from thinking_prompt.fields import (
            CheckboxFieldControl,
            SelectFieldControl,
            TextFieldControl,
        )

        items = [
            SelectField(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxField(key="stream", label="Stream", default=True),
            TextField(key="name", label="Name", default="test"),
        ]
        dialog = Dialog("Settings", fields=items)

        assert len(dialog._form.controls) == 3
        assert isinstance(dialog._form.controls[0], SelectFieldControl)
        assert isinstance(dialog._form.controls[1], CheckboxFieldControl)
        assert isinstance(dialog._form.controls[2], TextFieldControl)


class TestTextControlPasswordMasking:
    """Edit-mode rendering of password fields must not expose the buffer."""

    def _get_buffer_control(self, control: TextFieldControl) -> BufferControl:
        bc = control._buffer_window.content
        assert isinstance(bc, BufferControl)
        return bc

    def test_password_text_item_uses_password_processor_in_edit_mode(self):
        item = TextField(key="api_key", label="API Key", password=True)
        control = TextFieldControl(item)

        bc = self._get_buffer_control(control)
        processors = bc.input_processors or []
        assert any(isinstance(p, PasswordProcessor) for p in processors), (
            "BufferControl for password=True TextField must include "
            "PasswordProcessor; got input_processors="
            f"{processors!r}"
        )

    def test_non_password_text_item_has_no_password_processor(self):
        item = TextField(key="username", label="Username", password=False)
        control = TextFieldControl(item)

        bc = self._get_buffer_control(control)
        processors = bc.input_processors or []
        assert not any(isinstance(p, PasswordProcessor) for p in processors)


class TestSessionIntegration:
    def test_the_field_classes_are_exported(self):
        from thinking_prompt import (  # noqa: F401
            CheckboxField,
            ChecklistField,
            Dialog,
            DropdownField,
            Field,
            RadioField,
            SelectField,
            TextField,
        )

class TestSettingControl:
    """Tests for the FieldControl base class."""

    def test_setting_control_stores_item_and_value(self):
        """FieldControl stores item reference and initial value."""
        from thinking_prompt.fields import CheckboxFieldControl

        item = CheckboxField(key="stream", label="Stream", default=True)
        control = CheckboxFieldControl(item)

        assert control.item is item
        assert control.value is True

    def test_setting_control_is_not_editing_by_default(self):
        """FieldControl starts in view mode."""
        from thinking_prompt.fields import CheckboxFieldControl

        item = CheckboxField(key="stream", label="Stream", default=False)
        control = CheckboxFieldControl(item)

        assert control.is_editing is False


class TestCheckboxControl:
    """Tests for CheckboxFieldControl."""

    def test_checkbox_toggle(self):
        """Checkbox toggles value."""
        from thinking_prompt.fields import CheckboxFieldControl

        item = CheckboxField(key="stream", label="Stream", default=False)
        control = CheckboxFieldControl(item)

        assert control.value is False
        control.toggle()
        assert control.value is True
        control.toggle()
        assert control.value is False

    def test_checkbox_renders_label_and_value(self):
        """Checkbox renders label and true/false value."""
        from thinking_prompt.fields import CheckboxFieldControl

        item = CheckboxField(key="stream", label="Stream Output", default=True)
        control = CheckboxFieldControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Stream Output" in text
        assert "true" in text


class TestInlineSelectControl:
    """Tests for SelectFieldControl."""

    def test_inline_select_cycle_forward(self):
        """InlineSelect cycles through options forward."""
        from thinking_prompt.fields import SelectFieldControl

        item = SelectField(key="model", label="Model", options=["a", "b", "c"], default="a")
        control = SelectFieldControl(item)

        assert control.value == "a"
        control.cycle(1)
        assert control.value == "b"
        control.cycle(1)
        assert control.value == "c"
        control.cycle(1)
        assert control.value == "c"  # clamped at end

    def test_inline_select_cycle_backward(self):
        """InlineSelect cycles through options backward."""
        from thinking_prompt.fields import SelectFieldControl

        item = SelectField(key="model", label="Model", options=["a", "b", "c"], default="a")
        control = SelectFieldControl(item)

        control.cycle(-1)
        assert control.value == "a"  # clamped at start

    @pytest.mark.parametrize("default", [None, "not-an-option"])
    @pytest.mark.parametrize("delta", [1, -1])
    def test_first_press_without_selection_selects_first_option(self, default, delta):
        """With no current selection (no default, or a default that isn't
        an option), the first press selects the first option instead of
        skipping over it."""
        from thinking_prompt.fields import SelectFieldControl

        item = SelectField(key="m", label="M", options=["a", "b", "c"], default=default)
        control = SelectFieldControl(item)

        control.cycle(delta)
        assert control.value == "a"

    def test_an_untouched_select_without_default_keeps_none(self):
        """No default means "unset": leaving it alone keeps None."""
        assert Dialog("S", fields=[SelectField("s", "S", options=["a", "b"])]).values == {"s": None}

    def test_inline_select_renders_label_and_value(self):
        """InlineSelect renders label and current option."""
        from thinking_prompt.fields import SelectFieldControl

        item = SelectField(key="model", label="Model", options=["gpt-4", "gpt-3.5"], default="gpt-4")
        control = SelectFieldControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Model" in text
        assert "gpt-4" in text


def _style_of(line, text: str) -> list[str]:
    """Style classes of the one fragment whose text, stripped, is `text`."""
    (style,) = [s for s, t in line if t.strip() == text]
    return style.split()


class TestSelectArrows:
    """Select rows draw their arrows with class:select-arrow (select_arrow)."""

    def test_inline_select_arrows(self):
        from thinking_prompt.fields import SelectFieldControl

        item = SelectField(key="m", label="M", options=["a", "b", "c"], default="b")
        line = SelectFieldControl(item).create_content(width=40, height=1).get_line(0)

        assert "".join(t for _, t in line).endswith("◀ b ▶")
        assert "class:select-arrow" in _style_of(line, "◀")
        assert "class:select-arrow" in _style_of(line, "▶")
        assert "class:select-arrow" not in _style_of(line, "b")

    def test_dropdown_arrow(self):
        from thinking_prompt.fields import DropdownFieldControl

        item = DropdownField(key="m", label="M", options=["a", "b"], default="b")
        line = DropdownFieldControl(item).create_content(width=40, height=1).get_line(0)

        assert "".join(t for _, t in line).endswith("b ▼")
        assert "class:select-arrow" in _style_of(line, "▼")
        assert "class:select-arrow" not in _style_of(line, "b")


class TestTextControl:
    """Tests for TextFieldControl."""

    def test_text_control_enter_edit_mode(self):
        """TextFieldControl enters edit mode and populates buffer."""
        from thinking_prompt.fields import TextFieldControl

        item = TextField(key="name", label="Name", default="Alice")
        control = TextFieldControl(item)

        assert control.is_editing is False
        control.enter_edit_mode()
        assert control.is_editing is True
        assert control._buffer.text == "Alice"

    def test_text_control_confirm_edit(self):
        """TextFieldControl confirm saves buffer value."""
        from thinking_prompt.fields import TextFieldControl

        item = TextField(key="name", label="Name", default="Alice")
        control = TextFieldControl(item)

        control.enter_edit_mode()
        control._buffer.text = "Bob"
        control.confirm_edit()

        assert control.is_editing is False
        assert control.value == "Bob"

    def test_text_control_cancel_edit(self):
        """TextFieldControl cancel restores original value."""
        from thinking_prompt.fields import TextFieldControl

        item = TextField(key="name", label="Name", default="Alice")
        control = TextFieldControl(item)

        control.enter_edit_mode()
        control._buffer.text = "Bob"
        control.cancel_edit()

        assert control.is_editing is False
        assert control.value == "Alice"  # restored

    def test_text_control_renders_value(self):
        """TextFieldControl renders label and value in view mode."""
        from thinking_prompt.fields import TextFieldControl

        item = TextField(key="name", label="Name", default="Alice")
        control = TextFieldControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Name" in text
        assert "Alice" in text

    def test_text_control_renders_empty_placeholder(self):
        """TextFieldControl shows (empty) for empty value."""
        from thinking_prompt.fields import TextFieldControl

        item = TextField(key="name", label="Name", default="")
        control = TextFieldControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "(empty)" in text

    def test_text_control_renders_password_masked(self):
        """TextFieldControl masks password values."""
        from thinking_prompt.fields import TextFieldControl

        item = TextField(key="api_key", label="API Key", default="sk-secret", password=True)
        control = TextFieldControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "sk-secret" not in text
        assert "••••••" in text

    def test_text_control_container_switches_in_edit_mode(self):
        """TextFieldControl container returns different content in edit mode."""
        from prompt_toolkit.layout import DynamicContainer

        from thinking_prompt.fields import TextFieldControl

        item = TextField(key="name", label="Name", default="Alice")
        control = TextFieldControl(item)

        container = control.get_container()
        # Should be a DynamicContainer
        assert isinstance(container, DynamicContainer)


class TestSettingsDialogRefactored:
    """Dialog(fields=...) builds individual controls."""

    def test_settings_dialog_creates_controls(self):
        """A Dialog with fields creates FieldControl instances."""
        from thinking_prompt.fields import (
            CheckboxFieldControl,
            SelectFieldControl,
            TextFieldControl,
        )

        items = [
            CheckboxField(key="stream", label="Stream", default=True),
            SelectField(key="model", label="Model", options=["a", "b"], default="a"),
            TextField(key="name", label="Name", default="test"),
        ]
        dialog = Dialog("Settings", fields=items)

        assert len(dialog._form.controls) == 3
        assert isinstance(dialog._form.controls[0], CheckboxFieldControl)
        assert isinstance(dialog._form.controls[1], SelectFieldControl)
        assert isinstance(dialog._form.controls[2], TextFieldControl)

    def test_settings_dialog_build_body_returns_hsplit(self):
        """build_body returns HSplit of control containers."""
        items = [
            CheckboxField(key="stream", label="Stream", default=True),
        ]
        dialog = Dialog("Settings", fields=items)
        content, _ = dialog._content()

        assert isinstance(content, HSplit)


def _bindings(kb, key):
    return [] if kb is None else kb.get_bindings_for_keys((key,))


def _inline_dropdown(**item) -> DropdownFieldControl:
    control = DropdownFieldControl(DropdownField(**item))
    control.set_inline(True)
    return control


def _line(control, selected: bool, row: int = 0):
    """``control``'s ``row`` as drawn while its first cursor stop has
    focus (``selected``), or with no app running."""
    if not selected:
        return control.create_content(40, 2).get_line(row)
    layout = Layout(control.get_container(), focused_element=control.get_stops()[0])
    with set_app(Application(layout=layout, input=DummyInput(), output=DummyOutput())):
        return control.create_content(40, 2).get_line(row)


class TestRowStyles:
    """A setting's label, value and description take their -selected
    styles while the setting has focus."""

    @pytest.mark.parametrize(
        "make,value,style",
        [
            (lambda: CheckboxFieldControl(CheckboxField(key="c", label="Label", default=True)),
             "true", "field-value-true"),
            (lambda: CheckboxFieldControl(CheckboxField(key="c", label="Label")),
             "false", "field-value-false"),
            (lambda: SelectFieldControl(SelectField(key="s", label="Label", options=["a", "b"], default="a")),
             "a", "field-value"),
            (lambda: _inline_dropdown(key="d", label="Label", options=["a", "b"], default="a"),
             "a", "field-value"),
            (lambda: DropdownFieldControl(DropdownField(key="d", label="Label", options=["a", "b"], default="a")),
             "a", "field-value"),
            (lambda: TextFieldControl(TextField(key="t", label="Label", default="bob")),
             "bob", "field-value"),
            (lambda: TextFieldControl(TextField(key="t", label="Label")),
             "(empty)", "field-desc"),
        ],
        ids=["checked", "unchecked", "select", "inline-dropdown", "dropdown", "text", "empty-text"],
    )
    @pytest.mark.parametrize("selected", [False, True], ids=["idle", "selected"])
    def test_label_and_value(self, make, value, style, selected):
        line = _line(make(), selected)
        suffix = "-selected" if selected else ""
        assert f"class:field-label{suffix}" in _style_of(line, "Label")
        assert f"class:{style}{suffix}" in _style_of(line, value)

    @pytest.mark.parametrize("selected", [False, True], ids=["idle", "selected"])
    def test_a_description(self, selected):
        control = CheckboxFieldControl(CheckboxField(key="c", label="Label", description="Says more"))
        suffix = "-selected" if selected else ""
        assert _line(control, selected, row=1) == [("", "  "), (f"class:field-desc{suffix}", "Says more")]

    @pytest.mark.parametrize("selected", [False, True], ids=["idle", "selected"])
    def test_a_lists_label_and_description(self, selected):
        control = OptionsFieldControl(
            ChecklistField(key="t", label="Label", description="Says more", options=["a"])
        )
        suffix = "-selected" if selected else ""
        assert _line(control, selected) == [("", "  "), (f"class:field-label{suffix}", "Label")]
        assert _line(control, selected, row=1) == [("", "  "), (f"class:field-desc{suffix}", "Says more")]

    async def test_a_description_stays_under_the_edit_field(self):
        control = TextFieldControl(TextField(key="t", label="Name", description="Says more", default="bob"))
        control.enter_edit_mode()
        row, description = _drawn(control.get_container(), 30, height=2)
        assert _field(row)
        assert _text(description).rstrip() == "  Says more"
        assert all("class:field-desc-selected" in style for _, style in description[2:11])

    @pytest.mark.parametrize(
        "make",
        [
            lambda: SelectFieldControl(SelectField(key="s", label="S", options=["a", "b", "c"], default="b")),
            lambda: _inline_dropdown(key="d", label="D", options=["a", "b", "c"], default="b"),
        ],
        ids=["select", "inline-dropdown"],
    )
    @pytest.mark.parametrize(
        "key,value", [(Keys.Left, "a"), (Keys.Right, "c"), (" ", "c")], ids=["left", "right", "space"]
    )
    def test_selector_keys_step_through_the_options(self, make, key, value):
        control = make()
        (binding,) = [b for b in _bindings(control.get_key_bindings(), key) if b.filter()]
        binding.handler(MagicMock())
        assert control.value == value


class TestSettingsRows:
    """Settings controls are dialog rows: the ❯ marker, and inline/box modes."""

    def test_the_highlighted_row_uses_the_marker(self):
        from thinking_prompt.fields import CheckboxFieldControl

        control = CheckboxFieldControl(CheckboxField(key="s", label="Stream"))
        (row,) = control._build_setting_row(40, _RowValue("true", "", 4), True)
        assert row[0] == ("class:field-indicator", "❯ ")

    def test_inline_dropdown_is_a_selector_without_a_popup(self):
        from thinking_prompt.fields import DropdownFieldControl

        control = DropdownFieldControl(DropdownField(key="m", label="Model", options=["a", "b", "c"], default="b"))
        control.set_inline(True)
        text = "".join(t for _, t in control.create_content(40, 1).get_line(0))
        assert text.endswith("◀ b ▶")
        assert control.hints == {"←→ change"}
        kb = control.get_key_bindings()
        (right,) = [b for b in _bindings(kb, Keys.Right) if b.filter()]
        right.handler(MagicMock())
        assert control.value == "c"
        assert not any(b.filter() for b in _bindings(kb, Keys.ControlM))  # no popup

    def test_box_dropdown_is_unchanged(self):
        from thinking_prompt.fields import DropdownFieldControl

        control = DropdownFieldControl(DropdownField(key="m", label="Model", options=["a", "b"], default="b"))
        text = "".join(t for _, t in control.create_content(40, 1).get_line(0))
        assert text.endswith("b ▼")
        assert control.hints == frozenset()

    def test_inline_body_has_no_popups_and_leaves_arrows_to_the_dialog(self):
        dialog = Dialog(
            "S",
            fields=[DropdownField(key="m", label="M", options=["a", "b"]), CheckboxField(key="c", label="C")],
            placement="inline",
        )
        dialog._placement = "inline"  # as show_dialog() resolves it
        body, _ = dialog._content()
        assert isinstance(body, HSplit)  # no FloatContainer for dropdown menus
        assert _bindings(body.key_bindings, Keys.Down) == []
        assert _bindings(body.key_bindings, Keys.ControlS) == []

    def test_box_body_walks_settings_with_arrows(self):
        dialog = Dialog("S", fields=[CheckboxField(key="a", label="A"), CheckboxField(key="b", label="B")])
        body, _ = dialog._content()
        assert _bindings(body.key_bindings, Keys.Down) != []
        assert len(dialog._form.stops()) == 2

    def test_is_editing_follows_the_controls(self):
        dialog = Dialog("S", fields=[TextField(key="t", label="T")])
        assert dialog._is_editing() is False
        dialog._form.controls[0].enter_edit_mode()
        assert dialog._is_editing() is True



class TestOptionItems:
    """Check lists and radio lists in the settings form, one option per line."""

    def test_checklist_value_is_the_checked_options_in_option_order(self):
        from thinking_prompt.fields import ChecklistField, OptionsFieldControl

        control = OptionsFieldControl(ChecklistField(key="t", label="Tools", options=["a", "b", "c"], default=("c", "a")))
        assert control.value == ["a", "c"]

    def test_radio_value(self):
        from thinking_prompt.fields import OptionsFieldControl, RadioField

        assert OptionsFieldControl(RadioField(key="m", label="Mode", options=["x", "y"], default="y")).value == "y"
        assert OptionsFieldControl(RadioField(key="m", label="Mode", options=["x", "y"])).value is None

    def test_one_stop_per_option_and_the_label_takes_no_focus(self):
        from thinking_prompt.fields import ChecklistField, OptionsFieldControl

        control = OptionsFieldControl(ChecklistField(key="t", label="Tools", options=["a", "b"]))
        assert len(control.get_stops()) == 2
        assert not control.is_focusable()
        assert control.row_count == 3

    def test_values_follow_the_lists(self):
        from thinking_prompt.fields import ChecklistField, RadioField

        dialog = Dialog("S", fields=[
            ChecklistField(key="t", label="T", options=["a", "b"], default=("b",)),
            RadioField(key="m", label="M", options=["x", "y"]),
        ])
        assert dialog.values == {"t": ["b"], "m": None}
        tools, mode = dialog._form.controls
        tools._group.choose("a")
        mode._group.choose("x")
        assert dialog.values == {"t": ["a", "b"], "m": "x"}

    def test_box_cursor_stops_on_each_option(self):
        from thinking_prompt.fields import ChecklistField

        dialog = Dialog("S", fields=[
            CheckboxField(key="c", label="C"),
            ChecklistField(key="t", label="T", options=["a", "b"]),
        ])
        assert len(dialog._form.stops()) == 3

    def test_exported(self):
        from thinking_prompt import ChecklistField, RadioField

        assert ChecklistField and RadioField


@pytest.mark.parametrize(
    "make,widest",
    [
        (lambda: CheckboxFieldControl(CheckboxField(key="a", label="A")), len("false")),
        (
            lambda: SelectFieldControl(
                SelectField(key="a", label="A", options=["S", "Medium", "XL"])
            ),
            len("◀ Medium ▶"),
        ),
        (
            lambda: DropdownFieldControl(DropdownField(key="a", label="A", options=["x"], width=20)),
            20 + len(" ▼"),
        ),
        (
            lambda: SelectFieldControl(
                SelectField(key="a", label="A", options=["S", "M"], default="Not an option")
            ),
            len("◀ Not an option ▶"),
        ),
        (lambda: TextFieldControl(TextField(key="a", label="A", edit_width=12)), 12),
        (lambda: TextFieldControl(TextField(key="a", label="A", edit_width=5)), len("(empty)")),
        (
            lambda: TextFieldControl(TextField(key="a", label="A", default="a long default", edit_width=5)),
            len("a long default"),
        ),
        (lambda: OptionsFieldControl(ChecklistField(key="a", label="A", options=["x"])), 0),
    ],
)
def test_widest_value(make, widest):
    """The most columns a setting's value takes in full: showing any of its
    options, or what it shows now."""
    assert make().widest_value() == widest


def test_an_inline_dropdowns_widest_value_is_its_widest_option():
    control = DropdownFieldControl(DropdownField(key="a", label="A", options=["x", "Longest"], width=20))
    control.set_inline(True)
    assert control.widest_value() == len("◀ Longest ▶")


def _fixed(column: int | None) -> _ValueColumn | None:
    """Values at ``column`` whatever the row's width; None: at the right edge."""
    return None if column is None else _ValueColumn(column)


def _row(control, column, width: int = 60) -> str:
    control.set_value_column(_fixed(column))
    return "".join(text for _, text in control.create_content(width, 1).get_line(0))


def _drawn(container, width: int, height: int = 1) -> list[list[tuple[str, str]]]:
    """``container`` drawn ``width`` columns wide, floats included: each
    row's cells as (character, style)."""
    screen = Screen()
    container.write_to_screen(screen, MouseHandlers(), WritePosition(0, 0, width, height), "", True, None)
    screen.draw_all_floats()
    return [
        [(screen.data_buffer[y][x].char, screen.data_buffer[y][x].style) for x in range(width)]
        for y in range(height)
    ]


def _text(cells: list[tuple[str, str]]) -> str:
    return "".join(char for char, _ in cells)


def _field(cells: list[tuple[str, str]]) -> list[int]:
    """The columns of a text setting's input field (its text-area style).
    (Tests drawing one are async: its buffer loads its history in a task.)"""
    return [x for x, (_, style) in enumerate(cells) if "class:text-area" in style]


# (make the control, its label, its value at a column, how the row ends at the right edge)
ROWS = [
    (lambda: CheckboxFieldControl(CheckboxField(key="c", label="Stream", default=True)),
     "Stream", "true", "true"),
    (lambda: SelectFieldControl(SelectField(key="s", label="Size", options=["a", "b", "c"], default="b")),
     "Size", "◀ b ▶", "◀ b ▶"),
    (lambda: DropdownFieldControl(DropdownField(key="d", label="Model", options=["gpt", "o1"], default="o1")),
     "Model", "o1".ljust(15) + " ▼", "o1 ▼"),
    (lambda: TextFieldControl(TextField(key="t", label="Name", default="bob")),
     "Name", "bob".ljust(15), "bob"),
]
ROW_IDS = ["checkbox", "select", "dropdown", "text"]


class TestValueColumn:
    @pytest.mark.parametrize("make,label,at_column,at_right", ROWS, ids=ROW_IDS)
    def test_a_value_starts_at_its_column(self, make, label, at_column, at_right):
        row = _row(make(), 20)
        assert row[:20].strip() == label
        assert row[20:].startswith(at_column)

    @pytest.mark.parametrize("make,label,at_column,at_right", ROWS, ids=ROW_IDS)
    def test_no_column_keeps_values_at_the_right_edge(self, make, label, at_column, at_right):
        row = _row(make(), None)
        assert len(row) == 59
        assert row.endswith(at_right)

    def test_a_long_label_is_cut_before_the_column(self):
        row = _row(CheckboxFieldControl(CheckboxField(key="c", label="A very long label indeed")), 10)
        assert row[:10] == "  A very… "
        assert row[10:] == "false"

    def test_a_narrow_row_puts_the_value_at_the_right_edge(self):
        row = _row(CheckboxFieldControl(CheckboxField(key="c", label="Streaming output")), 30, width=20)
        assert row.endswith("false") and len(row) == 19
        assert "…" in row

    def test_fields_are_padded_in_terminal_columns(self):
        """Wide characters take two columns: a dropdown's ▼ lines up whatever
        its value, and a text value takes its edit_width."""

        def mark(value: str) -> int:
            item = DropdownField(key="d", label="Model", options=["日本語モデル", "beta"], default=value)
            row = _row(DropdownFieldControl(item), 20)
            return get_cwidth(row[:row.index("▼")])

        assert mark("日本語モデル") == mark("beta") == 20 + 15 + 1
        text = _row(TextFieldControl(TextField(key="t", label="Name", default="名前です")), 20)
        assert get_cwidth(text) == 20 + 15

    def test_a_value_reaching_the_rows_last_column_falls_back_too(self):
        """Values end where "right" ends them, a column short of the row's
        right edge: a value fits at its column if it ends there."""
        control = CheckboxFieldControl(CheckboxField(key="c", label="Stream"))
        assert _row(control, 14, width=20)[14:] == "false"
        row = _row(control, 15, width=20)
        assert row.endswith("false") and len(row) == 19

    @staticmethod
    def _menu_open(width: int, **kwargs) -> list[str]:
        """A box form's dropdown, its menu open, drawn ``width`` columns wide."""
        items = [
            DropdownField(key="d", label="Model", options=["alpha", "beta"], default="beta"),
            *(CheckboxField(key=k, label=k) for k in ("a", "b", "c")),
        ]
        dialog = Dialog("S", fields=items, **kwargs)
        body, _ = dialog._content()
        dialog._form.controls[0].enter_edit_mode()
        # As a box has them: the menu floats over the whole screen.
        screen = FloatContainer(content=body, floats=dialog._screen_floats())
        return [_text(row) for row in _drawn(screen, width, 4)]

    def test_the_dropdown_menu_floats_under_its_value(self):
        rows = self._menu_open(60, align_values=20)
        assert rows[0].index("beta") == rows[1].index("┌") == 20

    def test_a_narrow_row_floats_the_menu_under_the_value_at_the_right_edge(self):
        rows = self._menu_open(36, align_values=30)
        value = 36 - 1 - len("beta".ljust(15) + " ▼")
        assert rows[0].index("beta") == rows[1].index("┌") == value
        assert "beta" in rows[2]  # the menu has room for its options

    @staticmethod
    def _wide_menu_open(width: int, label: str, **kwargs) -> list[str]:
        items = [
            DropdownField(key="d", label=label, options=["alpha", "beta"], default="beta"),
            *(CheckboxField(key=k, label=k) for k in ("a", "b", "c")),
        ]
        dialog = Dialog("S", fields=items, **kwargs)
        body, _ = dialog._content()
        dialog._form.controls[0].enter_edit_mode()
        # As a box has them: the menu floats over the whole screen.
        screen = FloatContainer(content=body, floats=dialog._screen_floats())
        return [_text(row) for row in _drawn(screen, width, 4)]

    def test_a_wide_label_does_not_shift_the_menu_off_its_value(self):
        rows = self._wide_menu_open(60, "モデル名", align_values=20)
        assert get_cwidth(rows[0][: rows[0].index("beta")]) == 20
        assert get_cwidth(rows[1][: rows[1].index("┌")]) == 20

    def test_a_wide_label_in_a_narrow_row_keeps_the_menu_under_the_value(self):
        rows = self._wide_menu_open(70, "モデル名モデル名モデル名モデル名モデル名", align_values=40)
        assert get_cwidth(rows[0][: rows[0].index("beta")]) == get_cwidth(
            rows[1][: rows[1].index("┌")]
        )
        assert "┌" in rows[1] and not rows[1].startswith("┌")

    def test_without_a_column_the_menu_floats_under_the_value_at_the_right_edge(self):
        rows = self._menu_open(60, align_values="right")
        field = 15  # the dropdown's width, the value right-justified in it
        assert rows[1].index("┌") == rows[0].index("▼") - 1 - field

    async def test_the_text_field_starts_at_the_column_while_editing(self):
        control = TextFieldControl(TextField(key="t", label="Name", default="bob"))
        control.set_value_column(_ValueColumn(20))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 60)
        assert _field(row) == list(range(20, 35))
        assert _text(row)[20:23] == "bob"

    async def test_while_editing_a_long_label_is_cut_before_the_field(self):
        control = TextFieldControl(TextField(key="t", label="A rather long label", default="bob"))
        control.set_value_column(_ValueColumn(12))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 60)
        assert _text(row)[:15] == "❯ A rather… bob"

    async def test_a_narrow_row_keeps_the_text_field_where_the_value_was(self):
        """Too narrow for the column, the field ends at the row's right edge,
        as the value did, and the label is cut before it as it was."""
        control = TextFieldControl(TextField(key="t", label="A rather long label", default="bob"))
        shown = _row(control, 30, width=36)
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 36)
        assert _field(row) == list(range(36 - 1 - 15, 36 - 1))
        assert _text(row)[2:23] == shown[2:23] == "A rather long la… bob"

    async def test_without_a_column_the_text_field_is_at_the_right_edge(self):
        control = TextFieldControl(TextField(key="t", label="Name"))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 40)
        assert _field(row) == list(range(39 - 15, 39))


def _dropdown(label: str = "Model for summaries", default: str = "o1") -> DropdownFieldControl:
    return DropdownFieldControl(DropdownField(key="d", label=label, options=["gpt-4o", "o1"], default=default))


def _selector(label: str = "Model name", options=("a", "gpt-4o-mini", "z"), default="gpt-4o-mini"):
    return SelectFieldControl(SelectField(key="s", label=label, options=list(options), default=default))


def _text_setting(label: str = "Display name", default: str = "bob") -> TextFieldControl:
    return TextFieldControl(TextField(key="t", label=label, default=default))


class TestRowsShortOfWidth:
    """A label/value row gives way in order: the value at its column, in full;
    at the right edge, the label cut; the label at 3 columns and the field
    shrunk; the value cut. Its decoration stays."""

    # Checkbox: no padding, no decoration.
    def test_checkbox_in_full_at_the_column(self):
        control = CheckboxFieldControl(CheckboxField(key="c", label="Stream responses", default=True))
        assert _row(control, 20, width=30) == "  Stream responses  true"

    def test_checkbox_at_the_right_edge_with_a_cut_label(self):
        control = CheckboxFieldControl(CheckboxField(key="c", label="Stream responses", default=True))
        assert _row(control, 20, width=20) == "  Stream resp… true"
        assert _row(control, None, width=20) == "  Stream resp… true"

    def test_checkbox_with_a_3_column_label_cuts_the_value(self):
        control = CheckboxFieldControl(CheckboxField(key="c", label="Stream responses", default=True))
        assert _row(control, None, width=8) == "  St… …"

    def test_a_label_of_3_columns_or_fewer_is_never_cut(self):
        for label in ("Abc", "Go", "A"):
            control = CheckboxFieldControl(CheckboxField(key="c", label=label, default=True))
            assert _row(control, None, width=8).startswith(f"  {label} ")
            assert _row(control, 6, width=8).startswith(f"  {label} ")

    def test_a_floor_row_is_clipped_without_raising(self):
        control = CheckboxFieldControl(CheckboxField(key="c", label="Stream responses", default=True))
        for width in (0, 1, 3, 5):
            _row(control, None, width=width)
            _row(control, 10, width=width)

    # Selector: no padding, ◀ / ▶ around the option.
    def test_selector_in_full_at_the_column(self):
        assert _row(_selector(), 14, width=40) == "  Model name  ◀ gpt-4o-mini ▶"

    def test_selector_at_the_right_edge_with_a_cut_label(self):
        assert _row(_selector(), 14, width=24) == "  Mode… ◀ gpt-4o-mini ▶"

    def test_selector_cuts_the_option_and_keeps_its_arrows(self):
        assert _row(_selector(), None, width=20) == "  Mo… ◀ gpt-4o-m… ▶"
        assert _row(_selector(), 14, width=20) == "  Mo… ◀ gpt-4o-m… ▶"

    def test_an_inline_dropdown_gives_way_like_a_selector(self):
        control = _dropdown(label="Model name", default="o1")
        control.set_inline(True)
        assert _row(control, 14, width=24) == "  Model name  ◀ o1  "
        assert _row(control, None, width=12) == "  Mo… ◀ o1 "

    def test_a_missing_arrows_blank_place_gives_way_before_the_option_is_cut(self):
        # Last option: no ▶, so the blank after it shrinks first.
        last = _selector(options=("a", "gpt-4o", "z"), default="z")
        assert _row(last, 14, width=40) == "  Model name  ◀ z  "
        assert _row(last, None, width=12) == "  Mo… ◀ z  "
        # First option: no ◀, so the blank before it shrinks first.
        first = _selector(options=("a", "gpt-4o", "z"), default="a")
        assert _row(first, 14, width=40) == "  Model name    a ▶"
        assert _row(first, None, width=10) == "  Mo… a ▶"
        # The visible arrow stays; only then is the option cut.
        control = _selector(options=("gpt-4o-mini", "z"), default="gpt-4o-mini")
        assert _row(control, None, width=12) == "  Mo… gp… ▶"

    # Box dropdown: padded to its width, ▼ after.
    def test_dropdown_in_full_at_the_column(self):
        assert _row(_dropdown(), 22) == "  Model for summaries " + "o1".ljust(15) + " ▼"

    def test_dropdown_at_the_right_edge_with_a_cut_label(self):
        assert _row(_dropdown(), None, width=34) == "  Model for su… " + "o1".rjust(15) + " ▼"
        assert _row(_dropdown(), 30, width=34) == "  Model for su… " + "o1".ljust(15) + " ▼"

    def test_without_a_column_a_long_label_gives_way_to_the_value(self):
        row = _row(_dropdown(), None, width=40)
        assert row.startswith("  Model for summaries")
        assert row.endswith("o1 ▼") and len(row) == 39
        row = _row(_dropdown(), None, width=30)
        assert "…" in row and row.endswith("o1 ▼") and len(row) == 29

    def test_dropdown_shrinks_its_field_with_the_label_at_3_columns(self):
        assert _row(_dropdown(), None, width=20) == "  Mo… " + "o1".rjust(11) + " ▼"
        assert _row(_dropdown(), 22, width=20) == "  Mo… " + "o1".ljust(11) + " ▼"

    def test_dropdown_cuts_its_value_and_keeps_the_arrow(self):
        control = _dropdown(default="gpt-4o")
        assert _row(control, 22, width=12) == "  Mo… gp… ▼"
        assert _row(control, None, width=12) == "  Mo… gp… ▼"

    # Text field: padded to edit_width, no decoration.
    def test_text_in_full_at_the_column(self):
        assert _row(_text_setting(), 16, width=40) == "  Display name  " + "bob".ljust(15)

    def test_text_at_the_right_edge_with_a_cut_label(self):
        assert _row(_text_setting(), 16, width=30) == "  Display na… " + "bob".ljust(15)
        assert _row(_text_setting(), None, width=30) == "  Display na… " + "bob".rjust(15)

    def test_text_shrinks_its_field_with_the_label_at_3_columns(self):
        assert _row(_text_setting(), 16, width=15) == "  Di… " + "bob".ljust(8)
        assert _row(_text_setting(), None, width=15) == "  Di… " + "bob".rjust(8)

    def test_text_cuts_its_value(self):
        assert _row(_text_setting(default="alexander"), 16, width=12) == "  Di… alex…"

    # Terminal columns, not characters.
    def test_a_wide_label_is_cut_by_columns(self):
        control = CheckboxFieldControl(CheckboxField(key="c", label="設定モデル名前", default=True))
        row = _row(control, None, width=14)
        assert row == "  設定…  true"
        assert get_cwidth(row) == 13

    def test_a_wide_value_is_cut_by_columns(self):
        control = _selector(label="Mod", options=("x", "日本語モデル", "y"), default="日本語モデル")
        row = _row(control, None, width=22)
        assert row == "  Mod ◀ 日本語モデ… ▶"
        assert get_cwidth(row) == 21

    # The menu follows the shrunk field.
    def test_the_menu_position_follows_a_shrunk_field(self):
        control = _dropdown(label="Model for summaries", default="o1")
        control.set_value_column(_ValueColumn(10))
        content = control.create_content(20, 1)
        line = "".join(text for _, text in content.get_line(0))
        assert line == "  Mo… " + "o1".ljust(11) + " ▼"
        assert content.menu_position.x == line.index("o1") == 6

    def test_the_menu_position_counts_characters_ahead_of_the_value(self):
        control = _dropdown(label="設定モデル名前名前名前")
        control.set_value_column(_ValueColumn(30))
        content = control.create_content(30, 1)
        line = "".join(text for _, text in content.get_line(0))
        assert content.menu_position.x == line.index("o1")

    # Editing a text setting: the field takes the layout's start and width.
    @pytest.mark.parametrize(
        "column,width,cells",
        [
            (20, 30, range(14, 29)),   # at the right edge, label cut
            (None, 30, range(14, 29)),
            (None, 24, range(8, 23)),  # "right": the field is visible
            (20, 14, range(5, 13)),    # the 8-column minimum cuts the label further
            (None, 14, range(5, 13)),
        ],
    )
    async def test_the_edit_field_follows_the_layout(self, column, width, cells):
        control = _text_setting()
        control.set_value_column(_fixed(column))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), width)
        assert _field(row) == list(cells)
        assert len(cells) >= 8

    async def test_the_edit_field_starts_where_the_value_was_drawn(self):
        control = _text_setting()
        control.set_value_column(_ValueColumn(20))
        shown = _row(control, 20, width=30)
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 30)
        assert _field(row)[0] == shown.index("bob")

    async def test_a_row_too_narrow_for_the_minimum_does_not_collapse(self):
        control = _text_setting()
        control.enter_edit_mode()
        for width in (12, 8, 6, 3, 1):
            (row,) = _drawn(control.get_container(), width)
            assert len(row) == width
            assert all(x < width for x in _field(row))

    @pytest.mark.parametrize("column", [20, None])
    @pytest.mark.parametrize("password", [False, True])
    @pytest.mark.parametrize("default", ["alexander", "alexander the great"])
    async def test_a_long_value_keeps_the_minimum_in_a_narrow_row(self, column, password, default):
        control = TextFieldControl(TextField(key="t", label="Display name", default=default, password=password))
        control.set_value_column(_fixed(column))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 14)
        assert _field(row) == list(range(5, 13))

    @pytest.mark.parametrize("password", [False, True])
    async def test_a_long_value_gets_exactly_edit_width_in_a_wide_row(self, password):
        control = TextFieldControl(
            TextField(key="t", label="Name", default="a value of nineteen", password=password)
        )
        control.set_value_column(_ValueColumn(10))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 60)
        assert _field(row) == list(range(10, 25))

    async def test_a_small_edit_width_is_its_own_minimum(self):
        control = TextFieldControl(TextField(key="t", label="Display name", default="bob", edit_width=5))
        control.set_value_column(None)
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 12)
        assert len(_field(row)) == 5


class TestAlignValues:
    @staticmethod
    def _column(items, shown="box", **kwargs):
        dialog = Dialog("S", fields=items, **kwargs)
        dialog._placement = shown  # as show_dialog() resolves it
        dialog._content()
        return dialog._form.controls[0]._value_column

    def test_labels_start_values_after_the_longest_label(self):
        items = [
            CheckboxField(key="a", label="Stream"),
            TextField(key="b", label="API key"),
            ChecklistField(key="c", label="A much longer check list label", options=["x"]),
        ]
        assert self._column(items).at(60) == 2 + len("API key") + 2

    def test_labels_are_measured_in_terminal_columns(self):
        items = [CheckboxField(key="a", label="設定"), CheckboxField(key="b", label="abc")]
        assert self._column(items).at(60) == 2 + 4 + 2

    def test_right_and_a_column(self):
        items = [CheckboxField(key="a", label="Stream", description="Show tokens as they arrive")]
        assert self._column(items, align_values="right") is None
        column = self._column(items, align_values=24)
        assert (column.at(60), column.at(20)) == (24, 24)  # a set column doesn't move

    def test_values_clear_the_longest_description(self):
        items = [
            CheckboxField(key="a", label="Stream", description="Show tokens as they arrive"),
            TextField(key="b", label="API key", edit_width=10),
        ]
        assert self._column(items).at(80) == 2 + len("Show tokens as they arrive") + 2

    def test_a_description_too_long_for_the_values_runs_under_them(self):
        items = [
            CheckboxField(key="a", label="Stream", description="x" * 50),
            TextField(key="b", label="API key", edit_width=20),
        ]
        column = self._column(items)
        # As far right as the widest value (the 20-column field) still fits
        # before the row's last column, never left of the labels.
        assert column.at(60) == 60 - 1 - 20
        assert column.at(200) == 2 + 50 + 2
        assert column.at(20) == 2 + len("API key") + 2

    def test_an_inline_dropdown_is_measured_as_the_selector_it_shows(self):
        items = [
            DropdownField(key="m", label="Model", description="d" * 60, options=["a", "b"], width=30),
        ]
        # Inline, the value is "◀ a ▶"; in a box, a 30-column menu field and " ▼".
        assert self._column(items, shown="inline").at(80) == 2 + 60 + 2
        assert self._column(items, shown="box").at(80) == 80 - 1 - (30 + 2)

    def test_list_labels_and_descriptions_dont_move_the_values(self):
        items = [
            CheckboxField(key="a", label="Stream"),
            ChecklistField(key="c", label="Tools", description="y" * 40, options=["x"]),
        ]
        assert self._column(items).at(80) == 2 + len("Stream") + 2

    def test_a_form_of_lists_only_needs_no_column(self):
        dialog = Dialog("S", fields=[ChecklistField(key="c", label="Tools", options=["x", "y"])])
        dialog._content()

    def test_the_smallest_column(self):
        assert Dialog("S", align_values=4).align_values == 4


def test_the_settings_dialog_is_gone():
    assert not hasattr(thinking_prompt, "SettingsDialog")
    assert "SettingsDialog" not in thinking_prompt.__all__
    assert not hasattr(thinking_prompt.ThinkingPromptSession, "show_settings_dialog")
    with pytest.raises(ImportError):
        importlib.import_module("thinking_prompt.settings_dialog")


class TestDropdownMenuColumns:
    WIDE = "日本語のオプションです"  # 11 characters, 22 columns

    def _menu_rows(self, **field):
        control = DropdownFieldControl(DropdownField("k", "Lang", **field))
        width = control._get_dropdown_width()
        content = _DropdownMenuControl(control).create_content(width, 4)
        return width, [content.get_line(i) for i in range(content.line_count)]

    def test_every_row_fills_the_menu_exactly_with_the_scrollbar_last(self):
        width, rows = self._menu_rows(options=[self.WIDE, "short", "a", "b", "c", "d"], default="short")
        for row in rows:
            assert sum(get_cwidth(text) for _, text, *_ in row) == width
            assert row[-1][0].startswith("class:scrollbar")

    def test_a_cut_option_ends_in_an_ellipsis(self):
        _, rows = self._menu_rows(options=[self.WIDE, "b"], default="b")
        text = "".join(text for _, text, *_ in rows[0])
        assert text.rstrip().endswith("…")

    def test_auto_width_counts_columns(self):
        control = DropdownFieldControl(DropdownField("k", "L", options=["日本語", "ab"], width=None))
        assert control._get_dropdown_width() == 6 + 4
