"""Tests for the settings dialog system."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import BufferControl, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.processors import PasswordProcessor
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.utils import get_cwidth

from thinking_prompt.settings_dialog import (
    CheckboxControl,
    CheckboxItem,
    ChecklistItem,
    DropdownControl,
    DropdownItem,
    InlineSelectControl,
    InlineSelectItem,
    OptionsControl,
    SettingsDialog,
    TextControl,
    TextItem,
    _RowValue,
    _ValueColumn,
)


class TestSettingsItems:
    """Tests for settings item types."""

    def test_inline_select_item_creation(self):
        """InlineSelectItem stores key, label, options, and default."""
        item = InlineSelectItem(
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
        """InlineSelectItem can have a description."""
        item = InlineSelectItem(
            key="model",
            label="Model",
            description="Select the AI model to use",
            options=["gpt-4", "gpt-3.5"],
            default="gpt-4",
        )
        assert item.description == "Select the AI model to use"

    def test_checkbox_item_creation(self):
        """CheckboxItem stores key, label, and default bool."""
        item = CheckboxItem(
            key="stream",
            label="Stream Output",
            default=True,
        )
        assert item.key == "stream"
        assert item.label == "Stream Output"
        assert item.default is True

    def test_checkbox_item_default_false(self):
        """CheckboxItem defaults to False."""
        item = CheckboxItem(key="debug", label="Debug")
        assert item.default is False

    def test_text_item_creation(self):
        """TextItem stores key, label, default, and password flag."""
        item = TextItem(
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
        """TextItem has sensible defaults."""
        item = TextItem(key="name", label="Name")
        assert item.default == ""
        assert item.password is False


class TestSettingsDialogState:
    """Tests for SettingsDialog state management."""

    def test_settings_dialog_init_original_values(self):
        """SettingsDialog initializes original values from items."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)

        assert dialog._original_values == {"model": "a", "stream": True, "name": "test"}

    def test_settings_dialog_get_changed_values_empty(self):
        """No changes returns empty dict."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()  # Creates the list control

        changed = dialog._get_changed_values()
        assert changed == {}

    def test_settings_dialog_get_changed_values_with_changes(self):
        """Changed values are returned correctly."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()  # Creates the controls

        # Simulate user changing dropdown via control
        dialog._controls[0].value = "b"

        changed = dialog._get_changed_values()
        assert changed == {"model": "b"}

    def test_settings_dialog_can_cancel_default_true(self):
        """SettingsDialog has can_cancel=True by default."""
        dialog = SettingsDialog(title="Settings", items=[])
        assert dialog._can_cancel is True

    def test_settings_dialog_can_cancel_false(self):
        """SettingsDialog can disable cancel."""
        dialog = SettingsDialog(title="Settings", items=[], can_cancel=False)
        assert dialog._can_cancel is False

    def test_escape_returns_none_when_cancellable(self):
        """With can_cancel=True, Escape cancels and returns None."""
        dialog = SettingsDialog(title="Settings", items=[])
        assert dialog.escape_result is None

    def test_escape_disabled_when_not_cancellable(self):
        """With can_cancel=False, Escape is disabled entirely.

        Regression: escape_result used to be the string "close", which
        leaked through DialogManager.show() as the return value of
        show_settings_dialog() — violating its dict-or-None contract
        (callers iterating result.items() would crash on a str)."""
        dialog = SettingsDialog(title="Settings", items=[], can_cancel=False)
        assert dialog.escapable is False
        assert dialog.escape_result is None


