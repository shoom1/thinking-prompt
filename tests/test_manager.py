"""
Tests for ThinkingBoxManager and ManagedBox.
"""
from __future__ import annotations

import threading

import pytest

from thinking_prompt.manager import ManagedBox, ThinkingBoxManager
from thinking_prompt.thinking import ThinkingBoxControl
from thinking_prompt.layout import ThinkingHeader
from thinking_prompt.types import StreamingContent


# =============================================================================
# Creation tests
# =============================================================================


class TestCreation:
    """Test create_box returns ManagedBox with correct configuration."""

    def test_create_box_returns_managed_box(self):
        """create_box should return a ManagedBox instance."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "hello")
        assert isinstance(box, ManagedBox)

    def test_create_box_with_callback(self):
        """create_box with callback should use it in the control."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "test content")
        assert box.control.is_active
        assert box.control.content == "test content"

    def test_create_box_without_callback_creates_streaming_content(self):
        """create_box without callback should create StreamingContent internally."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box()
        assert box.streaming_content is not None
        assert isinstance(box.streaming_content, StreamingContent)
        assert box.control.is_active

    def test_create_box_without_callback_content_wired(self):
        """StreamingContent created internally should be wired to the control."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box()
        box.streaming_content.append("hello world")
        assert box.control.content == "hello world"

    def test_create_box_with_callback_no_streaming_content(self):
        """create_box with callback should not create StreamingContent."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x")
        assert box.streaming_content is None

    def test_create_box_with_title_creates_header(self):
        """create_box with title should create a ThinkingHeader."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x", title="Processing")
        assert box.header is not None
        assert isinstance(box.header, ThinkingHeader)
        assert box.header.text == "Processing"

    def test_create_box_without_title_no_header(self):
        """create_box without title should not create a header."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x")
        assert box.header is None

    def test_create_box_custom_id(self):
        """create_box with box_id should use the specified ID."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x", box_id="my-box")
        assert box.box_id == "my-box"

    def test_create_box_auto_id(self):
        """create_box without box_id should assign sequential IDs."""
        mgr = ThinkingBoxManager()
        box1 = mgr.create_box(lambda: "x")
        box2 = mgr.create_box(lambda: "y")
        assert box1.box_id == "box-0"
        assert box2.box_id == "box-1"

    def test_create_box_custom_order(self):
        """create_box with order should set it on the ManagedBox."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x", order=5)
        assert box.order == 5

    def test_create_box_default_order(self):
        """create_box without order should default to 0."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x")
        assert box.order == 0

    def test_create_box_custom_max_lines(self):
        """create_box with max_lines should override the default."""
        mgr = ThinkingBoxManager(default_max_lines=15)
        box = mgr.create_box(lambda: "x", max_lines=5)
        assert box.control.max_collapsed_lines == 5

    def test_create_box_default_max_lines(self):
        """create_box without max_lines should use the manager default."""
        mgr = ThinkingBoxManager(default_max_lines=20)
        box = mgr.create_box(lambda: "x")
        assert box.control.max_collapsed_lines == 20

    def test_create_box_content_format(self):
        """create_box with content_format should pass it to control.start()."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x", content_format="ansi")
        assert box.control.content_format == "ansi"

    def test_create_box_has_container(self):
        """create_box should build a container."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x")
        assert box.container is not None

    def test_create_box_seq_increments(self):
        """Each created box should have an incrementing seq."""
        mgr = ThinkingBoxManager()
        box1 = mgr.create_box(lambda: "a")
        box2 = mgr.create_box(lambda: "b")
        box3 = mgr.create_box(lambda: "c")
        assert box1.seq < box2.seq < box3.seq


# =============================================================================
# Active state tests
# =============================================================================


class TestActiveState:
    """Test has_active_boxes and active_count properties."""

    def test_no_boxes_not_active(self):
        """Manager with no boxes should not be active."""
        mgr = ThinkingBoxManager()
        assert not mgr.has_active_boxes
        assert mgr.active_count == 0

    def test_one_box_active(self):
        """Manager with one box should be active."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "x")
        assert mgr.has_active_boxes
        assert mgr.active_count == 1

    def test_multiple_boxes_active(self):
        """Manager with multiple boxes should report correct count."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.create_box(lambda: "c")
        assert mgr.has_active_boxes
        assert mgr.active_count == 3

    def test_removed_box_decreases_count(self):
        """Removing a box should decrease active_count."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.create_box(lambda: "b", box_id="b")
        mgr.remove_box("a")
        assert mgr.active_count == 1
        assert mgr.has_active_boxes

    def test_all_removed_not_active(self):
        """Manager with all boxes removed should not be active."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.remove_box("a")
        assert not mgr.has_active_boxes
        assert mgr.active_count == 0


