# Multi-Box Thinking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support multiple independent thinking boxes that stack vertically, each with its own content, optional animated header, height, and lifecycle.

**Architecture:** A `ThinkingBoxManager` manages a collection of `ManagedBox` instances. The layout uses `DynamicContainer` to render active boxes sorted by `(order, seq)`. Each box is a `ThinkingBoxControl` + optional `ThinkingHeader`, created once and reused until finished.

**Tech Stack:** Python 3.9+, prompt_toolkit 3.0+ (DynamicContainer, HSplit, Window), threading (RLock)

**Design doc:** `docs/plans/2026-03-11-multi-box-design.md`

---

### Task 1: Rename ThinkingSeparator → ThinkingHeader

**Files:**
- Modify: `thinking_prompt/layout.py` (class rename + all references)
- Modify: `thinking_prompt/session.py` (import and usage rename)
- Modify: `thinking_prompt/__init__.py` (if exported — check first)

**Step 1: Rename class and references in layout.py**

In `thinking_prompt/layout.py`:
- Rename `class ThinkingSeparator` → `class ThinkingHeader`
- Keep all methods and behavior identical
- Add backward-compat alias: `ThinkingSeparator = ThinkingHeader`

**Step 2: Update session.py references**

In `thinking_prompt/session.py`:
- Change import: `from .layout import create_layout, ThinkingHeader`
- Rename `self._thinking_separator` → `self._thinking_header` throughout
- Update `_create_session_layout`, `_set_thinking_title`, `_get_thinking_title`, `finish_thinking`, and all other references

**Step 3: Run tests to verify refactor**

Run: `conda run -n thinking_prompt pytest tests/ -v`
Expected: All existing tests pass (tests reference `session._thinking_separator` — update those too)

**Step 4: Update test references**

In `tests/test_thinking_context.py`: rename all `session._thinking_separator` → `session._thinking_header`

**Step 5: Run tests again**

Run: `conda run -n thinking_prompt pytest tests/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add thinking_prompt/layout.py thinking_prompt/session.py tests/test_thinking_context.py
git commit -m "refactor: rename ThinkingSeparator to ThinkingHeader"
```

---

### Task 2: Create ThinkingBoxManager and ManagedBox

**Files:**
- Create: `thinking_prompt/manager.py`
- Create: `tests/test_manager.py`

**Step 1: Write failing tests for ManagedBox and basic manager operations**

Create `tests/test_manager.py`:

```python
"""Tests for ThinkingBoxManager."""
from __future__ import annotations

import pytest

from thinking_prompt.manager import ThinkingBoxManager, ManagedBox


class TestThinkingBoxManagerCreation:
    """Test box creation."""

    def test_create_box_returns_managed_box(self):
        manager = ThinkingBoxManager()
        box = manager.create_box()
        assert isinstance(box, ManagedBox)

    def test_create_box_with_callback(self):
        manager = ThinkingBoxManager()
        box = manager.create_box(content_callback=lambda: "hello")
        assert box.control.content == "hello"

    def test_create_box_without_callback_creates_streaming_content(self):
        manager = ThinkingBoxManager()
        box = manager.create_box()
        assert box.streaming_content is not None
        box.streaming_content.append("test")
        assert box.control.content == "test"

    def test_create_box_with_title_creates_header(self):
        manager = ThinkingBoxManager()
        box = manager.create_box(title="Processing")
        assert box.header is not None
        assert box.header.text == "Processing"

    def test_create_box_without_title_no_header(self):
        manager = ThinkingBoxManager()
        box = manager.create_box()
        assert box.header is None

    def test_create_box_assigns_sequential_ids(self):
        manager = ThinkingBoxManager()
        box1 = manager.create_box()
        box2 = manager.create_box()
        assert box1.box_id != box2.box_id
        assert box1.seq < box2.seq

    def test_create_box_custom_id(self):
        manager = ThinkingBoxManager()
        box = manager.create_box(box_id="my-box")
        assert box.box_id == "my-box"

    def test_create_box_with_order(self):
        manager = ThinkingBoxManager()
        box = manager.create_box(order=100)
        assert box.order == 100

    def test_create_box_with_max_lines(self):
        manager = ThinkingBoxManager()
        box = manager.create_box(max_lines=5)
        assert box.control.max_collapsed_lines == 5

    def test_create_box_default_max_lines(self):
        manager = ThinkingBoxManager(default_max_lines=10)
        box = manager.create_box()
        assert box.control.max_collapsed_lines == 10

    def test_has_active_boxes_false_initially(self):
        manager = ThinkingBoxManager()
        assert not manager.has_active_boxes

    def test_has_active_boxes_true_after_create(self):
        manager = ThinkingBoxManager()
        manager.create_box()
        assert manager.has_active_boxes

    def test_active_count(self):
        manager = ThinkingBoxManager()
        manager.create_box()
        manager.create_box()
        assert manager.active_count == 2


class TestThinkingBoxManagerRemoval:
    """Test box removal."""

    def test_remove_box_returns_content(self):
        manager = ThinkingBoxManager()
        box = manager.create_box(content_callback=lambda: "final content")
        content, was_expanded, fmt = manager.remove_box(box.box_id)
        assert content == "final content"
        assert not was_expanded
        assert fmt == "plain"

    def test_remove_box_decreases_count(self):
        manager = ThinkingBoxManager()
        box1 = manager.create_box()
        box2 = manager.create_box()
        manager.remove_box(box1.box_id)
        assert manager.active_count == 1

    def test_remove_nonexistent_box(self):
        manager = ThinkingBoxManager()
        content, was_expanded, fmt = manager.remove_box("nonexistent")
        assert content == ""

    def test_finish_all(self):
        manager = ThinkingBoxManager()
        manager.create_box(content_callback=lambda: "a")
        manager.create_box(content_callback=lambda: "b")
        results = manager.finish_all()
        assert len(results) == 2
        assert not manager.has_active_boxes


class TestThinkingBoxManagerSorting:
    """Test box ordering."""

    def test_sorted_by_order(self):
        manager = ThinkingBoxManager()
        box_high = manager.create_box(order=100)
        box_low = manager.create_box(order=0)
        sorted_ids = [b.box_id for b in manager.get_sorted_boxes()]
        assert sorted_ids == [box_low.box_id, box_high.box_id]

    def test_same_order_sorted_by_seq(self):
        manager = ThinkingBoxManager()
        box1 = manager.create_box(order=0)
        box2 = manager.create_box(order=0)
        sorted_ids = [b.box_id for b in manager.get_sorted_boxes()]
        assert sorted_ids == [box1.box_id, box2.box_id]

    def test_mixed_order_and_seq(self):
        manager = ThinkingBoxManager()
        box_a = manager.create_box(order=0)   # (0, 1)
        box_b = manager.create_box(order=100) # (100, 2)
        box_c = manager.create_box(order=0)   # (0, 3)
        sorted_ids = [b.box_id for b in manager.get_sorted_boxes()]
        assert sorted_ids == [box_a.box_id, box_c.box_id, box_b.box_id]


class TestThinkingBoxManagerExpandCollapse:
    """Test expand/collapse all."""

    def test_toggle_all_expands(self):
        manager = ThinkingBoxManager()
        box1 = manager.create_box()
        box2 = manager.create_box()
        manager.toggle_all()
        assert box1.control.is_expanded
        assert box2.control.is_expanded

    def test_toggle_all_collapses(self):
        manager = ThinkingBoxManager()
        box1 = manager.create_box()
        box2 = manager.create_box()
        manager.toggle_all()  # expand
        manager.toggle_all()  # collapse
        assert not box1.control.is_expanded
        assert not box2.control.is_expanded

    def test_expand_all(self):
        manager = ThinkingBoxManager()
        box = manager.create_box()
        manager.expand_all()
        assert box.control.is_expanded

    def test_collapse_all(self):
        manager = ThinkingBoxManager()
        box = manager.create_box()
        manager.expand_all()
        manager.collapse_all()
        assert not box.control.is_expanded

    def test_new_box_inherits_expanded_state(self):
        manager = ThinkingBoxManager()
        manager.create_box()
        manager.toggle_all()  # expand
        box2 = manager.create_box()
        assert box2.control.is_expanded

    def test_can_toggle_false_when_empty(self):
        manager = ThinkingBoxManager()
        assert not manager.can_toggle()

    def test_can_toggle_true_when_expanded(self):
        manager = ThinkingBoxManager()
        manager.create_box()
        manager.toggle_all()
        assert manager.can_toggle()
```

**Step 2: Run tests to verify they fail**

Run: `conda run -n thinking_prompt pytest tests/test_manager.py -v`
Expected: ImportError — module doesn't exist yet

**Step 3: Implement ManagedBox and ThinkingBoxManager**

Create `thinking_prompt/manager.py`:

```python
"""
ThinkingBoxManager - manages multiple thinking boxes.

Each box is a ManagedBox containing a ThinkingBoxControl, optional ThinkingHeader,
and a pre-built layout container. The manager handles creation, removal, sorting,
and bulk expand/collapse.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout import (
    FormattedTextControl,
    HSplit,
    Window,
)
from prompt_toolkit.layout.containers import Container
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.layout.margins import ConditionalMargin, ScrollbarMargin

from .layout import ThinkingHeader
from .thinking import ThinkingBoxControl
from .types import ContentFormat, StreamingContent


@dataclass
class ManagedBox:
    """State for one managed thinking box."""
    box_id: str
    control: ThinkingBoxControl
    header: Optional[ThinkingHeader]
    container: Container
    order: int
    seq: int
    streaming_content: Optional[StreamingContent]


class ThinkingBoxManager:
    """
    Manages a collection of thinking boxes.

    Handles creation, removal, sorting by (order, seq), and
    bulk expand/collapse. Thread-safe via RLock.
    """

    def __init__(
        self,
        default_max_lines: int = 15,
        default_style: str = "class:thinking-box",
    ) -> None:
        self._boxes: Dict[str, ManagedBox] = {}
        self._lock = threading.RLock()
        self._seq_counter = 0
        self._expanded = False
        self._default_max_lines = default_max_lines
        self._default_style = default_style

    def create_box(
        self,
        content_callback: Optional[Callable[[], str]] = None,
        *,
        title: Optional[str] = None,
        order: int = 0,
        max_lines: Optional[int] = None,
        content_format: ContentFormat = "plain",
        box_id: Optional[str] = None,
    ) -> ManagedBox:
        """Create and register a new thinking box."""
        with self._lock:
            self._seq_counter += 1
            seq = self._seq_counter

            if box_id is None:
                box_id = f"box-{seq}"

            effective_max_lines = max_lines or self._default_max_lines

            # Create streaming content if no callback provided
            streaming = None
            if content_callback is None:
                streaming = StreamingContent()
                content_callback = streaming.get_content

            # Create control
            control = ThinkingBoxControl(
                max_collapsed_lines=effective_max_lines,
                style=self._default_style,
            )
            control.start(content_callback, content_format=content_format)

            # Apply current expand state
            if self._expanded:
                control.expand()

            # Create header if title provided
            header = None
            if title is not None:
                header = ThinkingHeader(text=title)

            # Build container
            container = self._build_container(control, header, effective_max_lines)

            box = ManagedBox(
                box_id=box_id,
                control=control,
                header=header,
                container=container,
                order=order,
                seq=seq,
                streaming_content=streaming,
            )

            self._boxes[box_id] = box
            return box

    def remove_box(self, box_id: str) -> Tuple[str, bool, ContentFormat]:
        """Remove a box and return its final (content, was_expanded, format)."""
        with self._lock:
            box = self._boxes.pop(box_id, None)
            if box is None:
                return "", False, "plain"
            return box.control.finish()

    def get_sorted_boxes(self) -> List[ManagedBox]:
        """Return boxes sorted by (order, seq)."""
        with self._lock:
            return sorted(self._boxes.values(), key=lambda b: (b.order, b.seq))

    def get_container(self) -> Container:
        """Return an HSplit of sorted box containers, or empty Window."""
        with self._lock:
            if not self._boxes:
                return Window(height=0)
            sorted_boxes = sorted(
                self._boxes.values(),
                key=lambda b: (b.order, b.seq),
            )
            return HSplit([b.container for b in sorted_boxes])

    def toggle_all(self) -> None:
        """Toggle expand/collapse on all boxes."""
        with self._lock:
            self._expanded = not self._expanded
            for box in self._boxes.values():
                if self._expanded:
                    box.control.expand()
                else:
                    box.control.collapse()

    def expand_all(self) -> None:
        """Expand all boxes."""
        with self._lock:
            self._expanded = True
            for box in self._boxes.values():
                box.control.expand()

    def collapse_all(self) -> None:
        """Collapse all boxes."""
        with self._lock:
            self._expanded = False
            for box in self._boxes.values():
                box.control.collapse()

    def can_toggle(self) -> bool:
        """Check if toggle is meaningful (any box can toggle or already expanded)."""
        with self._lock:
            if self._expanded:
                return True
            return any(
                box.control.can_toggle_expanded for box in self._boxes.values()
            )

    def finish_all(self) -> List[Tuple[str, str, bool, ContentFormat]]:
        """Finish all boxes. Returns list of (box_id, content, was_expanded, format)."""
        with self._lock:
            results = []
            for box_id in list(self._boxes.keys()):
                content, was_expanded, fmt = self.remove_box(box_id)
                results.append((box_id, content, was_expanded, fmt))
            return results

    @property
    def has_active_boxes(self) -> bool:
        """Check if any boxes are active."""
        with self._lock:
            return len(self._boxes) > 0

    @property
    def active_count(self) -> int:
        """Number of active boxes."""
        with self._lock:
            return len(self._boxes)

    def _build_container(
        self,
        control: ThinkingBoxControl,
        header: Optional[ThinkingHeader],
        max_lines: int,
    ) -> Container:
        """Build the layout container for a box."""
        def get_height() -> D:
            if control.is_expanded:
                return D(min=5, preferred=20, max=40)
            line_count = control.get_line_count()
            height = min(max(1, line_count), max_lines)
            return D(min=1, max=max_lines, preferred=height)

        is_expanded_filter = Condition(lambda: control.is_expanded)

        content_window = Window(
            content=control,
            height=get_height,
            wrap_lines=True,
            dont_extend_height=True,
            right_margins=[
                ConditionalMargin(
                    ScrollbarMargin(display_arrows=True),
                    filter=is_expanded_filter,
                ),
            ],
        )

        if header is not None:
            header_control = FormattedTextControl(
                text=lambda h=header: h.get_formatted_text(80)
            )
            header_window = Window(
                content=header_control,
                height=D.exact(1),
            )
            return HSplit([header_window, content_window])

        return content_window
```

