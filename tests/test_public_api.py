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
from thinking_prompt import AppInfo, ThinkingBox, ThinkingPromptSession, ThinkingPromptStyles

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
    ],
    ids=["session", "start_thinking", "thinking", "finish"],
)
def test_parameter_names(func: Callable[..., object], names: list[str]):
    """A session default for boxes is ``thinking_`` + the box's parameter."""
    assert _parameters(func) == names


def test_the_welcome_stays_a_customization_point():
    assert AppInfo(name="app", welcome_message="hi").get_welcome_content() == "hi"