class TestSettingsDialogLayout:
    """Tests for SettingsDialog layout."""

    def test_build_body_returns_hsplit(self):
        """build_body returns an HSplit of control containers."""
        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        body = dialog.build_body()

        # Should be an HSplit of control containers
        assert isinstance(body, HSplit)

    def test_build_body_creates_controls(self):
        """build_body creates individual SettingControl instances."""
        from thinking_prompt.settings_dialog import (
            CheckboxControl, InlineSelectControl, TextControl
        )

        items = [
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            CheckboxItem(key="stream", label="Stream", default=True),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()

        assert len(dialog._controls) == 3
        assert isinstance(dialog._controls[0], InlineSelectControl)
        assert isinstance(dialog._controls[1], CheckboxControl)
        assert isinstance(dialog._controls[2], TextControl)


class TestTextControlPasswordMasking:
    """Edit-mode rendering of password fields must not expose the buffer."""

    def _get_buffer_control(self, control: TextControl) -> BufferControl:
        bc = control._buffer_window.content
        assert isinstance(bc, BufferControl)
        return bc

    def test_password_text_item_uses_password_processor_in_edit_mode(self):
        item = TextItem(key="api_key", label="API Key", password=True)
        control = TextControl(item)

        bc = self._get_buffer_control(control)
        processors = bc.input_processors or []
        assert any(isinstance(p, PasswordProcessor) for p in processors), (
            "BufferControl for password=True TextItem must include "
            "PasswordProcessor; got input_processors="
            f"{processors!r}"
        )

    def test_non_password_text_item_has_no_password_processor(self):
        item = TextItem(key="username", label="Username", password=False)
        control = TextControl(item)

        bc = self._get_buffer_control(control)
        processors = bc.input_processors or []
        assert not any(isinstance(p, PasswordProcessor) for p in processors)


class TestSessionIntegration:
    """Tests for session.show_settings_dialog integration."""

    def test_settings_items_exported(self):
        """Settings item classes are exported from package."""
        from thinking_prompt import (
            SettingsItem,
            DropdownItem,
            InlineSelectItem,
            CheckboxItem,
            TextItem,
            SettingsDialog,
        )
        # Just check they're importable
        assert SettingsItem is not None
        assert DropdownItem is not None
        assert InlineSelectItem is not None
        assert CheckboxItem is not None
        assert TextItem is not None
        assert SettingsDialog is not None


class TestSettingControl:
    """Tests for the SettingControl base class."""

    def test_setting_control_stores_item_and_value(self):
        """SettingControl stores item reference and initial value."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream", default=True)
        control = CheckboxControl(item)

        assert control.item is item
        assert control.value is True

    def test_setting_control_is_not_editing_by_default(self):
        """SettingControl starts in view mode."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream", default=False)
        control = CheckboxControl(item)

        assert control.is_editing is False