**Step 4: Run tests**

Run: `conda run -n thinking_prompt pytest tests/test_manager.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add thinking_prompt/manager.py tests/test_manager.py
git commit -m "feat: add ThinkingBoxManager for multi-box support"
```

---

### Task 3: Add finish() to ThinkingContext

**Files:**
- Modify: `thinking_prompt/types.py:181-283` (ThinkingContext class)
- Modify: `tests/test_thinking_context.py`

**Step 1: Write failing tests for ThinkingContext.finish()**

Add to `tests/test_thinking_context.py`:

```python
class TestThinkingContextFinish:
    """Test ThinkingContext.finish() method."""

    def test_finish_calls_callback(self):
        finish_mock = MagicMock(return_value="content")
        ctx = ThinkingContext(
            StreamingContent(),
            set_title=MagicMock(),
            get_title=lambda: "",
            finish=finish_mock,
        )
        result = ctx.finish()
        finish_mock.assert_called_once_with(add_to_history=True, echo_to_console=None)
        assert result == "content"

    def test_finish_passes_kwargs(self):
        finish_mock = MagicMock(return_value="content")
        ctx = ThinkingContext(
            StreamingContent(),
            set_title=MagicMock(),
            get_title=lambda: "",
            finish=finish_mock,
        )
        ctx.finish(add_to_history=False, echo_to_console=True)
        finish_mock.assert_called_once_with(add_to_history=False, echo_to_console=True)

    def test_finish_raises_without_callback(self):
        ctx = ThinkingContext(
            StreamingContent(),
            set_title=MagicMock(),
            get_title=lambda: "",
        )
        with pytest.raises(RuntimeError, match="No finish callback"):
            ctx.finish()

    def test_finish_works_without_content(self):
        """finish() should work even when content is None (low-level API)."""
        finish_mock = MagicMock(return_value="")
        ctx = ThinkingContext(
            None,
            set_title=MagicMock(),
            get_title=lambda: "",
            finish=finish_mock,
        )
        ctx.finish()
        finish_mock.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `conda run -n thinking_prompt pytest tests/test_thinking_context.py::TestThinkingContextFinish -v`
Expected: FAIL — `finish` parameter doesn't exist

**Step 3: Implement finish() on ThinkingContext**

In `thinking_prompt/types.py`, modify `ThinkingContext.__init__` to accept a `finish` callback, and add the `finish()` method:

```python
class ThinkingContext:
    def __init__(
        self,
        content: Optional[StreamingContent],
        set_title: Callable[[str], None],
        get_title: Callable[[], str],
        set_format: Optional[Callable[[ContentFormat], None]] = None,
        rich_theme: Any = None,
        finish: Optional[Callable[..., str]] = None,
    ) -> None:
        self._content = content
        self._set_title = set_title
        self._get_title = get_title
        self._set_format = set_format
        self._format_set = False
        self._rich_theme = rich_theme
        self._finish = finish

    def finish(
        self,
        add_to_history: bool = True,
        echo_to_console: Optional[bool] = None,
    ) -> str:
        """Finish this thinking box and remove it from display.

        Args:
            add_to_history: If True, add content to chat history.
            echo_to_console: If True, print content to console.

        Returns:
            The full content that was displayed.

        Raises:
            RuntimeError: If no finish callback was provided.
        """
        if self._finish is None:
            raise RuntimeError(
                "No finish callback — use session.finish_thinking() "
                "or the thinking() context manager instead."
            )
        return self._finish(
            add_to_history=add_to_history, echo_to_console=echo_to_console
        )
```

**Step 4: Run tests**

Run: `conda run -n thinking_prompt pytest tests/test_thinking_context.py -v`
Expected: All pass (old + new)

**Step 5: Commit**

```bash
git add thinking_prompt/types.py tests/test_thinking_context.py
git commit -m "feat: add finish() method to ThinkingContext"
```

---

### Task 4: Update layout to use DynamicContainer

**Files:**
- Modify: `thinking_prompt/layout.py:335-467` (create_layout function)

**Step 1: Add create_thinking_area function**

In `thinking_prompt/layout.py`, add a new function and import `DynamicContainer`:

```python
from prompt_toolkit.layout import DynamicContainer

