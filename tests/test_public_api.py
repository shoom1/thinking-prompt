"""The public API: thinking_prompt's ``__all__`` and the members of what it
names. From 0.5.0 a minor series keeps this stable, so a change here is made
on purpose."""
from __future__ import annotations

import dataclasses
import inspect
from typing import Callable

import pytest
from prompt_toolkit.application import Application

import thinking_prompt
from thinking_prompt import (
    AppInfo,
    ChoiceField,
    DropdownField,
    RadioField,
    SelectField,
    TextField,
    ThinkingBox,
    ThinkingPromptSession,
    ThinkingPromptStyles,
)

PUBLIC = {
    "ThinkingPromptSession",
    "AppInfo",
    "ThinkingPromptStyles",
    "ThinkingBox",
    "ContentCallback",
    "ContentFormat",
    "Overflow",
    "Placement",
    "InputHandler",
    "AlignValues",
    "Dialog",
    "ButtonConfig",
    "Field",
    "TextField",
    "CheckboxField",
    "SelectField",
    "DropdownField",
    "ChecklistField",
    "RadioField",
    "ChoiceField",
    "Spinner",
    "rich_to_ansi",
}


def test_all_names_the_public_api():
    assert sorted(thinking_prompt.__all__) == sorted(PUBLIC)


def test_each_public_name_imports_from_the_package():
    for name in thinking_prompt.__all__:
        assert hasattr(thinking_prompt, name), name


@pytest.mark.parametrize("name", ["StreamingContent", "ThinkingHeader", "DEFAULT_STYLES"])
def test_building_blocks_arent_exported(name: str):
    assert not hasattr(thinking_prompt, name)


def test_there_are_no_default_styles_to_share():
    """Each session makes its own ThinkingPromptStyles(): one shared,
    mutable instance would let a tweak restyle every session."""
    from thinking_prompt import styles

    assert not hasattr(styles, "DEFAULT_STYLES")


def test_align_values_is_the_dialogs_type():
    from thinking_prompt.fields import AlignValues

    assert thinking_prompt.AlignValues == AlignValues


def test_a_boxs_text_is_read_only_and_has_one_name():
    assert ThinkingBox.text.fset is None
    assert not hasattr(ThinkingBox, "get_content")


def test_the_session_exposes_its_application_and_not_its_parts():
    session = ThinkingPromptSession()
    assert isinstance(session.app, Application)
    assert not hasattr(session, "layout")
    assert not hasattr(session, "default_buffer")


def test_styles_have_no_fields_for_widgets_nothing_draws():
    """prompt_toolkit's RadioList and CheckboxList: the form fields replaced them."""
    gone = {"radio_list", "radio_selected", "checkbox_list", "checkbox_selected"}
    assert not gone & {field.name for field in dataclasses.fields(ThinkingPromptStyles)}
    classes = set(ThinkingPromptStyles().to_style_dict())
    assert not {"radio-list", "radio-selected", "checkbox-list", "checkbox-selected"} & classes


def test_styles_convert_to_a_prompt_toolkit_style_only():
    assert hasattr(ThinkingPromptStyles, "to_style")
    assert not hasattr(ThinkingPromptStyles, "to_rich_theme_dict")


@pytest.mark.parametrize(
    ("owner", "member"),
    [
        (ThinkingPromptSession, "set_status"),  # status_text takes all kinds of text
        (ThinkingPromptSession, "add_message"),  # add_system(); add_response()
    ],
)
def test_one_name_per_thing(owner: type, member: str):
    assert not hasattr(owner, member)


def _parameters(func: Callable[..., object]) -> list[str]:
    return [name for name in inspect.signature(func).parameters if name != "self"]


@pytest.mark.parametrize(
    ("func", "names"),
    [
        (
            ThinkingPromptSession.__init__,
            [
                "message", "app_info", "theme", "history", "completer",
                "complete_while_typing", "completions_menu_height", "editing_mode",
                "enable_status_bar", "status_text", "expand_key", "thinking_max_lines",
                "thinking_title", "spinner", "spinner_position", "echo_input",
                "thinking_echo", "transcript_limit", "dialog_placement",
            ],
        ),
        (
            ThinkingPromptSession.start_thinking,
            ["content_callback", "title", "order", "max_lines", "content_format", "overflow"],
        ),
        (
            ThinkingPromptSession.thinking,
            ["title", "content_format", "echo", "order", "max_lines", "overflow"],
        ),
        (ThinkingBox.finish, ["echo"]),
        (
            ThinkingPromptSession.message_dialog,
            ["title", "text", "ok_text", "placement", "max_height"],
        ),
        (
            ThinkingPromptSession.yes_no_dialog,
            ["title", "text", "yes_text", "no_text", "placement", "max_height"],
        ),
        (
            ThinkingPromptSession.choice_dialog,
            ["title", "text", "options", "placement", "max_height"],
        ),
        (
            ThinkingPromptSession.dropdown_dialog,
            ["title", "text", "options", "default", "placement", "max_height"],
        ),
        (
            ThinkingPromptSession.checklist_dialog,
            ["title", "text", "options", "defaults", "placement", "max_height"],
        ),
    ],
    ids=[
        "session", "start_thinking", "thinking", "finish", "message_dialog",
        "yes_no_dialog", "choice_dialog", "dropdown_dialog", "checklist_dialog",
    ],
)
def test_parameter_names(func: Callable[..., object], names: list[str]):
    """One name per meaning: a session default for boxes is ``thinking_`` +
    the box's parameter, and the dialog helpers all take ``options``."""
    assert _parameters(func) == names


@pytest.mark.parametrize(
    ("field_class", "names"),
    [
        (TextField, ["key", "label", "description", "default", "password", "width"]),
        (
            DropdownField,
            ["key", "label", "description", "default", "options", "height", "width", "max_width"],
        ),
    ],
    ids=["TextField", "DropdownField"],
)
def test_a_fields_width_is_named_width(field_class: type, names: list[str]):
    assert [field.name for field in dataclasses.fields(field_class)] == names


@pytest.mark.parametrize("field_class", [SelectField, DropdownField, RadioField, ChoiceField])
def test_a_single_choice_fields_default_is_an_option_or_none(field_class: type):
    (default,) = [field for field in dataclasses.fields(field_class) if field.name == "default"]
    assert default.type == "str | None"


def test_printed_messages_are_styled_as_the_transcript():
    """The transcript is what the session printed; its styles say so."""
    assert "transcript" in {field.name for field in dataclasses.fields(ThinkingPromptStyles)}
    assert "history" not in {field.name for field in dataclasses.fields(ThinkingPromptStyles)}
    classes = set(ThinkingPromptStyles().to_style_dict())
    assert {"transcript", "transcript.error", "transcript.user-message"} <= classes
    assert not [name for name in classes if name.split(".")[0] == "history"]


def test_the_welcome_stays_a_customization_point():
    assert AppInfo(name="app", welcome_message="hi").get_welcome_content() == "hi"
