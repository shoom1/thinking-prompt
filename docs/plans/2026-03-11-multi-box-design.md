# Multi-Box Thinking Design

## Overview

Add support for multiple independent thinking boxes that stack vertically above the prompt. Each box has its own content, optional animated header, height, and lifecycle. Boxes are sorted by an `order` key (higher = closer to prompt) with creation order as tiebreaker.

## Use Cases

- Multiple parallel tasks showing 1-2 lines of progress each
- A persistent task list (~10 lines) anchored near the prompt while transient progress boxes appear/disappear above it
- Any combination of independent thinking operations

## Architecture

### Components

```
ThinkingPromptSession
  └── ThinkingBoxManager
        ├── ManagedBox(control, header, container, order=0, seq=1)
        ├── ManagedBox(control, header, container, order=0, seq=2)
        └── ManagedBox(control, header, container, order=100, seq=3)
              ↓
        DynamicContainer → HSplit([box1.container, box2.container, box3.container])
```

### ManagedBox

Dataclass holding one box's state:

- `box_id: str` — unique identifier (auto-generated or user-provided)
- `control: ThinkingBoxControl` — content widget (created once, reused)
- `header: Optional[ThinkingHeader]` — animated header (only if title provided)
- `container` — layout wrapper: `HSplit([header_window, content_window])` or just `content_window`
- `order: int` — sort key (higher = closer to prompt, default 0)
- `seq: int` — creation sequence for stable ordering within same order

### ThinkingBoxManager (new file: manager.py)

Manages the collection of active boxes:

- `create_box(title, order, max_lines, content_format) → ManagedBox`
- `remove_box(box_id)` — removes box immediately
- `get_container() → Container` — returns `HSplit(sorted_boxes)` or empty `Window(height=0)`
- `expand_all()` / `collapse_all()` / `toggle_all()`
- `has_active_boxes: bool`
- Thread-safe via RLock

### ThinkingHeader (renamed from ThinkingSeparator)

Renamed to reflect its role as a box header rather than a separator. Same functionality: animated spinner + title text on a bordered line. Optional per box — no header by default; created only when `title` is provided.

## Layout Changes

In `create_layout()`, the single `thinking_box` slot is replaced with a `DynamicContainer`:

```python
# Before
thinking_box = create_thinking_box(control, max_height, separator)

# After
thinking_area = DynamicContainer(lambda: manager.get_container())
```

The `DynamicContainer` re-evaluates on each render (~100ms), returning an `HSplit` of currently active boxes sorted by `(order, seq)`. Box containers (Windows, Controls) are created once per box and reused — only the `HSplit` wrapper is new each render.

## API

### Starting boxes

```python
# Low-level: provide your own callback
ctx = session.start_thinking(
    content_callback=my_callback,
    title="Processing",
    order=0,
    max_lines=5,
    content_format="plain",
)

# High-level: StreamingContent managed internally
ctx = session.start_thinking(title="Tasks", order=100, max_lines=10)
ctx.append("working...\n")
```

### Finishing boxes

```python
# Finish one box
ctx.finish()
ctx.finish(echo_to_console=True)
ctx.finish(add_to_history=True)

# Finish all boxes (backward compat)
session.finish_thinking()
```

### Context manager (unchanged for single box, works for multiple)

```python
async with session.thinking(title="Task 1") as ctx1:
    async with session.thinking(title="Task 2") as ctx2:
        ctx1.append("...\n")
        ctx2.append("...\n")
```

### Backward compatibility

- Single-box usage works exactly as today
- `session.is_thinking` returns True if any box is active
- `session.finish_thinking()` finishes all boxes
- Ctrl+T expands/collapses all boxes together

## Expand/Collapse

- Single `_expanded` boolean on the manager — all boxes toggle together
- Ctrl+T toggles all (disabled in fullscreen, same as today)
- Each box shows its own expand hint when content overflows its `max_lines`
- When expanded, each box uses flexible height: `D(min=5, preferred=20, max=40)`

## Sorting

Boxes sorted by `(order, seq)`:
- Lower `order` at top, higher `order` at bottom (closer to prompt)
- Within same `order`, earlier-created boxes appear first
- When a box is removed, remaining boxes shift up naturally

## Thread Safety

- `ThinkingBoxManager` uses RLock for the box list
- Individual `ThinkingBoxControl` instances keep their own locks
- `get_container()` returns a snapshot under lock

## Files Changed

| File | Change |
|------|--------|
| `manager.py` | **New** — `ThinkingBoxManager`, `ManagedBox` |
| `thinking.py` | Remove per-control expand state (moved to manager) |
| `layout.py` | Rename `ThinkingSeparator` → `ThinkingHeader`, replace `create_thinking_box` with `create_thinking_area` using `DynamicContainer` |
| `session.py` | Replace single `_thinking_control` with `ThinkingBoxManager`, update `start_thinking`/`finish_thinking` |
| `types.py` | Add `finish()` to `ThinkingContext` |
| `__init__.py` | Export new public types |
