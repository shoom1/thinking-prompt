"""Spinner: a thinking header's animation frames, with their speed."""
from __future__ import annotations

import dataclasses

import pytest

from thinking_prompt import AppInfo, Spinner

BRAILLE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class TestSpinner:
    def test_lives_in_its_own_module(self):
        from thinking_prompt.spinner import Spinner as defined

        assert Spinner is defined

    def test_holds_frames_and_interval(self):
        spinner = Spinner(("a", "b"), 0.25)
        assert spinner.frames == ("a", "b")
        assert spinner.interval == 0.25

    def test_the_interval_defaults_to_a_tenth_of_a_second(self):
        assert Spinner(("a", "b")).interval == 0.1

    def test_a_list_of_frames_is_kept_as_a_tuple(self):
        spinner = Spinner(["a", "b"])
        assert spinner.frames == ("a", "b")
        assert spinner == Spinner(("a", "b"))
        hash(spinner)

    def test_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            Spinner(("a", "b")).interval = 1.0  # type: ignore[misc]

    def test_no_frames_raises_and_points_at_none(self):
        with pytest.raises(ValueError, match="spinner=None"):
            Spinner(())

    @pytest.mark.parametrize("interval", [0, -0.1])
    def test_an_interval_that_is_not_positive_raises(self, interval):
        with pytest.raises(ValueError, match="interval"):
            Spinner(("a", "b"), interval)


class TestPresets:
    def test_dots_is_the_braille_spinner(self):
        assert Spinner(BRAILLE, 0.1) == Spinner.DOTS

    def test_line_is_ascii(self):
        assert Spinner(("-", "\\", "|", "/"), 0.13) == Spinner.LINE

    def test_ellipsis(self):
        assert Spinner((".  ", ".. ", "..."), 0.3) == Spinner.ELLIPSIS


class TestAppInfo:
    def test_the_default_is_dots_before_the_title(self):
        info = AppInfo(name="t")
        assert info.spinner == Spinner.DOTS
        assert info.spinner_position == "before"

    def test_none_turns_the_spinner_off(self):
        assert AppInfo(name="t", spinner=None).spinner is None

    def test_the_animation_fields_are_gone(self):
        names = {field.name for field in dataclasses.fields(AppInfo)}
        assert "thinking_animation" not in names
        assert "thinking_animation_position" not in names