class TestCheckboxControl:
    """Tests for CheckboxControl."""

    def test_checkbox_toggle(self):
        """Checkbox toggles value."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream", default=False)
        control = CheckboxControl(item)

        assert control.value is False
        control.toggle()
        assert control.value is True
        control.toggle()
        assert control.value is False

    def test_checkbox_renders_label_and_value(self):
        """Checkbox renders label and true/false value."""
        from thinking_prompt.settings_dialog import CheckboxControl

        item = CheckboxItem(key="stream", label="Stream Output", default=True)
        control = CheckboxControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Stream Output" in text
        assert "true" in text


class TestInlineSelectControl:
    """Tests for InlineSelectControl."""

    def test_inline_select_cycle_forward(self):
        """InlineSelect cycles through options forward."""
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="model", label="Model", options=["a", "b", "c"], default="a")
        control = InlineSelectControl(item)

        assert control.value == "a"
        control.cycle(1)
        assert control.value == "b"
        control.cycle(1)
        assert control.value == "c"
        control.cycle(1)
        assert control.value == "c"  # clamped at end

    def test_inline_select_cycle_backward(self):
        """InlineSelect cycles through options backward."""
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="model", label="Model", options=["a", "b", "c"], default="a")
        control = InlineSelectControl(item)

        control.cycle(-1)
        assert control.value == "a"  # clamped at start

    @pytest.mark.parametrize("default", [None, "not-an-option"])
    @pytest.mark.parametrize("delta", [1, -1])
    def test_first_press_without_selection_selects_first_option(self, default, delta):
        """With no current selection (no default, or a default that isn't
        an option), the first press selects the first option instead of
        skipping over it."""
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="m", label="M", options=["a", "b", "c"], default=default)
        control = InlineSelectControl(item)

        control.cycle(delta)
        assert control.value == "a"

    def test_untouched_select_without_default_is_not_a_change(self):
        """No default means "unset": leaving it alone reports no change."""
        dialog = SettingsDialog(
            title="S", items=[InlineSelectItem(key="m", label="M", options=["a", "b"])]
        )
        assert dialog._get_changed_values() == {}

    def test_inline_select_renders_label_and_value(self):
        """InlineSelect renders label and current option."""
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="model", label="Model", options=["gpt-4", "gpt-3.5"], default="gpt-4")
        control = InlineSelectControl(item)

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
        from thinking_prompt.settings_dialog import InlineSelectControl

        item = InlineSelectItem(key="m", label="M", options=["a", "b", "c"], default="b")
        line = InlineSelectControl(item).create_content(width=40, height=1).get_line(0)

        assert "".join(t for _, t in line).endswith("◀ b ▶")
        assert "class:select-arrow" in _style_of(line, "◀")
        assert "class:select-arrow" in _style_of(line, "▶")
        assert "class:select-arrow" not in _style_of(line, "b")

    def test_dropdown_arrow(self):
        from thinking_prompt.settings_dialog import DropdownControl

        item = DropdownItem(key="m", label="M", options=["a", "b"], default="b")
        line = DropdownControl(item).create_content(width=40, height=1).get_line(0)

        assert "".join(t for _, t in line).endswith("b ▼")
        assert "class:select-arrow" in _style_of(line, "▼")
        assert "class:select-arrow" not in _style_of(line, "b")


class TestTextControl:
    """Tests for TextControl."""

    def test_text_control_enter_edit_mode(self):
        """TextControl enters edit mode and populates buffer."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        assert control.is_editing is False
        control.enter_edit_mode()
        assert control.is_editing is True
        assert control._buffer.text == "Alice"

    def test_text_control_confirm_edit(self):
        """TextControl confirm saves buffer value."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        control.enter_edit_mode()
        control._buffer.text = "Bob"
        control.confirm_edit()

        assert control.is_editing is False
        assert control.value == "Bob"

    def test_text_control_cancel_edit(self):
        """TextControl cancel restores original value."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        control.enter_edit_mode()
        control._buffer.text = "Bob"
        control.cancel_edit()

        assert control.is_editing is False
        assert control.value == "Alice"  # restored

    def test_text_control_renders_value(self):
        """TextControl renders label and value in view mode."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "Name" in text
        assert "Alice" in text

    def test_text_control_renders_empty_placeholder(self):
        """TextControl shows (empty) for empty value."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="name", label="Name", default="")
        control = TextControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "(empty)" in text

    def test_text_control_renders_password_masked(self):
        """TextControl masks password values."""
        from thinking_prompt.settings_dialog import TextControl

        item = TextItem(key="api_key", label="API Key", default="sk-secret", password=True)
        control = TextControl(item)

        content = control.create_content(width=50, height=1)
        line = content.get_line(0)
        text = "".join(t[1] for t in line)

        assert "sk-secret" not in text
        assert "••••••" in text

    def test_text_control_container_switches_in_edit_mode(self):
        """TextControl container returns different content in edit mode."""
        from thinking_prompt.settings_dialog import TextControl
        from prompt_toolkit.layout import DynamicContainer

        item = TextItem(key="name", label="Name", default="Alice")
        control = TextControl(item)

        container = control.get_container()
        # Should be a DynamicContainer
        assert isinstance(container, DynamicContainer)


class TestShowSettingsDialog:
    """Tests for session.show_settings_dialog method."""

    def test_session_has_show_settings_dialog_method(self):
        """ThinkingPromptSession has show_settings_dialog method."""
        from thinking_prompt import ThinkingPromptSession
        assert hasattr(ThinkingPromptSession, 'show_settings_dialog')