def create_thinking_area(manager) -> DynamicContainer:
    """Create a dynamic container that renders active thinking boxes.

    The container re-evaluates on each render, returning an HSplit
    of currently active boxes sorted by (order, seq).

    Args:
        manager: ThinkingBoxManager instance.

    Returns:
        DynamicContainer wrapping the manager's sorted boxes.
    """
    return DynamicContainer(lambda: manager.get_container())
```

**Step 2: Update create_layout to accept manager instead of single control**

Change `create_layout` signature. Keep the old `thinking_control` parameter as optional for backward compat during transition, but add `thinking_manager` parameter:

```python
def create_layout(
    default_buffer: Buffer,
    message: Callable[[], AnyFormattedText],
    max_thinking_height: int,
    history: FormattedTextHistory,
    is_fullscreen: Callable[[], bool],
    get_status_text: Callable[[], AnyFormattedText],
    is_status_bar_enabled: Callable[[], bool],
    thinking_manager=None,
    completions_menu_height: int = 5,
) -> Layout:
```

In the body, replace:
```python
thinking_box = create_thinking_box(...)
```
with:
```python
thinking_area = create_thinking_area(thinking_manager)
```

And in main_layout HSplit, replace `thinking_box` with `thinking_area`.

Remove `thinking_control` and `separator` parameters. Remove `create_thinking_box` function (no longer needed — the manager builds containers internally).

**Step 3: Run tests**

Run: `conda run -n thinking_prompt pytest tests/ -v`
Expected: Some tests may fail due to changed signature — fix in Task 5

**Step 4: Commit**

```bash
git add thinking_prompt/layout.py
git commit -m "feat: replace static thinking box with DynamicContainer"
```

---

### Task 5: Update ThinkingPromptSession

**Files:**
- Modify: `thinking_prompt/session.py`
- Modify: `tests/test_thinking_context.py` (session integration tests)

This is the largest task. It rewires the session to use `ThinkingBoxManager`.

**Step 1: Update imports and constructor**

In `thinking_prompt/session.py`:

Add import:
```python
from .manager import ThinkingBoxManager
```

In `__init__`, replace:
```python
self._thinking_control = ThinkingBoxControl(
    max_collapsed_lines=max_thinking_height,
    style="class:thinking-box",
    expand_key=self._expand_key,
)
```
with:
```python
self._manager = ThinkingBoxManager(
    default_max_lines=max_thinking_height,
)
```

**Step 2: Update _create_session_layout**

Replace the single separator + control approach:

```python
def _create_session_layout(self):
    self._default_thinking_text = (
        self._app_info.thinking_text if self._app_info else "Thinking"
    )
    # Store header config from app_info for creating per-box headers
    self._header_config = {}
    if self._app_info:
        self._header_config = {
            "frames": self._app_info.thinking_animation,
            "position": self._app_info.thinking_animation_position,
        }

    return create_layout(
        default_buffer=self.default_buffer,
        message=lambda: self._message,
        max_thinking_height=self._max_thinking_height,
        history=self._display.history,
        is_fullscreen=lambda: self._is_fullscreen,
        get_status_text=lambda: self._status_text,
        is_status_bar_enabled=lambda: self._enable_status_bar,
        thinking_manager=self._manager,
        completions_menu_height=self._completions_menu_height,
    )
```

**Step 3: Update _create_key_bindings**

Replace the thinking box key bindings section:

```python
def _create_key_bindings(self) -> KeyBindings:
    kb = KeyBindings()

    # Cancel/interrupt
    @kb.add("c-c")
    def cancel(event: KeyPressEvent) -> None:
        if self._manager.has_active_boxes:
            self._manager.finish_all()
            self._invalidate()
            if self._pending_input and not self._pending_input.done():
                self._pending_input.cancel()
        else:
            event.app.exit()

    # Exit
    @kb.add("c-d")
    def exit_app(event: KeyPressEvent) -> None:
        event.app.exit()

    # Enter to submit
    @kb.add("enter", filter=has_focus(DEFAULT_BUFFER))
    def accept_input(event: KeyPressEvent) -> None:
        self.default_buffer.validate_and_handle()

    # Expand/collapse all thinking boxes
    def can_toggle() -> bool:
        if not self._manager.can_toggle():
            return False
        if self._is_fullscreen:
            return False
        return True

    @kb.add(self._expand_key, filter=Condition(can_toggle))
    def toggle_expand(event: KeyPressEvent) -> None:
        self._manager.toggle_all()

    # Fullscreen toggle
    if self._fullscreen_enabled:
        @kb.add(self._fullscreen_key)
        def toggle_fullscreen(event: KeyPressEvent) -> None:
            if self._is_fullscreen:
                self.switch_to_prompt()
            else:
                if self._manager.has_active_boxes:
                    self._manager.expand_all()
                self.switch_to_fullscreen()

    return kb
