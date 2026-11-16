"""Spinner: a thinking header's animation frames, with their speed."""
from __future__ import annotations

import dataclasses
import math

import pytest

from thinking_prompt import Spinner

BRAILLE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class TestSpinner:
    def test_holds_frames_and_interval(self):
        spinner = Spinner(("a", "b"), interval=0.25)
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

    @pytest.mark.parametrize(
        "frames",
        ["abc", ("a", 1), {"a", "b"}, (f for f in ("a", "b")), 5],
        ids=["str", "not a str", "set", "generator", "int"],
    )
    def test_frames_are_a_list_or_tuple_of_strs(self, frames):
        """A str was taken as its letters, a set's order changes from run to
        run, and a frame that wasn't a str failed at the first draw."""
        with pytest.raises(ValueError, match="frames must be a sequence of str"):
            Spinner(frames)

    def test_no_frames_raises_and_points_at_none(self):
        with pytest.raises(ValueError, match="spinner=None"):
            Spinner(())

    @pytest.mark.parametrize("interval", ["0.1", None, True])
    def test_an_interval_that_is_not_a_number_raises(self, interval):
        with pytest.raises(ValueError, match="interval must be a number of seconds"):
            Spinner(("a", "b"), interval=interval)

    @pytest.mark.parametrize("interval", [0, -0.1, math.nan, math.inf])
    def test_an_interval_that_is_not_positive_and_finite_raises(self, interval):
        with pytest.raises(ValueError, match="interval must be positive and finite"):
            Spinner(("a", "b"), interval=interval)


class TestPresets:
    def test_dots_is_the_braille_spinner(self):
        assert Spinner(BRAILLE, interval=0.1) == Spinner.DOTS

    def test_line_is_ascii(self):
        assert Spinner(("-", "\\", "|", "/"), interval=0.13) == Spinner.LINE

    def test_ellipsis(self):
        assert Spinner((".  ", ".. ", "..."), interval=0.3) == Spinner.ELLIPSIS