class TestSettingsDialogRefactored:
    """Tests for refactored SettingsDialog using individual controls."""

    def test_settings_dialog_creates_controls(self):
        """SettingsDialog creates SettingControl instances."""
        from thinking_prompt.settings_dialog import (
            CheckboxControl, InlineSelectControl, TextControl
        )

        items = [
            CheckboxItem(key="stream", label="Stream", default=True),
            InlineSelectItem(key="model", label="Model", options=["a", "b"], default="a"),
            TextItem(key="name", label="Name", default="test"),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        dialog.build_body()

        assert len(dialog._controls) == 3
        assert isinstance(dialog._controls[0], CheckboxControl)
        assert isinstance(dialog._controls[1], InlineSelectControl)
        assert isinstance(dialog._controls[2], TextControl)

    def test_settings_dialog_build_body_returns_hsplit(self):
        """build_body returns HSplit of control containers."""
        items = [
            CheckboxItem(key="stream", label="Stream", default=True),
        ]
        dialog = SettingsDialog(title="Settings", items=items)
        body = dialog.build_body()

        assert isinstance(body, HSplit)


class TestSettingsDialogIsADialog:
    def test_options_pass_through_to_dialog(self):
        from thinking_prompt.dialog import Dialog

        d = SettingsDialog(title="S", items=[], width=40, max_height=15, can_cancel=False)
        assert isinstance(d, Dialog)
        assert (d.title, d.width, d.max_height, d.escapable) == ("S", 40, 15, False)

    @pytest.mark.parametrize(
        "can_cancel,labels", [(True, ["Save", "Cancel"]), (False, ["Done"])]
    )
    def test_buttons_are_button_configs(self, can_cancel, labels):
        from thinking_prompt.dialog import ButtonConfig

        buttons = SettingsDialog(title="S", items=[], can_cancel=can_cancel).get_buttons()
        assert all(isinstance(b, ButtonConfig) for b in buttons)
        assert [b.text for b in buttons] == labels


class TestSettingsDialogOptions:
    """0.4 removes styles= (it was never read) and makes the layout options
    keyword-only: before 0.4 the fourth positional was styles, so a stale
    positional call must fail instead of shifting into width/max_height."""

    def test_styles_is_gone(self):
        with pytest.raises(TypeError, match="styles"):
            SettingsDialog(title="S", items=[], styles={})

    def test_layout_options_are_keyword_only(self):
        with pytest.raises(TypeError):
            SettingsDialog("S", [], True, None)

    @pytest.fixture
    def capturing_session(self, monkeypatch):
        """A session whose show_settings_dialog() records the dialog instead
        of opening it (there is no running app to answer it)."""
        from thinking_prompt import ThinkingPromptSession

        session = ThinkingPromptSession()
        shown: list = []

        async def capture(dialog):
            shown.append(dialog)

        monkeypatch.setattr(session._dialogs, "show", capture)
        return session, shown

    async def test_session_helper_passes_options_through(self, capturing_session):
        session, shown = capturing_session
        await session.show_settings_dialog("S", [], False, width=40, max_height=15, align_values=24)

        (dialog,) = shown
        assert dialog._align_values == 24
        assert (dialog.title, dialog.width, dialog.max_height) == ("S", 40, 15)
        assert dialog.escapable is False

    def test_height_is_gone(self):
        with pytest.raises(TypeError):
            SettingsDialog(title="S", items=[], height=15)

    async def test_top_is_gone(self, capturing_session):
        session, _ = capturing_session
        with pytest.raises(TypeError, match="top"):
            SettingsDialog(title="S", items=[], top=1)
        with pytest.raises(TypeError, match="top"):
            await session.show_settings_dialog("S", [], top=1)

    async def test_session_helper_rejects_height(self, capturing_session):
        session, shown = capturing_session
        with pytest.raises(TypeError):
            await session.show_settings_dialog("S", [], height=15)
        assert shown == []

    async def test_session_helper_rejects_styles(self, capturing_session):
        session, shown = capturing_session
        with pytest.raises(TypeError, match="styles"):
            await session.show_settings_dialog("S", [], styles={})
        assert shown == []

    async def test_session_helper_layout_options_are_keyword_only(self, capturing_session):
        session, shown = capturing_session
        with pytest.raises(TypeError):
            await session.show_settings_dialog("S", [], True, None)
        assert shown == []

    async def test_session_helper_passes_placement(self, capturing_session):
        session, shown = capturing_session
        await session.show_settings_dialog("S", [], placement="inline")
        assert shown[0].placement == "inline"


def _bindings(kb, key):
    return kb.get_bindings_for_keys((key,))


def _inline_dropdown(**item) -> DropdownControl:
    control = DropdownControl(DropdownItem(**item))
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
            (lambda: CheckboxControl(CheckboxItem(key="c", label="Label", default=True)),
             "true", "field-value-true"),
            (lambda: CheckboxControl(CheckboxItem(key="c", label="Label")),
             "false", "field-value-false"),
            (lambda: InlineSelectControl(InlineSelectItem(key="s", label="Label", options=["a", "b"], default="a")),
             "a", "field-value"),
            (lambda: _inline_dropdown(key="d", label="Label", options=["a", "b"], default="a"),
             "a", "field-value"),
            (lambda: DropdownControl(DropdownItem(key="d", label="Label", options=["a", "b"], default="a")),
             "a", "field-value"),
            (lambda: TextControl(TextItem(key="t", label="Label", default="bob")),
             "bob", "field-value"),
            (lambda: TextControl(TextItem(key="t", label="Label")),
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
        control = CheckboxControl(CheckboxItem(key="c", label="Label", description="Says more"))
        suffix = "-selected" if selected else ""
        assert _line(control, selected, row=1) == [("", "  "), (f"class:field-desc{suffix}", "Says more")]

    @pytest.mark.parametrize("selected", [False, True], ids=["idle", "selected"])
    def test_a_lists_label_and_description(self, selected):
        control = OptionsControl(
            ChecklistItem(key="t", label="Label", description="Says more", options=["a"])
        )
        suffix = "-selected" if selected else ""
        assert _line(control, selected) == [("", "  "), (f"class:field-label{suffix}", "Label")]
        assert _line(control, selected, row=1) == [("", "  "), (f"class:field-desc{suffix}", "Says more")]

    async def test_a_description_stays_under_the_edit_field(self):
        control = TextControl(TextItem(key="t", label="Name", description="Says more", default="bob"))
        control.enter_edit_mode()
        row, description = _drawn(control.get_container(), 30, height=2)
        assert _field(row)
        assert _text(description).rstrip() == "  Says more"
        assert all("class:field-desc-selected" in style for _, style in description[2:11])

    @pytest.mark.parametrize(
        "make",
        [
            lambda: InlineSelectControl(InlineSelectItem(key="s", label="S", options=["a", "b", "c"], default="b")),
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
        from thinking_prompt.settings_dialog import CheckboxControl

        control = CheckboxControl(CheckboxItem(key="s", label="Stream"))
        (row,) = control._build_setting_row(40, _RowValue("true", "", 4), True)
        assert row[0] == ("class:field-indicator", "❯ ")

    def test_inline_dropdown_is_a_selector_without_a_popup(self):
        from thinking_prompt.settings_dialog import DropdownControl

        control = DropdownControl(DropdownItem(key="m", label="Model", options=["a", "b", "c"], default="b"))
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
        from thinking_prompt.settings_dialog import DropdownControl

        control = DropdownControl(DropdownItem(key="m", label="Model", options=["a", "b"], default="b"))
        text = "".join(t for _, t in control.create_content(40, 1).get_line(0))
        assert text.endswith("b ▼")
        assert control.hints == frozenset()

    def test_inline_body_has_no_popups_and_leaves_arrows_to_the_dialog(self):
        dialog = SettingsDialog(
            "S",
            [DropdownItem(key="m", label="M", options=["a", "b"]), CheckboxItem(key="c", label="C")],
            placement="inline",
        )
        dialog._placement = "inline"  # as show_dialog() resolves it
        body = dialog.build_body()
        assert isinstance(body, HSplit)  # no FloatContainer for dropdown menus
        assert _bindings(body.key_bindings, Keys.Down) == []
        assert _bindings(body.key_bindings, Keys.ControlS) != []

    def test_box_body_walks_settings_with_arrows(self):
        dialog = SettingsDialog("S", [CheckboxItem(key="a", label="A"), CheckboxItem(key="b", label="B")])
        body = dialog.build_body()
        assert _bindings(body.key_bindings, Keys.Down) != []
        assert len(dialog._stops()) == 2

    def test_is_editing_follows_the_controls(self):
        dialog = SettingsDialog("S", [TextItem(key="t", label="T")])
        assert dialog._is_editing() is False
        dialog._controls[0].enter_edit_mode()
        assert dialog._is_editing() is True

    def test_placement_goes_to_the_dialog(self):
        assert SettingsDialog("S", [], placement="inline").placement == "inline"
        assert SettingsDialog("S", []).placement is None
        with pytest.raises(ValueError, match="placement must be"):
            SettingsDialog("S", [], placement="side")


class TestOptionItems:
    """Check lists and radio lists in the settings form, one option per line."""

    def test_checklist_value_is_the_checked_options_in_option_order(self):
        from thinking_prompt.settings_dialog import ChecklistItem, OptionsControl

        control = OptionsControl(ChecklistItem(key="t", label="Tools", options=["a", "b", "c"], default=("c", "a")))
        assert control.value == ["a", "c"]

    def test_radio_value(self):
        from thinking_prompt.settings_dialog import OptionsControl, RadioItem

        assert OptionsControl(RadioItem(key="m", label="Mode", options=["x", "y"], default="y")).value == "y"
        assert OptionsControl(RadioItem(key="m", label="Mode", options=["x", "y"])).value is None

    def test_one_stop_per_option_and_the_label_takes_no_focus(self):
        from thinking_prompt.settings_dialog import ChecklistItem, OptionsControl

        control = OptionsControl(ChecklistItem(key="t", label="Tools", options=["a", "b"]))
        assert len(control.get_stops()) == 2
        assert not control.is_focusable()
        assert control.row_count == 3

    def test_change_detection(self):
        from thinking_prompt.settings_dialog import ChecklistItem, RadioItem

        dialog = SettingsDialog("S", [
            ChecklistItem(key="t", label="T", options=["a", "b"], default=("b",)),
            RadioItem(key="m", label="M", options=["x", "y"]),
        ])
        assert dialog._get_changed_values() == {}
        tools, mode = dialog._controls
        tools._group.choose("a")
        mode._group.choose("x")
        assert dialog._get_changed_values() == {"t": ["a", "b"], "m": "x"}

    def test_box_cursor_stops_on_each_option(self):
        from thinking_prompt.settings_dialog import ChecklistItem

        dialog = SettingsDialog("S", [
            CheckboxItem(key="c", label="C"),
            ChecklistItem(key="t", label="T", options=["a", "b"]),
        ])
        assert len(dialog._stops()) == 3

    def test_exported(self):
        from thinking_prompt import ChecklistItem, RadioItem

        assert ChecklistItem and RadioItem


@pytest.mark.parametrize(
    "make,widest",
    [
        (lambda: CheckboxControl(CheckboxItem(key="a", label="A")), len("false")),
        (
            lambda: InlineSelectControl(
                InlineSelectItem(key="a", label="A", options=["S", "Medium", "XL"])
            ),
            len("◀ Medium ▶"),
        ),
        (
            lambda: DropdownControl(DropdownItem(key="a", label="A", options=["x"], width=20)),
            20 + len(" ▼"),
        ),
        (
            lambda: InlineSelectControl(
                InlineSelectItem(key="a", label="A", options=["S", "M"], default="Not an option")
            ),
            len("◀ Not an option ▶"),
        ),
        (lambda: TextControl(TextItem(key="a", label="A", edit_width=12)), 12),
        (lambda: TextControl(TextItem(key="a", label="A", edit_width=5)), len("(empty)")),
        (
            lambda: TextControl(TextItem(key="a", label="A", default="a long default", edit_width=5)),
            len("a long default"),
        ),
        (lambda: OptionsControl(ChecklistItem(key="a", label="A", options=["x"])), 0),
    ],
)
def test_widest_value(make, widest):
    """The most columns a setting's value takes in full: showing any of its
    options, or what it shows now."""
    assert make().widest_value() == widest


def test_an_inline_dropdowns_widest_value_is_its_widest_option():
    control = DropdownControl(DropdownItem(key="a", label="A", options=["x", "Longest"], width=20))
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
    (lambda: CheckboxControl(CheckboxItem(key="c", label="Stream", default=True)),
     "Stream", "true", "true"),
    (lambda: InlineSelectControl(InlineSelectItem(key="s", label="Size", options=["a", "b", "c"], default="b")),
     "Size", "◀ b ▶", "◀ b ▶"),
    (lambda: DropdownControl(DropdownItem(key="d", label="Model", options=["gpt", "o1"], default="o1")),
     "Model", "o1".ljust(15) + " ▼", "o1 ▼"),
    (lambda: TextControl(TextItem(key="t", label="Name", default="bob")),
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
        row = _row(CheckboxControl(CheckboxItem(key="c", label="A very long label indeed")), 10)
        assert row[:10] == "  A very… "
        assert row[10:] == "false"

    def test_a_narrow_row_puts_the_value_at_the_right_edge(self):
        row = _row(CheckboxControl(CheckboxItem(key="c", label="Streaming output")), 30, width=20)
        assert row.endswith("false") and len(row) == 19
        assert "…" in row

    def test_fields_are_padded_in_terminal_columns(self):
        """Wide characters take two columns: a dropdown's ▼ lines up whatever
        its value, and a text value takes its edit_width."""

        def mark(value: str) -> int:
            item = DropdownItem(key="d", label="Model", options=["日本語モデル", "beta"], default=value)
            row = _row(DropdownControl(item), 20)
            return get_cwidth(row[:row.index("▼")])

        assert mark("日本語モデル") == mark("beta") == 20 + 15 + 1
        text = _row(TextControl(TextItem(key="t", label="Name", default="名前です")), 20)
        assert get_cwidth(text) == 20 + 15

    def test_a_value_reaching_the_rows_last_column_falls_back_too(self):
        """Values end where "right" ends them, a column short of the row's
        right edge: a value fits at its column if it ends there."""
        control = CheckboxControl(CheckboxItem(key="c", label="Stream"))
        assert _row(control, 14, width=20)[14:] == "false"
        row = _row(control, 15, width=20)
        assert row.endswith("false") and len(row) == 19

    @staticmethod
    def _menu_open(width: int, **kwargs) -> list[str]:
        """A box form's dropdown, its menu open, drawn ``width`` columns wide."""
        items = [
            DropdownItem(key="d", label="Model", options=["alpha", "beta"], default="beta"),
            *(CheckboxItem(key=k, label=k) for k in ("a", "b", "c")),
        ]
        dialog = SettingsDialog("S", items, **kwargs)
        body = dialog.build_body()
        dialog._controls[0].enter_edit_mode()
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
            DropdownItem(key="d", label=label, options=["alpha", "beta"], default="beta"),
            *(CheckboxItem(key=k, label=k) for k in ("a", "b", "c")),
        ]
        dialog = SettingsDialog("S", items, **kwargs)
        body = dialog.build_body()
        dialog._controls[0].enter_edit_mode()
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
        control = TextControl(TextItem(key="t", label="Name", default="bob"))
        control.set_value_column(_ValueColumn(20))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 60)
        assert _field(row) == list(range(20, 35))
        assert _text(row)[20:23] == "bob"

    async def test_while_editing_a_long_label_is_cut_before_the_field(self):
        control = TextControl(TextItem(key="t", label="A rather long label", default="bob"))
        control.set_value_column(_ValueColumn(12))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 60)
        assert _text(row)[:15] == "❯ A rather… bob"

    async def test_a_narrow_row_keeps_the_text_field_where_the_value_was(self):
        """Too narrow for the column, the field ends at the row's right edge,
        as the value did, and the label is cut before it as it was."""
        control = TextControl(TextItem(key="t", label="A rather long label", default="bob"))
        shown = _row(control, 30, width=36)
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 36)
        assert _field(row) == list(range(36 - 1 - 15, 36 - 1))
        assert _text(row)[2:23] == shown[2:23] == "A rather long la… bob"

    async def test_without_a_column_the_text_field_is_at_the_right_edge(self):
        control = TextControl(TextItem(key="t", label="Name"))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 40)
        assert _field(row) == list(range(39 - 15, 39))


