"""
Tests for ThinkingBoxManager and ThinkingBox.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from thinking_prompt.manager import ThinkingBoxManager
from thinking_prompt.thinking_box import ThinkingBox
from thinking_prompt.thinking_control import ThinkingBoxControl
from thinking_prompt.layout import ThinkingHeader
from thinking_prompt.streaming import StreamingContent
from tests.helpers import echoed, history_texts, make_display, make_manager


# =============================================================================
# Creation tests
# =============================================================================


class TestCreation:
    """Test create_box returns ThinkingBox with correct configuration."""

    def test_create_box_returns_a_thinking_box(self):
        """create_box should return a ThinkingBox instance."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "hello")
        assert isinstance(box, ThinkingBox)

    def test_create_box_with_callback(self):
        """create_box with callback should use it in the control."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "test content")
        assert box._control.content == "test content"

    def test_create_box_without_callback_creates_streaming_content(self):
        """create_box without callback should create StreamingContent internally."""
        mgr = make_manager()
        box = mgr.create_box()
        assert box._content is not None
        assert isinstance(box._content, StreamingContent)

    def test_create_box_without_callback_content_wired(self):
        """The box's own content is what the control draws."""
        mgr = make_manager()
        box = mgr.create_box()
        box.append("hello world")
        assert box._control.content == "hello world"

    def test_create_box_with_callback_no_streaming_content(self):
        """create_box with callback should not create StreamingContent."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "x")
        assert box._content is None

    def test_create_box_with_title_creates_header(self):
        """create_box with title should create a ThinkingHeader."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "x", title="Processing")
        assert box._header is not None
        assert isinstance(box._header, ThinkingHeader)
        assert box._header.text == "Processing"

    def test_create_box_without_title_no_header(self):
        """create_box without title should not create a header."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "x")
        assert box._header is None

    def test_headers_use_the_managers_spinner_settings(self):
        mgr = make_manager(spinner_frames=("a", "b"), spinner_position="after")
        header = mgr.create_box(lambda: "x", title="T")._header
        assert header.frames == ("a", "b")
        assert header.position == "after"

    def test_display_is_required(self):
        with pytest.raises(TypeError):
            ThinkingBoxManager()  # type: ignore[call-arg]

    def test_session_spinner_settings_reach_every_header(self):
        from thinking_prompt import AppInfo, ThinkingPromptSession

        session = ThinkingPromptSession(
            app_info=AppInfo(
                name="t", thinking_animation=(), thinking_animation_position="after"
            )
        )
        session.start_thinking(lambda: "x")
        (box,) = session._manager.get_sorted_boxes()
        assert box._header.frames == ()
        assert box._header.position == "after"

    def test_session_echo_thinking_off_keeps_boxes_off_the_console(self):
        from thinking_prompt import AppInfo, ThinkingPromptSession

        session = ThinkingPromptSession(app_info=AppInfo(name="t", echo_thinking=False))
        session._is_fullscreen = True  # the Display caches console output in full screen
        ctx = session.start_thinking()
        ctx.append("x\n")
        ctx.finish()
        assert session._display._pending_output == []
        assert history_texts(session._display) == ["x\n\n"]

    def test_create_box_custom_order(self):
        """create_box with order should set it on the ThinkingBox."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "x", order=5)
        assert box._order == 5

    def test_create_box_default_order(self):
        """create_box without order should default to 0."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "x")
        assert box._order == 0

    def test_create_box_custom_max_lines(self):
        """create_box with max_lines should override the default."""
        mgr = make_manager(default_max_lines=15)
        box = mgr.create_box(lambda: "x", max_lines=5)
        assert box._control.max_collapsed_lines == 5

    def test_create_box_default_max_lines(self):
        """create_box without max_lines should use the manager default."""
        mgr = make_manager(default_max_lines=20)
        box = mgr.create_box(lambda: "x")
        assert box._control.max_collapsed_lines == 20

    def test_create_box_forwards_expand_key_to_hint(self):
        """The truncation hint must name the manager's expand key.

        Regression: boxes were created with the control's default
        ("c-t"), so a custom expand key bound at the session level
        showed the wrong key in the "+N lines... ctrl-t to expand"
        hint."""
        mgr = make_manager(default_max_lines=3, expand_key="c-x")
        box = mgr.create_box(lambda: "1\n2\n3\n4\n5", title="T")
        hint = "".join(frag[1] for frag in box._control._get_formatted_text())
        assert "ctrl-x" in hint
        assert "ctrl-t" not in hint

    def test_session_expand_key_reaches_manager(self):
        """AppInfo.expand_key flows through the session to the manager."""
        from thinking_prompt import AppInfo, ThinkingPromptSession

        session = ThinkingPromptSession(
            app_info=AppInfo(name="t", expand_key="c-x")
        )
        assert session._manager._expand_key == "c-x"

    def test_header_separator_spans_terminal_width(self):
        """The header line is sized to the app's terminal width, not a
        hardcoded 80 columns."""
        from unittest.mock import MagicMock

        from prompt_toolkit.application.current import set_app
        from prompt_toolkit.data_structures import Size

        mgr = make_manager()
        box = mgr.create_box(lambda: "x", title="T")

        # box._container is HSplit([header_window, content_window]).
        header_window = box._container.get_children()[0]
        get_text = header_window.content.text

        fake_app = MagicMock()
        fake_app.output.get_size.return_value = Size(rows=24, columns=120)
        with set_app(fake_app):
            line = "".join(frag[1] for frag in get_text())
        assert len(line) == 120

    def test_create_box_content_format(self):
        """create_box passes content_format to the control."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "x", content_format="ansi")
        assert box._control.content_format == "ansi"

    def test_create_box_has_container(self):
        """create_box should build a container."""
        mgr = make_manager()
        box = mgr.create_box(lambda: "x")
        assert box._container is not None

    def test_create_box_seq_increments(self):
        """Each created box should have an incrementing seq."""
        mgr = make_manager()
        box1 = mgr.create_box(lambda: "a")
        box2 = mgr.create_box(lambda: "b")
        box3 = mgr.create_box(lambda: "c")
        assert box1._seq < box2._seq < box3._seq