```

**Step 4: Rewrite start_thinking**

```python
def start_thinking(
    self,
    content_callback: Optional[Callable[[], str]] = None,
    *,
    title: Optional[str] = None,
    order: int = 0,
    max_lines: Optional[int] = None,
    content_format: "ContentFormat" = "plain",
) -> ThinkingContext:
    # Build header kwargs from app_info config
    header_title = title
    box = self._manager.create_box(
        content_callback=content_callback,
        title=header_title,
        order=order,
        max_lines=max_lines,
        content_format=content_format,
    )

    # Apply header config from app_info if header was created
    if box.header and self._header_config:
        if "frames" in self._header_config:
            box.header.frames = self._header_config["frames"]
        if "position" in self._header_config:
            box.header.position = self._header_config["position"]

    self._invalidate()

    # Build finish callback for this specific box
    def _finish_box(
        add_to_history: bool = True,
        echo_to_console: Optional[bool] = None,
    ) -> str:
        full_content, _, content_format_val = self._manager.remove_box(box.box_id)
        should_echo = (
            echo_to_console if echo_to_console is not None else self._echo_thinking
        )
        if full_content.strip():
            self._display.thinking(
                full_content,
                truncate_lines=box.control.max_collapsed_lines,
                add_to_history=add_to_history,
                echo_to_console=should_echo,
                content_format=content_format_val,
            )
        self._invalidate()
        return full_content

    return ThinkingContext(
        content=box.streaming_content,
        set_title=lambda t: setattr(box.header, 'text', t) if box.header else None,
        get_title=lambda: box.header.text if box.header else self._default_thinking_text,
        set_format=box.control.set_content_format,
        rich_theme=self._display.rich_theme,
        finish=_finish_box,
    )
```

**Step 5: Rewrite finish_thinking (backward compat — finishes all)**

```python
def finish_thinking(
    self,
    add_to_history: bool = True,
    echo_to_console: Optional[bool] = None,
) -> str:
    if not self._manager.has_active_boxes:
        return ""

    should_echo = (
        echo_to_console if echo_to_console is not None else self._echo_thinking
    )

    results = self._manager.finish_all()
    all_content = []

    for box_id, full_content, _, content_format_val in results:
        if full_content.strip():
            self._display.thinking(
                full_content,
                truncate_lines=self._max_thinking_height,
                add_to_history=add_to_history,
                echo_to_console=should_echo,
                content_format=content_format_val,
            )
            all_content.append(full_content)

    self._invalidate()
    return "\n".join(all_content)
```

**Step 6: Update is_thinking property**

```python
@property
def is_thinking(self) -> bool:
    """Check if any thinking box is active."""
    return self._manager.has_active_boxes
```

**Step 7: Update thinking() context manager**

```python
@asynccontextmanager
async def thinking(
    self,
    *,
    title: Optional[str] = None,
    content_format: "ContentFormat" = "plain",
    add_to_history: bool = True,
    echo_to_console: Optional[bool] = None,
    order: int = 0,
    max_lines: Optional[int] = None,
) -> AsyncIterator[ThinkingContext]:
    ctx = self.start_thinking(
        title=title,
        content_format=content_format,
        order=order,
        max_lines=max_lines,
    )
    try:
        yield ctx
        ctx.finish(add_to_history=add_to_history, echo_to_console=echo_to_console)
    except BaseException:
        ctx.finish(add_to_history=False, echo_to_console=False)
        raise