def _dropdown(label: str = "Model for summaries", default: str = "o1") -> DropdownControl:
    return DropdownControl(DropdownItem(key="d", label=label, options=["gpt-4o", "o1"], default=default))


def _selector(label: str = "Model name", options=("a", "gpt-4o-mini", "z"), default="gpt-4o-mini"):
    return InlineSelectControl(InlineSelectItem(key="s", label=label, options=list(options), default=default))


def _text_setting(label: str = "Display name", default: str = "bob") -> TextControl:
    return TextControl(TextItem(key="t", label=label, default=default))


class TestRowsShortOfWidth:
    """A label/value row gives way in order: the value at its column, in full;
    at the right edge, the label cut; the label at 3 columns and the field
    shrunk; the value cut. Its decoration stays."""

    # Checkbox: no padding, no decoration.
    def test_checkbox_in_full_at_the_column(self):
        control = CheckboxControl(CheckboxItem(key="c", label="Stream responses", default=True))
        assert _row(control, 20, width=30) == "  Stream responses  true"

    def test_checkbox_at_the_right_edge_with_a_cut_label(self):
        control = CheckboxControl(CheckboxItem(key="c", label="Stream responses", default=True))
        assert _row(control, 20, width=20) == "  Stream resp… true"
        assert _row(control, None, width=20) == "  Stream resp… true"

    def test_checkbox_with_a_3_column_label_cuts_the_value(self):
        control = CheckboxControl(CheckboxItem(key="c", label="Stream responses", default=True))
        assert _row(control, None, width=8) == "  St… …"

    def test_a_label_of_3_columns_or_fewer_is_never_cut(self):
        for label in ("Abc", "Go", "A"):
            control = CheckboxControl(CheckboxItem(key="c", label=label, default=True))
            assert _row(control, None, width=8).startswith(f"  {label} ")
            assert _row(control, 6, width=8).startswith(f"  {label} ")

    def test_a_floor_row_is_clipped_without_raising(self):
        control = CheckboxControl(CheckboxItem(key="c", label="Stream responses", default=True))
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
        control = CheckboxControl(CheckboxItem(key="c", label="設定モデル名前", default=True))
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
        control = TextControl(TextItem(key="t", label="Display name", default=default, password=password))
        control.set_value_column(_fixed(column))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 14)
        assert _field(row) == list(range(5, 13))

    @pytest.mark.parametrize("password", [False, True])
    async def test_a_long_value_gets_exactly_edit_width_in_a_wide_row(self, password):
        control = TextControl(
            TextItem(key="t", label="Name", default="a value of nineteen", password=password)
        )
        control.set_value_column(_ValueColumn(10))
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 60)
        assert _field(row) == list(range(10, 25))

    async def test_a_small_edit_width_is_its_own_minimum(self):
        control = TextControl(TextItem(key="t", label="Display name", default="bob", edit_width=5))
        control.set_value_column(None)
        control.enter_edit_mode()
        (row,) = _drawn(control.get_container(), 12)
        assert len(_field(row)) == 5


