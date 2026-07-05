# thinking-prompt

A prompt_toolkit extension that adds a "thinking box" above the prompt for displaying AI thinking/processing content with real-time streaming updates.

![Demo](img/demo.gif)

## Features

- **Thinking Box**: A collapsible area above the prompt that shows processing/thinking content
- **Multiple Thinking Boxes**: Run multiple independent boxes concurrently with ordering and per-box lifecycle control
- **Real-time Streaming**: Content updates in real-time as your callback returns new content
- **Fullscreen Mode**: Optional fullscreen mode with chat history (disabled by default)
- **Animated Header**: Configurable animated indicator showing thinking is in progress
- **Rich Output**: Support for markdown rendering and syntax-highlighted code blocks
- **Rich/ANSI in Thinking Box**: Use Rich markup for styled, in-place-updating content inside the thinking box
- **Customizable Styles**: Full control over colors and styling

## Installation

```bash
pip install thinking-prompt
```

For markdown and code highlighting support:
```bash
pip install thinking-prompt[all]
```

## Quick Start

```python
import asyncio
from thinking_prompt import ThinkingPromptSession, AppInfo

async def main():
    app_info = AppInfo(name="MyApp", version="1.0.0")
    session = ThinkingPromptSession(app_info=app_info, message=">>> ")

    @session.on_input
    async def handle(text: str):
        if not text.strip():
            return

        # Use context manager for clean thinking management
        async with session.thinking() as content:
            content.append("Processing...\n")
            await asyncio.sleep(0.5)
            content.append("Done!\n")

        session.add_response(f"You said: {text}")

    await session.run_async()

if __name__ == "__main__":
    asyncio.run(main())
```

> **Note — input handlers run on the event loop.** A synchronous handler
> blocks the UI for its entire duration: the screen freezes, the spinner
> stops, and Ctrl+C is not processed until it returns. Use an `async`
> handler for anything that takes time, and wrap blocking calls with
> `await asyncio.to_thread(...)` so the UI stays responsive.

## Key Bindings

| Key | Action |
|-----|--------|
| Ctrl+T | Expand/collapse all thinking boxes (in prompt mode) |
| Ctrl+E | Toggle fullscreen mode (when enabled) |
| Ctrl+C | Cancel current operation or exit |
| Ctrl+D | Exit application (empty input line only) |

## API Reference

### ThinkingPromptSession

The main class for creating a thinking-enabled prompt session.

```python
session = ThinkingPromptSession(
    message=">>> ",              # Prompt message
    app_info=AppInfo(...),       # App metadata and configuration
    max_thinking_height=15,      # Max lines when collapsed
    enable_status_bar=True,      # Show status bar
    echo_input=True,             # Echo user input to console
    complete_while_typing=True,  # Show completions as you type
    completions_menu_height=6,   # Max rows in completions popup
)
```

### Thinking API

**Context Manager (recommended):**
```python
async with session.thinking(title="Processing") as ctx:
    ctx.append("Step 1...\n")
    await asyncio.sleep(0.5)
    ctx.append("Step 2...\n")
# Automatically finishes when exiting context
```

**Manual control:**
```python
# Start with a content callback
chunks = []
ctx = session.start_thinking(lambda: ''.join(chunks))

chunks.append("Processing...\n")
await asyncio.sleep(0.5)

# Finish this specific box and optionally echo to console
ctx.finish(add_to_history=True, echo_to_console=True)
```

### Multiple Thinking Boxes

Run multiple boxes concurrently with independent lifecycles. Use `order` to control positioning (higher = closer to prompt):

```python
# Task list pinned near the prompt
tasks = session.start_thinking(title="Tasks", order=100, max_lines=10)
tasks.append_rich("[dim]  ○ Download[/dim]\n")
tasks.append_rich("[dim]  ○ Process[/dim]\n")
tasks.append_rich("[dim]  ○ Report[/dim]\n")

# Step 1: separate detail box appears above the task list
tasks.set_line_rich(0, "[bold cyan]  ⟳ Downloading…[/bold cyan]")
dl = session.start_thinking(title="Download", max_lines=2)
for pct in range(0, 101, 20):
    dl.set_line(0, f"  {pct}% complete")
    await asyncio.sleep(0.3)
dl.finish(echo_to_console=False, add_to_history=False)
tasks.set_line_rich(0, "[green]  ✓ Download[/green]")

# Step 2: another detail box
tasks.set_line_rich(1, "[bold cyan]  ⟳ Processing…[/bold cyan]")
proc = session.start_thinking(title="Process", max_lines=2)
for i in range(5):
    proc.set_line(0, f"  Batch {i+1}/5...")
    await asyncio.sleep(0.4)
proc.finish(echo_to_console=False, add_to_history=False)
tasks.set_line_rich(1, "[green]  ✓ Process[/green]")

# Finish task list
tasks.finish(echo_to_console=False, add_to_history=False)
```