```

**Step 8: Remove old helper methods**

Remove `_set_thinking_title`, `_get_thinking_title` — title is now per-box via ThinkingContext.

Remove `self._thinking_separator` / `self._thinking_header` references.

Remove `self._thinking_control` references.

**Step 9: Run tests and fix breakage**

Run: `conda run -n thinking_prompt pytest tests/ -v`

Expected: Several test failures in `test_thinking_context.py` due to removed `session._thinking_separator` / `session._thinking_header` / `session._thinking_control`.

Update `tests/test_thinking_context.py`:

- `TestSessionThinkingTitle`: Rewrite tests to use ThinkingContext API instead of accessing internal `_thinking_separator`. For example, check `ctx.title` instead of `session._thinking_separator.text`.
- `TestThinkingContextRichSessionIntegration.test_append_rich_auto_switches_format_in_session`: Remove or rework — can't access `session._thinking_control` directly. Test through ctx instead.

**Step 10: Run tests**

Run: `conda run -n thinking_prompt pytest tests/ -v`
Expected: All pass

**Step 11: Commit**

```bash
git add thinking_prompt/session.py thinking_prompt/manager.py tests/
git commit -m "feat: integrate ThinkingBoxManager into session for multi-box support"
```

---

### Task 6: Update exports

**Files:**
- Modify: `thinking_prompt/__init__.py`

**Step 1: Add new exports**

Add to `thinking_prompt/__init__.py`:

```python
from .manager import ThinkingBoxManager, ManagedBox
from .layout import ThinkingHeader
```

Add to `__all__`:
```python
"ThinkingHeader",
```

Note: `ThinkingBoxManager` and `ManagedBox` are internal — don't add to `__all__` unless users need them directly. `ThinkingHeader` is useful for custom header config.

**Step 2: Run all tests**

Run: `conda run -n thinking_prompt pytest tests/ -v`
Expected: All pass

**Step 3: Commit**

```bash
git add thinking_prompt/__init__.py
git commit -m "feat: export ThinkingHeader"
```

---

### Task 7: Multi-box integration tests

**Files:**
- Create: `tests/test_multi_box.py`

**Step 1: Write integration tests**

```python
"""Integration tests for multi-box thinking."""
from __future__ import annotations

import pytest

from thinking_prompt import ThinkingPromptSession, AppInfo, ThinkingContext


def _make_session(**kwargs):
    app_info = AppInfo(name="Test", version="0.0.1", thinking_text="Thinking")
    return ThinkingPromptSession(app_info=app_info, **kwargs)


class TestMultiBoxLifecycle:
    """Test multiple boxes created and finished independently."""

    def test_multiple_start_thinking(self):
        session = _make_session()
        ctx1 = session.start_thinking(title="Box 1")
        ctx2 = session.start_thinking(title="Box 2")
        assert session.is_thinking
        assert session._manager.active_count == 2
        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)

    def test_finish_one_keeps_others(self):
        session = _make_session()
        ctx1 = session.start_thinking(title="Box 1")
        ctx2 = session.start_thinking(title="Box 2")
        ctx1.finish(add_to_history=False, echo_to_console=False)
        assert session.is_thinking  # ctx2 still active
        assert session._manager.active_count == 1
        ctx2.finish(add_to_history=False, echo_to_console=False)

    def test_finish_all_via_session(self):
        session = _make_session()
        session.start_thinking(title="Box 1")
        session.start_thinking(title="Box 2")
        session.finish_thinking(add_to_history=False, echo_to_console=False)
        assert not session.is_thinking

    def test_ctx_finish_returns_content(self):
        session = _make_session()
        ctx = session.start_thinking()
        ctx.append("hello\n")
        content = ctx.finish(add_to_history=False, echo_to_console=False)
        assert content == "hello\n"

    @pytest.mark.asyncio
    async def test_context_manager_multi_box(self):
        session = _make_session()
        async with session.thinking(
            title="Outer", add_to_history=False, echo_to_console=False
        ) as ctx1:
            ctx1.append("outer\n")
            async with session.thinking(
                title="Inner", add_to_history=False, echo_to_console=False
            ) as ctx2:
                ctx2.append("inner\n")
                assert session._manager.active_count == 2
            # Inner finished
            assert session._manager.active_count == 1
        # Outer finished
        assert not session.is_thinking


class TestMultiBoxOrdering:
    """Test box ordering."""

    def test_boxes_sorted_by_order(self):
        session = _make_session()
        ctx_high = session.start_thinking(title="High", order=100)
        ctx_low = session.start_thinking(title="Low", order=0)
        boxes = session._manager.get_sorted_boxes()
        assert boxes[0].order == 0  # low first
        assert boxes[1].order == 100  # high second (closer to prompt)
        ctx_high.finish(add_to_history=False, echo_to_console=False)
        ctx_low.finish(add_to_history=False, echo_to_console=False)


class TestMultiBoxExpandCollapse:
    """Test expand/collapse all boxes."""

    def test_toggle_expands_all(self):
        session = _make_session()
        ctx1 = session.start_thinking()
        ctx2 = session.start_thinking()
        session._manager.toggle_all()
        boxes = session._manager.get_sorted_boxes()
        assert all(b.control.is_expanded for b in boxes)
        ctx1.finish(add_to_history=False, echo_to_console=False)
        ctx2.finish(add_to_history=False, echo_to_console=False)