class TestAlignValues:
    @staticmethod
    def _column(items, shown="box", **kwargs):
        dialog = SettingsDialog("S", items, **kwargs)
        dialog._placement = shown  # as show_dialog() resolves it
        dialog.build_body()
        return dialog._controls[0]._value_column

    def test_labels_start_values_after_the_longest_label(self):
        items = [
            CheckboxItem(key="a", label="Stream"),
            TextItem(key="b", label="API key"),
            ChecklistItem(key="c", label="A much longer check list label", options=["x"]),
        ]
        assert self._column(items).at(60) == 2 + len("API key") + 2

    def test_labels_are_measured_in_terminal_columns(self):
        items = [CheckboxItem(key="a", label="設定"), CheckboxItem(key="b", label="abc")]
        assert self._column(items).at(60) == 2 + 4 + 2

    def test_right_and_a_column(self):
        items = [CheckboxItem(key="a", label="Stream", description="Show tokens as they arrive")]
        assert self._column(items, align_values="right") is None
        column = self._column(items, align_values=24)
        assert (column.at(60), column.at(20)) == (24, 24)  # a set column doesn't move

    def test_values_clear_the_longest_description(self):
        items = [
            CheckboxItem(key="a", label="Stream", description="Show tokens as they arrive"),
            TextItem(key="b", label="API key", edit_width=10),
        ]
        assert self._column(items).at(80) == 2 + len("Show tokens as they arrive") + 2

    def test_a_description_too_long_for_the_values_runs_under_them(self):
        items = [
            CheckboxItem(key="a", label="Stream", description="x" * 50),
            TextItem(key="b", label="API key", edit_width=20),
        ]
        column = self._column(items)
        # As far right as the widest value (the 20-column field) still fits
        # before the row's last column, never left of the labels.
        assert column.at(60) == 60 - 1 - 20
        assert column.at(200) == 2 + 50 + 2
        assert column.at(20) == 2 + len("API key") + 2

    def test_an_inline_dropdown_is_measured_as_the_selector_it_shows(self):
        items = [
            DropdownItem(key="m", label="Model", description="d" * 60, options=["a", "b"], width=30),
        ]
        # Inline, the value is "◀ a ▶"; in a box, a 30-column menu field and " ▼".
        assert self._column(items, shown="inline").at(80) == 2 + 60 + 2
        assert self._column(items, shown="box").at(80) == 80 - 1 - (30 + 2)

    def test_list_labels_and_descriptions_dont_move_the_values(self):
        items = [
            CheckboxItem(key="a", label="Stream"),
            ChecklistItem(key="c", label="Tools", description="y" * 40, options=["x"]),
        ]
        assert self._column(items).at(80) == 2 + len("Stream") + 2

    def test_a_form_of_lists_only_needs_no_column(self):
        dialog = SettingsDialog("S", [ChecklistItem(key="c", label="Tools", options=["x", "y"])])
        dialog.build_body()

    @pytest.mark.parametrize("bad", [3, 0, -1, "left", True, 4.5])
    def test_align_values_is_checked(self, bad):
        with pytest.raises(ValueError, match="align_values"):
            SettingsDialog("S", [], align_values=bad)

    def test_the_smallest_column(self):
        assert SettingsDialog("S", [], align_values=4)._align_values == 4