# =============================================================================
# Active state tests
# =============================================================================


class TestActiveState:
    """Test has_active_boxes and active_count properties."""

    def test_no_boxes_not_active(self):
        """Manager with no boxes should not be active."""
        mgr = make_manager()
        assert not mgr.has_active_boxes
        assert mgr.active_count == 0

    def test_one_box_active(self):
        """Manager with one box should be active."""
        mgr = make_manager()
        mgr.create_box(lambda: "x")
        assert mgr.has_active_boxes
        assert mgr.active_count == 1

    def test_multiple_boxes_active(self):
        """Manager with multiple boxes should report correct count."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.create_box(lambda: "c")
        assert mgr.has_active_boxes
        assert mgr.active_count == 3

    def test_finished_box_decreases_count(self):
        mgr = make_manager()
        a = mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.finish(a)
        assert mgr.active_count == 1
        assert mgr.has_active_boxes

    def test_all_finished_not_active(self):
        mgr = make_manager()
        mgr.finish(mgr.create_box(lambda: "a"))
        assert not mgr.has_active_boxes
        assert mgr.active_count == 0


# =============================================================================
# Ending boxes
# =============================================================================


class TestFinish:
    """finish(box): that box ends, once."""

    def test_finish_ends_only_that_box(self):
        mgr = make_manager()
        a = mgr.create_box(lambda: "a")
        b = mgr.create_box(lambda: "b")
        assert mgr.finish(a) is True
        assert a.is_finished and not b.is_finished
        assert mgr.get_sorted_boxes() == [b]

    def test_finishing_an_ended_box_does_nothing(self):
        display = make_display()
        mgr = make_manager(display)
        box = mgr.create_box(lambda: "x\n")
        mgr.finish(box)
        assert mgr.finish(box) is False
        assert history_texts(display) == ["x\n\n"]


class TestFinishAll:
    def test_finish_all_returns_the_boxes_in_creation_order(self):
        mgr = make_manager()
        a = mgr.create_box(lambda: "a", order=5)
        b = mgr.create_box(lambda: "b", order=1)
        assert mgr.finish_all() == [a, b]
        assert a.is_finished and b.is_finished

    def test_finish_all_clears_boxes(self):
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.finish_all()
        assert mgr.active_count == 0
        assert not mgr.has_active_boxes

    def test_finish_all_empty_manager(self):
        assert make_manager().finish_all() == []


class TestFinishOwnedBy:
    """A handler answers for its own boxes, for boxes whose task ended and
    for boxes with no task; another task's live box is left alone."""

    async def test_picks_the_boxes_a_handler_answers_for(self):
        mgr = make_manager()
        mine = mgr.create_box(lambda: "mine")
        threaded = await asyncio.to_thread(mgr.create_box, lambda: "thread")

        async def open_and_return() -> ThinkingBox:
            return mgr.create_box(lambda: "ended")

        orphan = await asyncio.create_task(open_and_return())

        gate = asyncio.Event()
        live: list[ThinkingBox] = []

        async def open_and_wait() -> None:
            live.append(mgr.create_box(lambda: "live"))
            await gate.wait()

        task = asyncio.create_task(open_and_wait())
        await asyncio.sleep(0)

        assert threaded._owner is None and orphan._owner.done()
        assert mgr.finish_owned_by(asyncio.current_task()) == [mine, threaded, orphan]
        assert mgr.get_sorted_boxes() == live
        gate.set()
        await task