# =============================================================================
# Removal tests
# =============================================================================


class TestRemoval:
    """Test remove_box behavior."""

    def test_remove_returns_content(self):
        """remove_box should return the content from control.finish()."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "final content", box_id="x")
        content, was_expanded, fmt = mgr.remove_box("x")
        assert content == "final content"

    def test_remove_returns_was_expanded(self):
        """remove_box should return was_expanded state."""
        mgr = ThinkingBoxManager()
        box = mgr.create_box(lambda: "x", box_id="x")
        box.control.expand()
        _, was_expanded, _ = mgr.remove_box("x")
        assert was_expanded

    def test_remove_returns_format(self):
        """remove_box should return the content format."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "x", box_id="x", content_format="ansi")
        _, _, fmt = mgr.remove_box("x")
        assert fmt == "ansi"

    def test_remove_decreases_count(self):
        """remove_box should decrease active_count."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.create_box(lambda: "b", box_id="b")
        assert mgr.active_count == 2
        mgr.remove_box("a")
        assert mgr.active_count == 1

    def test_remove_nonexistent_returns_empty(self):
        """remove_box for nonexistent box should return empty defaults."""
        mgr = ThinkingBoxManager()
        content, was_expanded, fmt = mgr.remove_box("nonexistent")
        assert content == ""
        assert not was_expanded
        assert fmt == "plain"


# =============================================================================
# finish_all tests
# =============================================================================


class TestFinishAll:
    """Test finish_all behavior."""

    def test_finish_all_returns_results(self):
        """finish_all should return a list of results for each box."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "content-a", box_id="a")
        mgr.create_box(lambda: "content-b", box_id="b")
        results = mgr.finish_all()
        assert len(results) == 2

    def test_finish_all_includes_box_id(self):
        """finish_all results should include box_id."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "x", box_id="alpha")
        results = mgr.finish_all()
        assert results[0][0] == "alpha"

    def test_finish_all_includes_content(self):
        """finish_all results should include content."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "my-content", box_id="a")
        results = mgr.finish_all()
        assert results[0][1] == "my-content"

    def test_finish_all_clears_boxes(self):
        """finish_all should leave the manager with no active boxes."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.create_box(lambda: "b", box_id="b")
        mgr.finish_all()
        assert mgr.active_count == 0
        assert not mgr.has_active_boxes

    def test_finish_all_includes_format(self):
        """finish_all should include content format in results."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "x", box_id="a", content_format="ansi")
        results = mgr.finish_all()
        # results are (box_id, content, was_expanded, format)
        assert results[0][3] == "ansi"

    def test_finish_all_empty_manager(self):
        """finish_all on empty manager should return empty list."""
        mgr = ThinkingBoxManager()
        results = mgr.finish_all()
        assert results == []


# =============================================================================
# Sorting tests
# =============================================================================


