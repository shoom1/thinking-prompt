"""Form fields: the Field classes, their controls, and fields on a Dialog."""
from __future__ import annotations

import dataclasses

import pytest

import thinking_prompt
from thinking_prompt import (
    CheckboxField,
    ChecklistField,
    DropdownField,
    Field,
    RadioField,
    SelectField,
    TextField,
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