class TestEcho:
    """Ending a box echoes its text through the Display, as it was shown."""

    def test_echo_is_cut_to_each_boxs_lines_at_its_overflow_end(self):
        display = make_display()
        mgr = make_manager(display, default_max_lines=15)
        mgr.create_box(lambda: "1\n2\n3\n4\n", max_lines=2)
        mgr.create_box(lambda: "1\n2\n3\n4\n", max_lines=2, overflow="head")
        mgr.finish_all()
        assert echoed(display) == ["...\n3\n4\n", "1\n2\n...\n"]
        assert history_texts(display) == ["1\n2\n3\n4\n\n", "1\n2\n3\n4\n\n"]

    def test_ansi_boxes_echo_as_ansi(self):
        display = make_display()
        mgr = make_manager(display)
        mgr.finish(mgr.create_box(lambda: "\x1b[31mred\x1b[0m\n", content_format="ansi"))
        (entry,) = display.history.iter_entries()
        assert entry.kind == "ansi"

    def test_blank_boxes_echo_nothing(self):
        display = make_display()
        mgr = make_manager(display)
        mgr.finish(mgr.create_box(lambda: "  \n"))
        assert history_texts(display) == []
        assert echoed(display) == []

    def test_echo_thinking_off_keeps_the_console_quiet_by_default(self):
        display = make_display()
        mgr = make_manager(display, echo_thinking=False)
        mgr.finish(mgr.create_box(lambda: "x\n"))
        assert echoed(display) == []
        assert history_texts(display) == ["x\n\n"]
        mgr.finish(mgr.create_box(lambda: "y\n"), echo_to_console=True)
        assert echoed(display) == ["y\n"]

    def test_add_to_history_false_keeps_history_clean(self):
        display = make_display()
        mgr = make_manager(display)
        mgr.finish(mgr.create_box(lambda: "x\n"), add_to_history=False)
        assert history_texts(display) == []
        assert echoed(display) == ["x\n"]


# =============================================================================
# Sorting tests
# =============================================================================