### Rich/ANSI Content in Thinking Box

Use `append_rich()` and `set_line_rich()` for styled content with [Rich markup](https://rich.readthedocs.io/):

```python
async with session.thinking(title="Processing") as ctx:
    ctx.append_rich("[dim]  ○ Load data[/dim]\n")
    ctx.append_rich("[dim]  ○ Transform[/dim]\n")

    ctx.set_line_rich(0, "[bold cyan]  ⟳ Load data…[/bold cyan]")
    ctx.set_title("Loading")
    await asyncio.sleep(1)
    ctx.set_line_rich(0, "[green]  ✓ Load data[/green]")

    ctx.set_line_rich(1, "[bold cyan]  ⟳ Transform…[/bold cyan]")
    ctx.set_title("Transforming")
    await asyncio.sleep(1)
    ctx.set_line_rich(1, "[green]  ✓ Transform[/green]")
```

### Dynamic Titles & In-Place Updates

Use `set_title()` to change the thinking header and `set_line()` to update lines in place:

```python
async with session.thinking(title="Downloading") as ctx:
    ctx.append("Progress: 0%\n")
    for i in range(1, 101):
        ctx.set_line(-1, f"Progress: {i}%")
        ctx.set_title(f"Downloading {i}%")
        await asyncio.sleep(0.02)
```

### Output Methods

```python
# Plain text response
session.add_response("Hello, world!")

# Markdown (requires rich)
session.add_response("# Title\n- Item 1\n- Item 2", markdown=True)

# Syntax-highlighted code (requires pygments)
session.add_code("def hello(): return 'world'", language="python")

# Status bar text
session.set_status("Ready")                    # Plain text
from rich.text import Text
session.set_status(Text.from_markup("[bold]Processing[/bold]"))  # Rich renderable

# Status messages
session.add_success("Operation completed")
session.add_warning("Rate limit approaching")
session.add_error("Connection failed")
session.add_message("system", "Connecting to server...")
```

### Dialogs

```python
# Yes/No confirmation
result = await session.yes_no_dialog("Confirm", "Delete this item?")
if result:
    # User clicked Yes

# Message dialog
await session.message_dialog("Info", "Operation completed!")

# Choice dialog (multiple buttons)
action = await session.choice_dialog("Action", "What to do?", ["Save", "Discard", "Cancel"])

# Dropdown selection
theme = await session.dropdown_dialog("Theme", "Choose:", ["Light", "Dark", "System"])

# Custom dialog
from thinking_prompt import DialogConfig, ButtonConfig
config = DialogConfig(
    title="Custom",
    body="Choose an option:",
    buttons=[
        ButtonConfig(text="Option A", result="a"),
        ButtonConfig(text="Option B", result="b"),
    ],
)
result = await session.show_dialog(config)
```

### Settings Dialog

A form-based dialog for configuring multiple settings at once:

```python
from thinking_prompt.settings_dialog import (
    SettingsDialog,
    DropdownItem,
    InlineSelectItem,
    TextItem,
    CheckboxItem,
)

items = [
    DropdownItem(
        key="theme",
        label="Theme",
        description="Application color scheme",
        options=["Light", "Dark", "System"],
        default="System",
    ),
    InlineSelectItem(
        key="font_size",
        label="Font Size",
        options=["Small", "Medium", "Large"],
        default="Medium",
    ),
    TextItem(
        key="username",
        label="Username",
        default="Guest",
    ),
    TextItem(
        key="api_key",
        label="API Key",
        password=True,
    ),
    CheckboxItem(
        key="notifications",
        label="Enable Notifications",
        description="Show desktop notifications",
        default=True,
    ),
]

dialog = SettingsDialog(title="Settings", items=items)
result = await session.show_dialog(dialog)

if result:
    # result is a dict of changed values only
    for key, value in result.items():
        print(f"{key}: {value}")
```

**Control Types:**
| Control | Description | Navigation |
|---------|-------------|------------|
| `DropdownItem` | Expandable dropdown list with `▼` indicator | Enter to open, Up/Down to select, Enter to confirm |
| `InlineSelectItem` | Inline cycling with `◀`/`▶` indicators | Left/Right to cycle through options |
| `TextItem` | Text input (optional password masking) | Enter to edit, Enter/Escape to confirm/cancel |
| `CheckboxItem` | Boolean toggle (`true`/`false`) | Space/Enter/Left/Right to toggle |

**Navigation:** Up/Down moves between controls, Tab cycles through controls and buttons, Ctrl+S saves.

**Fixed dialog height:** Pass `height=N` to `show_settings_dialog()` (or set `height` on a `BaseDialog`/`SettingsDialog` subclass) to allocate the full dialog area in one render frame instead of growing line-by-line. Body content that exceeds the available rows scrolls within the dialog. The value is clamped to the terminal size; if the terminal is too small for the minimum dialog (12 rows), the dialog returns its escape result without opening.

```python
result = await session.show_settings_dialog(
    title="Settings",
    items=items,
    height=15,
)
```

### AppInfo Configuration

```python
app_info = AppInfo(
    name="MyApp",
    version="1.0.0",
    welcome_message="Welcome to MyApp!",  # Optional custom welcome

    # Key bindings
    fullscreen_key="c-e",        # Ctrl+E for fullscreen
    expand_key="c-t",            # Ctrl+T for expand/collapse

    # Feature flags
    fullscreen_enabled=False,    # Enable fullscreen mode
    echo_thinking=True,          # Echo thinking to console after completion

    # Thinking animation
    thinking_text="Thinking",    # Text in header
    thinking_animation=("⠋", "⠙", "⠹", ...),  # Animation frames
    thinking_animation_position="before",      # "before" or "after" text
)
```

## Theming

Four built-in themes, selectable by name:

```python
session = ThinkingPromptSession(theme="light")   # or "dark", "mono", "terminal", "auto"
```

- `dark` — the default (unchanged from previous versions)
- `light` — palette tuned for light terminal backgrounds
- `mono` — attributes only (bold/italic/reverse), rendered without color
- `terminal` — named ANSI colors that inherit your terminal's own palette
- `auto` — picks mono under `NO_COLOR`, light/dark from `COLORFGBG` when
  available, otherwise `terminal`

Custom themes are `ThinkingPromptStyles` instances (`theme=` accepts them
too). All element styles derive from the `color_*` tokens, so overriding
tokens restyles the whole UI consistently.

Switch at runtime:

```python
session.set_theme("light")                # live UI re-themes on next paint
session.set_theme("light", repaint=True)  # also clears and re-prints the transcript
```

With `repaint=True`, markdown and code blocks re-render from source in the
new theme; output from `add_rich()` and raw ANSI keeps its original colors.

`NO_COLOR` (non-empty, checked at startup — see no-color.org) forces
colorless rendering regardless of theme, while keeping bold/italic.

Bound history growth for long sessions:

```python
session = ThinkingPromptSession(history_limit=1000)  # max transcript entries
```

## Examples

See the `examples/` directory for complete demos:

- `basic.py` - Simple thinking box usage
- `demo.py` - Interactive demo with simulated AI thinking
- `streaming.py` - Character-by-character streaming
- `chat_demo.py` - Chat-style conversation loop
- `clear_demo.py` - Clearing the screen and history with `session.clear()`
- `progress_demo.py` - Progress bar with callback
- `demo_progress_line.py` - In-place progress updates
- `demo_multi_box.py` - Multiple concurrent thinking boxes with task list
- `demo_messages_during_thinking.py` - Output messages during thinking
- `demo_animated_separator.py` - Different animation configurations
- `demo_task_progress.py` - Rich-styled task progress with in-place status updates
- `dialog_test.py` - Dialog system demo (yes/no, message, choice, dropdown)
- `settings_dialog_demo.py` - Settings dialog with all control types
- `demo_showcase.py` - Feature showcase for demos and screenshots
- `completer_demo.py` - Slash-command autocompletion (like Claude Code)

## License

MIT
