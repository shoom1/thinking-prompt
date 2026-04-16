"""
Integration tests for the multi-box thinking feature.

Tests the interaction between ThinkingPromptSession and ThinkingBoxManager
for creating, managing, and finishing multiple thinking boxes.
"""
from __future__ import annotations

import warnings

import pytest

from thinking_prompt import ThinkingPromptSession, AppInfo
from thinking_prompt.types import ThinkingContext


def _make_session(**kwargs):
    """Create a minimal ThinkingPromptSession with test defaults."""
    app_info = AppInfo(name="Test", version="0.0.1", thinking_text="Thinking")
    return ThinkingPromptSession(app_info=app_info, **kwargs)


# =============================================================================
# Lifecycle tests
# =============================================================================


class TestMultiBoxLifecycle:
    """Test lifecycle of multiple thinking boxes via the session API."""

    def test_multiple_start_thinking_creates_multiple_boxes(self):
        """Multiple start_thinking calls should create multiple active boxes."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "box 1")
        ctx2 = session.start_thinking(lambda: "box 2")
        ctx3 = session.start_thinking(lambda: "box 3")
        assert session._manager.active_count == 3
        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)
        ctx3.finish(add_to_history=False, echo_to_console=False)

    def test_finishing_one_box_keeps_others_active(self):
        """Finishing one box via ctx.finish() should keep other boxes active."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "box 1")
        ctx2 = session.start_thinking(lambda: "box 2")
        ctx3 = session.start_thinking(lambda: "box 3")
        assert session._manager.active_count == 3

        ctx1.finish(add_to_history=False, echo_to_console=False)
        assert session._manager.active_count == 2
        ctx2.finish(add_to_history=False, echo_to_console=False)
        ctx3.finish(add_to_history=False, echo_to_console=False)

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_session_finish_thinking_finishes_all_boxes(self):
        """session.finish_thinking() should finish all active boxes."""
        session = _make_session()
        session.start_thinking(lambda: "box 1")
        session.start_thinking(lambda: "box 2")
        session.start_thinking(lambda: "box 3")
        assert session._manager.active_count == 3

        session.finish_thinking(add_to_history=False, echo_to_console=False)
        assert session._manager.active_count == 0

    def test_ctx_finish_returns_box_content(self):
        """ctx.finish() should return the content of the finished box."""
        session = _make_session()
        ctx = session.start_thinking(lambda: "final result")
        result = ctx.finish(add_to_history=False, echo_to_console=False)
        assert result == "final result"

    @pytest.mark.asyncio
    async def test_nested_context_managers(self):
        """Nested context managers: inner finishes first, outer stays active."""
        session = _make_session()

        async with session.thinking(
            title="Outer",
            add_to_history=False,
            echo_to_console=False,
        ) as outer_ctx:
            assert session._manager.active_count == 1
            outer_ctx.append("outer content\n")

            async with session.thinking(
                title="Inner",
                add_to_history=False,
                echo_to_console=False,
            ) as inner_ctx:
                assert session._manager.active_count == 2
                inner_ctx.append("inner content\n")

            # Inner exited — only outer remains
            assert session._manager.active_count == 1

        # Both exited
        assert session._manager.active_count == 0

    def test_is_thinking_reflects_active_boxes(self):
        """session.is_thinking should reflect whether any boxes are active."""
        session = _make_session()
        assert not session.is_thinking

        ctx = session.start_thinking(lambda: "")
        assert session.is_thinking

        ctx.finish(add_to_history=False, echo_to_console=False)
        assert not session.is_thinking

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_finish_thinking_on_empty_returns_empty_string(self):
        """session.finish_thinking() with no active boxes should return ''."""
        session = _make_session()
        result = session.finish_thinking(add_to_history=False, echo_to_console=False)
        assert result == ""


# =============================================================================
# Ordering tests
# =============================================================================


class TestMultiBoxOrdering:
    """Test sorting of multiple boxes by order and creation sequence."""

    def test_boxes_sorted_by_order(self):
        """Boxes should be sorted by order (lower order at top)."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "high", order=10)
        ctx2 = session.start_thinking(lambda: "low", order=1)
        ctx3 = session.start_thinking(lambda: "mid", order=5)

        sorted_boxes = session._manager.get_sorted_boxes()
        orders = [b.order for b in sorted_boxes]
        assert orders == [1, 5, 10]

        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)
        ctx3.finish(add_to_history=False, echo_to_console=False)

    def test_same_order_sorted_by_creation_sequence(self):
        """Boxes with the same order should be sorted by creation sequence."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "first", order=0)
        ctx2 = session.start_thinking(lambda: "second", order=0)
        ctx3 = session.start_thinking(lambda: "third", order=0)

        sorted_boxes = session._manager.get_sorted_boxes()
        assert len(sorted_boxes) == 3
        # seq should be monotonically increasing
        seqs = [b.seq for b in sorted_boxes]
        assert seqs == sorted(seqs)
        assert seqs[0] < seqs[1] < seqs[2]

        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)
        ctx3.finish(add_to_history=False, echo_to_console=False)

    def test_mixed_order_with_sequence_tiebreaker(self):
        """Mixed order values with creation sequence as tiebreaker."""
        session = _make_session()
        ctx_a = session.start_thinking(lambda: "a", order=2, title="A")
        ctx_b = session.start_thinking(lambda: "b", order=1, title="B")
        ctx_c = session.start_thinking(lambda: "c", order=2, title="C")
        ctx_d = session.start_thinking(lambda: "d", order=1, title="D")

        sorted_boxes = session._manager.get_sorted_boxes()
        titles = [b.header.text for b in sorted_boxes]
        assert titles == ["B", "D", "A", "C"]

        ctx_a.finish(add_to_history=False, echo_to_console=False)
        ctx_b.finish(add_to_history=False, echo_to_console=False)
        ctx_c.finish(add_to_history=False, echo_to_console=False)
        ctx_d.finish(add_to_history=False, echo_to_console=False)