class TestSorting:
    """Test get_sorted_boxes ordering."""

    def test_sorted_by_order(self):
        mgr = make_manager()
        high = mgr.create_box(lambda: "high", order=10)
        low = mgr.create_box(lambda: "low", order=1)
        mid = mgr.create_box(lambda: "mid", order=5)
        assert mgr.get_sorted_boxes() == [low, mid, high]

    def test_sorted_by_seq_within_same_order(self):
        mgr = make_manager()
        first = mgr.create_box(lambda: "first", order=0)
        second = mgr.create_box(lambda: "second", order=0)
        third = mgr.create_box(lambda: "third", order=0)
        assert mgr.get_sorted_boxes() == [first, second, third]

    def test_mixed_ordering(self):
        mgr = make_manager()
        a = mgr.create_box(lambda: "a", order=2)
        b = mgr.create_box(lambda: "b", order=1)
        c = mgr.create_box(lambda: "c", order=2)
        d = mgr.create_box(lambda: "d", order=1)
        assert mgr.get_sorted_boxes() == [b, d, a, c]

    def test_get_container_returns_container(self):
        """get_container should return a valid container."""
        from prompt_toolkit.layout import HSplit, Window
        mgr = make_manager()
        mgr.create_box(lambda: "x")
        container = mgr.get_container()
        # Should be an HSplit (or Window if empty)
        assert container is not None

    def test_get_container_empty_returns_zero_height(self):
        """get_container with no boxes should return a zero-height Window."""
        from prompt_toolkit.layout import Window
        mgr = make_manager()
        container = mgr.get_container()
        assert isinstance(container, Window)


# =============================================================================
# Expand / Collapse tests
# =============================================================================


class TestExpandCollapse:
    """Test toggle_all, expand_all, collapse_all."""

    def test_toggle_all_expands_when_collapsed(self):
        """toggle_all should expand all boxes when currently collapsed."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.toggle_all()
        for box in mgr.get_sorted_boxes():
            assert box._control.is_expanded

    def test_toggle_all_collapses_when_expanded(self):
        """toggle_all should collapse all boxes when currently expanded."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.expand_all()
        mgr.toggle_all()
        for box in mgr.get_sorted_boxes():
            assert not box._control.is_expanded

    def test_expand_all(self):
        """expand_all should expand all boxes."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.expand_all()
        for box in mgr.get_sorted_boxes():
            assert box._control.is_expanded

    def test_collapse_all(self):
        """collapse_all should collapse all boxes."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.create_box(lambda: "b")
        mgr.expand_all()
        mgr.collapse_all()
        for box in mgr.get_sorted_boxes():
            assert not box._control.is_expanded

    def test_new_box_inherits_expanded_state(self):
        """A new box should inherit the current expanded state."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.expand_all()
        box2 = mgr.create_box(lambda: "b")
        assert box2._control.is_expanded

    def test_new_box_inherits_collapsed_state(self):
        """A new box created when collapsed should remain collapsed."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.collapse_all()
        box2 = mgr.create_box(lambda: "b")
        assert not box2._control.is_expanded

    def test_can_toggle_true_when_expanded(self):
        """can_toggle should return True when boxes are expanded."""
        mgr = make_manager()
        mgr.create_box(lambda: "a")
        mgr.expand_all()
        assert mgr.can_toggle()

    def test_can_toggle_true_when_any_box_can_toggle(self):
        """can_toggle should return True when any box can toggle."""
        mgr = make_manager()
        # Create box with lots of content so it can toggle
        big_content = "\n".join(f"line {i}" for i in range(30))
        mgr.create_box(lambda: big_content)
        assert mgr.can_toggle()

    def test_can_toggle_false_when_empty(self):
        """can_toggle should return False when there are no boxes."""
        mgr = make_manager()
        assert not mgr.can_toggle()

    def test_can_toggle_false_when_small_content_collapsed(self):
        """can_toggle should return False when content fits and is collapsed."""
        mgr = make_manager(default_max_lines=100)
        mgr.create_box(lambda: "small")
        assert not mgr.can_toggle()