class TestSorting:
    """Test get_sorted_boxes ordering."""

    def test_sorted_by_order(self):
        """Boxes should be sorted by order."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "high", box_id="high", order=10)
        mgr.create_box(lambda: "low", box_id="low", order=1)
        mgr.create_box(lambda: "mid", box_id="mid", order=5)
        sorted_boxes = mgr.get_sorted_boxes()
        assert [b.box_id for b in sorted_boxes] == ["low", "mid", "high"]

    def test_sorted_by_seq_within_same_order(self):
        """Boxes with same order should be sorted by creation sequence."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "first", box_id="first", order=0)
        mgr.create_box(lambda: "second", box_id="second", order=0)
        mgr.create_box(lambda: "third", box_id="third", order=0)
        sorted_boxes = mgr.get_sorted_boxes()
        assert [b.box_id for b in sorted_boxes] == ["first", "second", "third"]

    def test_mixed_ordering(self):
        """Mixed order values with seq as tiebreaker."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a", order=2)
        mgr.create_box(lambda: "b", box_id="b", order=1)
        mgr.create_box(lambda: "c", box_id="c", order=2)
        mgr.create_box(lambda: "d", box_id="d", order=1)
        sorted_boxes = mgr.get_sorted_boxes()
        assert [b.box_id for b in sorted_boxes] == ["b", "d", "a", "c"]

    def test_get_container_returns_container(self):
        """get_container should return a valid container."""
        from prompt_toolkit.layout import HSplit, Window
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "x", box_id="x")
        container = mgr.get_container()
        # Should be an HSplit (or Window if empty)
        assert container is not None

    def test_get_container_empty_returns_zero_height(self):
        """get_container with no boxes should return a zero-height Window."""
        from prompt_toolkit.layout import Window
        mgr = ThinkingBoxManager()
        container = mgr.get_container()
        assert isinstance(container, Window)


# =============================================================================
# Expand / Collapse tests
# =============================================================================


class TestExpandCollapse:
    """Test toggle_all, expand_all, collapse_all."""

    def test_toggle_all_expands_when_collapsed(self):
        """toggle_all should expand all boxes when currently collapsed."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.create_box(lambda: "b", box_id="b")
        mgr.toggle_all()
        for box in mgr.get_sorted_boxes():
            assert box.control.is_expanded

    def test_toggle_all_collapses_when_expanded(self):
        """toggle_all should collapse all boxes when currently expanded."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.create_box(lambda: "b", box_id="b")
        mgr.expand_all()
        mgr.toggle_all()
        for box in mgr.get_sorted_boxes():
            assert not box.control.is_expanded

    def test_expand_all(self):
        """expand_all should expand all boxes."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.create_box(lambda: "b", box_id="b")
        mgr.expand_all()
        for box in mgr.get_sorted_boxes():
            assert box.control.is_expanded

    def test_collapse_all(self):
        """collapse_all should collapse all boxes."""
        mgr = ThinkingBoxManager()
        b1 = mgr.create_box(lambda: "a", box_id="a")
        b2 = mgr.create_box(lambda: "b", box_id="b")
        b1.control.expand()
        b2.control.expand()
        mgr.collapse_all()
        for box in mgr.get_sorted_boxes():
            assert not box.control.is_expanded

    def test_new_box_inherits_expanded_state(self):
        """A new box should inherit the current expanded state."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.expand_all()
        box2 = mgr.create_box(lambda: "b", box_id="b")
        assert box2.control.is_expanded

    def test_new_box_inherits_collapsed_state(self):
        """A new box created when collapsed should remain collapsed."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.collapse_all()
        box2 = mgr.create_box(lambda: "b", box_id="b")
        assert not box2.control.is_expanded

    def test_can_toggle_true_when_expanded(self):
        """can_toggle should return True when boxes are expanded."""
        mgr = ThinkingBoxManager()
        mgr.create_box(lambda: "a", box_id="a")
        mgr.expand_all()
        assert mgr.can_toggle()

    def test_can_toggle_true_when_any_box_can_toggle(self):
        """can_toggle should return True when any box can toggle."""
        mgr = ThinkingBoxManager()
        # Create box with lots of content so it can toggle
        big_content = "\n".join(f"line {i}" for i in range(30))
        mgr.create_box(lambda: big_content, box_id="a")
        assert mgr.can_toggle()

    def test_can_toggle_false_when_empty(self):
        """can_toggle should return False when there are no boxes."""
        mgr = ThinkingBoxManager()
        assert not mgr.can_toggle()

    def test_can_toggle_false_when_small_content_collapsed(self):
        """can_toggle should return False when content fits and is collapsed."""
        mgr = ThinkingBoxManager(default_max_lines=100)
        mgr.create_box(lambda: "small", box_id="a")
        assert not mgr.can_toggle()


# =============================================================================
# Thread safety tests
# =============================================================================


class TestThreadSafety:
    """Test that the manager is thread-safe."""

    def test_concurrent_create_and_remove(self):
        """Concurrent create and remove should not raise."""
        mgr = ThinkingBoxManager()
        errors = []

        def creator():
            try:
                for i in range(50):
                    mgr.create_box(lambda: "x", box_id=f"create-{i}")
            except Exception as e:
                errors.append(e)

        def remover():
            try:
                for i in range(50):
                    mgr.remove_box(f"create-{i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=creator)
        t2 = threading.Thread(target=remover)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Thread safety errors: {errors}"
