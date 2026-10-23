"""
Integration tests for the multi-box thinking feature.

Tests the interaction between ThinkingPromptSession and ThinkingBoxManager
for creating, managing, and finishing multiple thinking boxes.
"""
from __future__ import annotations

import pytest

from thinking_prompt import ThinkingPromptSession, AppInfo

from tests.helpers import echoed, keep_console


def _make_session(**kwargs):
    """Create a minimal ThinkingPromptSession with test defaults."""
    app_info = AppInfo(name="Test", version="0.0.1")
    return ThinkingPromptSession(app_info=app_info, **kwargs)


# =============================================================================
# Lifecycle tests
# =============================================================================


class TestMultiBoxLifecycle:
    """Test lifecycle of multiple thinking boxes via the session API."""

    @pytest.mark.asyncio
    async def test_nested_context_managers(self):
        """Nested context managers: inner finishes first, outer stays active."""
        session = _make_session()

        async with session.thinking(
            title="Outer",
            echo_to_console=False,
        ) as outer_ctx:
            assert session._manager.active_count == 1
            outer_ctx.append("outer content\n")

            async with session.thinking(
                title="Inner",
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

        ctx.finish(echo_to_console=False)
        assert not session.is_thinking


# =============================================================================
# Ordering tests
# =============================================================================


class TestMultiBoxOrdering:
    """Test sorting of multiple boxes by order and creation sequence."""

    def test_mixed_order_with_sequence_tiebreaker(self):
        """Mixed order values with creation sequence as tiebreaker."""
        session = _make_session()
        ctx_a = session.start_thinking(lambda: "a", order=2, title="A")
        ctx_b = session.start_thinking(lambda: "b", order=1, title="B")
        ctx_c = session.start_thinking(lambda: "c", order=2, title="C")
        ctx_d = session.start_thinking(lambda: "d", order=1, title="D")

        sorted_boxes = session._manager.get_sorted_boxes()
        titles = [b._header.text for b in sorted_boxes]
        assert titles == ["B", "D", "A", "C"]

        ctx_a.finish(echo_to_console=False)
        ctx_b.finish(echo_to_console=False)
        ctx_c.finish(echo_to_console=False)
        ctx_d.finish(echo_to_console=False)


# =============================================================================
# Expand / Collapse tests
# =============================================================================


class TestMultiBoxExpandCollapse:
    """Test expand/collapse behavior across multiple boxes."""

    def test_new_boxes_inherit_collapsed_state(self):
        """New boxes created after collapse_all should remain collapsed."""
        session = _make_session()
        ctx1 = session.start_thinking(lambda: "a")
        session._manager.expand_all()
        session._manager.collapse_all()

        ctx2 = session.start_thinking(lambda: "b")
        boxes = session._manager.get_sorted_boxes()
        new_box = [b for b in boxes if b._control.content == "b"][0]
        assert not new_box._control.is_expanded

        ctx1.finish(echo_to_console=False)
        ctx2.finish(echo_to_console=False)


class TestSessionOverflow:
    """overflow= on start_thinking()/thinking() reaches the box and decides
    which end of the content the finish echo keeps."""

    @staticmethod
    def _session():
        # Keeping console output instead of printing it makes the finish
        # echo observable.
        s = ThinkingPromptSession()
        keep_console(s._display)
        return s

    @staticmethod
    def _echoed(s) -> list[str]:
        return echoed(s._display)

    @staticmethod
    def _lines(n: int) -> str:
        return "".join(f"line {i}\n" for i in range(n))

    def test_default_is_tail_and_echo_keeps_last_lines(self):
        s = self._session()
        ctx = s.start_thinking(max_lines=3)
        ctx.append(self._lines(10))
        ctx.finish(echo_to_console=True)
        assert self._echoed(s) == ["...\nline 7\nline 8\nline 9\n"]

    async def test_thinking_head_echo_keeps_first_lines(self):
        s = self._session()
        async with s.thinking(max_lines=3, overflow="head", echo_to_console=True) as ctx:
            ctx.append(self._lines(10))
            assert s._manager.get_sorted_boxes()[0]._control.overflow == "head"
        assert self._echoed(s) == ["line 0\nline 1\nline 2\n...\n"]

    def test_overflow_type_is_exported(self):
        from thinking_prompt import Overflow  # noqa: F401