# =============================================================================
# Expand / Collapse tests
# =============================================================================


class TestMultiBoxExpandCollapse:
    """Test expand/collapse behavior across multiple boxes."""

    def test_toggle_all_expands_all_boxes(self):
        """toggle_all should expand all boxes when currently collapsed."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "a")
        ctx2 = session.start_thinking(lambda: "b")

        session._manager.toggle_all()

        for box in session._manager.get_sorted_boxes():
            assert box.control.is_expanded

        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)

    def test_toggle_all_collapses_all_boxes(self):
        """toggle_all should collapse all boxes when currently expanded."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "a")
        ctx2 = session.start_thinking(lambda: "b")

        session._manager.expand_all()
        session._manager.toggle_all()

        for box in session._manager.get_sorted_boxes():
            assert not box.control.is_expanded

        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)

    def test_new_boxes_inherit_expanded_state(self):
        """New boxes created after expand_all should inherit expanded state."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "a")
        session._manager.expand_all()

        # Create a new box after expanding
        ctx2 = session.start_thinking(lambda: "b")
        boxes = session._manager.get_sorted_boxes()
        # The new box should also be expanded
        new_box = [b for b in boxes if b.control.content == "b"][0]
        assert new_box.control.is_expanded

        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)

    def test_new_boxes_inherit_collapsed_state(self):
        """New boxes created after collapse_all should remain collapsed."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "a")
        session._manager.expand_all()
        session._manager.collapse_all()

        ctx2 = session.start_thinking(lambda: "b")
        boxes = session._manager.get_sorted_boxes()
        new_box = [b for b in boxes if b.control.content == "b"][0]
        assert not new_box.control.is_expanded

        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)


# =============================================================================
# Backward compatibility tests
# =============================================================================


class TestMultiBoxBackwardCompat:
    """Test backward compatibility with single-box usage patterns."""

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_single_box_start_finish(self):
        """Single-box start_thinking(callback) / finish_thinking() works as before."""
        session = _make_session()
        chunks = []
        session.start_thinking(lambda: "".join(chunks))
        chunks.append("Processing...\n")
        chunks.append("Done!\n")

        assert session.is_thinking
        assert session._manager.active_count == 1

        result = session.finish_thinking(add_to_history=False, echo_to_console=False)
        assert "Processing" in result
        assert "Done!" in result
        assert not session.is_thinking
        assert session._manager.active_count == 0

    @pytest.mark.asyncio
    async def test_single_box_context_manager(self):
        """Single-box thinking() context manager works as before."""
        session = _make_session()

        async with session.thinking(
            title="Working",
            add_to_history=False,
            echo_to_console=False,
        ) as ctx:
            assert isinstance(ctx, ThinkingContext)
            assert session.is_thinking
            assert session._manager.active_count == 1
            ctx.append("step 1\n")
            ctx.append("step 2\n")
            assert "step 1" in ctx.text
            assert "step 2" in ctx.text

        assert not session.is_thinking
        assert session._manager.active_count == 0

    def test_start_thinking_with_callback_title_returns_default(self):
        """start_thinking with callback — ctx.title returns default 'Thinking'."""
        session = _make_session()
        ctx = session.start_thinking(lambda: "content")
        assert ctx.title == "Thinking"
        ctx.finish(add_to_history=False, echo_to_console=False)

    def test_start_thinking_with_explicit_title(self):
        """start_thinking with explicit title — ctx.title returns that title."""
        session = _make_session()
        ctx = session.start_thinking(lambda: "content", title="Custom")
        assert ctx.title == "Custom"
        ctx.finish(add_to_history=False, echo_to_console=False)

    def test_start_thinking_without_callback_creates_streaming_content(self):
        """start_thinking without callback should create StreamingContent via manager."""
        session = _make_session()
        ctx = session.start_thinking()
        ctx.append("hello")
        assert ctx.text == "hello"
        ctx.finish(add_to_history=False, echo_to_console=False)

    @pytest.mark.asyncio
    async def test_context_manager_exception_cleanup(self):
        """Context manager should clean up properly on exception."""
        session = _make_session()

        with pytest.raises(RuntimeError):
            async with session.thinking(
                add_to_history=False,
                echo_to_console=False,
            ) as ctx:
                ctx.append("before error\n")
                raise RuntimeError("boom")

        assert not session.is_thinking
        assert session._manager.active_count == 0