class TestMultiBoxBackwardCompat:
    """Ensure single-box usage works exactly as before."""

    def test_single_box_start_finish(self):
        session = _make_session()
        ctx = session.start_thinking(lambda: "content", title="Working")
        assert session.is_thinking
        result = session.finish_thinking(add_to_history=False, echo_to_console=False)
        assert result == "content"
        assert not session.is_thinking

    @pytest.mark.asyncio
    async def test_single_box_context_manager(self):
        session = _make_session()
        async with session.thinking(
            title="Working", add_to_history=False, echo_to_console=False
        ) as ctx:
            ctx.append("hello\n")
            assert session.is_thinking
        assert not session.is_thinking

    def test_start_thinking_with_callback(self):
        session = _make_session()
        chunks = []
        ctx = session.start_thinking(lambda: "".join(chunks))
        chunks.append("test")
        assert ctx.title == "Thinking"  # default
        session.finish_thinking(add_to_history=False, echo_to_console=False)
```

**Step 2: Run tests**

Run: `conda run -n thinking_prompt pytest tests/test_multi_box.py -v`
Expected: All pass

**Step 3: Run full test suite**

Run: `conda run -n thinking_prompt pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add tests/test_multi_box.py
git commit -m "test: add multi-box integration tests"
```

---

### Task 8: Multi-box example

**Files:**
- Create: `examples/demo_multi_box.py`

**Step 1: Write example demonstrating multi-box usage**

```python
"""
Demo: Multiple thinking boxes running concurrently.

Shows:
- Multiple independent boxes with different lifetimes
- Box ordering (task list anchored near prompt)
- Boxes appearing and disappearing dynamically
"""
import asyncio
from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    app_info = AppInfo(
        name="MultiBoxDemo",
        version="1.0.0",
        thinking_text="Thinking",
    )
    session = ThinkingPromptSession(app_info=app_info, message=">>> ")

    @session.on_input
    async def handle(text: str):
        if not text.strip():
            return

        if text.strip() == "/quit":
            session.exit()
            return

        # Task list box — anchored near prompt with order=100
        tasks = session.start_thinking(title="Tasks", order=100, max_lines=10)
        tasks.append_rich("[dim]  ○ Download data[/dim]\n")
        tasks.append_rich("[dim]  ○ Process data[/dim]\n")
        tasks.append_rich("[dim]  ○ Generate report[/dim]\n")

        # Step 1: Download
        tasks.set_line_rich(0, "[bold cyan]  ⟳ Downloading data…[/bold cyan]")
        dl = session.start_thinking(title="Download", max_lines=2)
        for pct in range(0, 101, 20):
            dl.append(f"\r  {pct}% complete")
            dl.set_line(0, f"  {pct}% complete")
            await asyncio.sleep(0.3)
        dl.finish(echo_to_console=False, add_to_history=False)
        tasks.set_line_rich(0, "[green]  ✓ Download data[/green]")

        # Step 2: Process
        tasks.set_line_rich(1, "[bold cyan]  ⟳ Processing data…[/bold cyan]")
        proc = session.start_thinking(title="Process", max_lines=2)
        for i in range(5):
            proc.set_line(0, f"  Processing batch {i+1}/5...")
            await asyncio.sleep(0.4)
        proc.finish(echo_to_console=False, add_to_history=False)
        tasks.set_line_rich(1, "[green]  ✓ Process data[/green]")

        # Step 3: Report
        tasks.set_line_rich(2, "[bold cyan]  ⟳ Generating report…[/bold cyan]")
        await asyncio.sleep(0.5)
        tasks.set_line_rich(2, "[green]  ✓ Generate report[/green]")

        await asyncio.sleep(0.5)
        tasks.finish(echo_to_console=False, add_to_history=False)

        session.add_success("All tasks complete!")

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Test manually**

Run: `conda run -n thinking_prompt python examples/demo_multi_box.py`
Expected: Type any text to see multi-box demo. `/quit` to exit.

**Step 3: Commit**

```bash
git add examples/demo_multi_box.py
git commit -m "feat(examples): add multi-box thinking demo"
```

---

### Task 9: Update unreleased changes

**Files:**
- Modify: `changes/unreleased.md`

**Step 1: Update changelog**

```markdown
### Added
- Multiple thinking boxes: `start_thinking()` can be called multiple times to create independent boxes
- `ThinkingContext.finish()` method for finishing individual boxes
- Box ordering via `order` parameter (higher = closer to prompt)
- Per-box `max_lines` configuration
- `ThinkingHeader` class (renamed from `ThinkingSeparator`)

### Changed
- `start_thinking()` now accepts optional `order` and `max_lines` parameters
- `thinking()` context manager now accepts `order` and `max_lines` parameters
- `finish_thinking()` finishes all active boxes (backward compatible)
- `is_thinking` returns True if any box is active
- Ctrl+T expands/collapses all boxes together
```

**Step 2: Commit**

```bash
git add changes/unreleased.md
git commit -m "docs: update unreleased changes for multi-box feature"
```