# =============================================================================
# Thread safety tests
# =============================================================================


class TestThreadSafety:
    """Test that the manager is thread-safe."""

    def test_concurrent_create_and_finish(self):
        mgr = make_manager()
        errors: list[Exception] = []

        def creator():
            try:
                for _ in range(50):
                    mgr.create_box(lambda: "x")
            except Exception as e:
                errors.append(e)

        def finisher():
            try:
                for _ in range(50):
                    mgr.finish_all(add_to_history=False, echo_to_console=False)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=creator), threading.Thread(target=finisher)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        mgr.finish_all()

        assert not errors, f"Thread safety errors: {errors}"
        assert mgr.active_count == 0


# =============================================================================
# Collapsed height terminal width tests
# =============================================================================


class TestCollapsedHeightUsesTerminalWidth:
    """Collapsed height must wrap-count at the real terminal width, not a
    hardcoded 80 (manager.get_height previously called get_line_count()
    with the width=80 default while the header one function away already
    queried the live width)."""

    def test_height_wraps_at_patched_terminal_width(self, monkeypatch):
        import thinking_prompt.manager as manager_mod

        monkeypatch.setattr(manager_mod, "_terminal_width", lambda *a, **k: 20)

        manager = make_manager(default_max_lines=15)
        # title=None -> no header -> container IS the content Window,
        # whose .height is the get_height closure.
        box = manager.create_box(lambda: "x" * 80, title=None)

        dim = box._container.height()
        # 80 chars at width 20 wrap to 4 display lines.
        assert dim.preferred == 4

    def test_height_defaults_to_80_columns_without_app(self):
        manager = make_manager(default_max_lines=15)
        box = manager.create_box(lambda: "x" * 80, title=None)

        dim = box._container.height()
        # Outside a running app the dummy app reports 80 columns:
        # a single 80-char line occupies exactly 1 display line.
        assert dim.preferred == 1


def _render_rows(container, width: int, height: int) -> list[str]:
    """Render a container into width x height; return its text rows."""
    from prompt_toolkit.layout.mouse_handlers import MouseHandlers
    from prompt_toolkit.layout.screen import Screen, WritePosition

    screen = Screen()
    container.write_to_screen(
        screen, MouseHandlers(), WritePosition(0, 0, width, height), "", True, None
    )
    return [
        "".join(screen.data_buffer[y][x].char for x in range(width)).rstrip()
        for y in range(height)
    ]


class TestBoxSizing:
    """Expanded boxes size to their content; when the screen is short the
    layout squeezes them and they show the newest lines under the hint."""

    @staticmethod
    def _box(manager: ThinkingBoxManager, n: int, **kwargs):
        content = "".join(f"line {i}\n" for i in range(n))
        return manager.create_box(lambda: content, title="T", **kwargs)

    def test_expanded_small_box_takes_its_content_height(self):
        m = make_manager(default_max_lines=5)
        self._box(m, 3)
        m.expand_all()
        # header + 3 content rows (it used to be a fixed 20)
        assert m.get_container().preferred_height(40, 100).preferred == 4

    def test_expanded_large_box_on_short_screen_follows_newest_lines(self):
        m = make_manager(default_max_lines=5)
        self._box(m, 60)
        m.expand_all()
        rows = _render_rows(m.get_container(), 40, 10)
        assert rows[1] == "+52 earlier lines... ctrl-t to collapse"
        assert rows[2:] == [f"line {i}" for i in range(52, 60)]

    def test_overflow_defaults_to_tail(self):
        m = make_manager()
        assert self._box(m, 1)._control.overflow == "tail"

    def test_overflow_head_reaches_the_control(self):
        m = make_manager()
        assert self._box(m, 1, overflow="head")._control.overflow == "head"
