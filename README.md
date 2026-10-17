# thinking-prompt

A prompt_toolkit extension that adds a "thinking box" above the prompt for displaying AI thinking/processing content with real-time streaming updates.

![Demo](img/demo.gif)

## Features

- **Thinking Box**: A collapsible area above the prompt that shows processing/thinking content
- **Multiple Thinking Boxes**: Run multiple independent boxes concurrently with ordering and per-box lifecycle control
- **Real-time Streaming**: Content updates in real-time as your callback returns new content
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
        async with session.thinking() as box:
            box.append("Processing...\n")
            await asyncio.sleep(0.5)
            box.append("Done!\n")

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

> **Note — handler errors.** An exception in a handler is shown as
> `[ERROR] Handler error: KeyError: 'x'` and logged, with its traceback,
> to the `thinking_prompt` logger. The library adds no log output of its
> own; configure logging to see tracebacks — to a file, since stderr
> would draw over the UI:
> `logging.basicConfig(filename="app.log", level=logging.ERROR)`.

## Key Bindings

| Key | Action |
|-----|--------|
| Ctrl+T | Expand/collapse all thinking boxes (while one is open) |
| Ctrl+C | Cancel current operation or exit |
| Ctrl+D | Exit application (empty input line only) |

Rebind Ctrl+T with `expand_key=` (see [Session Options](#session-options)).

## API Reference

### ThinkingPromptSession

The main class for creating a thinking-enabled prompt session.

```python
session = ThinkingPromptSession(
    message=">>> ",              # Prompt message
    app_info=AppInfo(...),       # Startup banner (none without it)
    max_thinking_height=15,      # Max lines when collapsed
    enable_status_bar=True,      # Show status bar
    echo_input=True,             # Echo user input to console
    complete_while_typing=True,  # Show completions as you type
    completions_menu_height=6,   # Max rows in completions popup
)
```

Every argument after `message` is keyword-only. Keys and the thinking
header are under [Session Options](#session-options).

### Thinking API

**Context Manager (recommended):**
```python
async with session.thinking(title="Processing") as box:
    box.append("Step 1...\n")
    await asyncio.sleep(0.5)
    box.append("Step 2...\n")
# Automatically finishes when exiting context
```

**Manual control:**
```python
box = session.start_thinking(title="Processing")
box.append("Processing...\n")
await asyncio.sleep(0.5)

# Finish this specific box and optionally echo to console
box.finish(add_to_history=True, echo_to_console=True)
```

To show text you already hold, pass a content callback instead. The box
re-reads it while it's drawn (every 0.1 s). You can read such a box
(`box.text` is what it shows), but writing to it raises `TypeError`:

```python
status = {"line": "starting"}
box = session.start_thinking(lambda: status["line"], title="Watching")
status["line"] = "step 2"   # shown at the next poll
box.finish()
```

### When a Box Ends

A box's content is kept however it ends, echoed to the console and history
as on a normal finish:

- **Cancelled** (Ctrl+C, or the task running a `thinking()` block is
  cancelled): the content, then one `Operation cancelled...` line after all
  the boxes that the cancel ended.
- **The handler raises**: the content, then the `[ERROR] Handler error: ...` line.
- **Left open** by a handler that returns: finished as `box.finish()` would.

A box belongs to the task that opened it. When a handler ends, the session
finishes the boxes it opened (and any whose task has already ended); a box
opened by a background task stays until that task finishes it. Ctrl+C at
an idle prompt clears every remaining box.

`box.is_finished` tells whether a box is done. Calling `finish()` again
returns the same text without echoing it twice. Writes to a finished box are
dropped, so `box.text` stays what `finish()` returned; the first one logs a
warning to the `thinking_prompt` logger.

Ctrl+T expands or collapses all open boxes together, and boxes start
collapsed again once the last one finishes.

### Redraws

The screen is redrawn only when something changes, never on a timer, so an
idle prompt costs no CPU:

- Writes to a box (`append`, `set_line`, `set_title`, ...)
  redraw right away, from any thread; fast streams are capped at 30
  redraws a second.
- A spinner redraws at each frame (10 a second for the default) while its
  box is shown; `ThinkingPromptSession(spinner=None)` turns the spinner off.
- Text that can't say when it changes is re-read every 0.1 s while it's
  shown: a content callback passed to `start_thinking()`, and a prompt
  `message` or `status_text` given as a callable.
- When the terminal gets narrower or shorter, the session repaints once
  the size holds for 0.25 s: it clears the screen and scrollback and prints
  the transcript again, as `set_theme(repaint=True)` does. A narrower
  window re-wraps the UI's full-width rows and a shorter one pushes its top
  into scrollback, so the old frame can't be erased row by row. Shell
  output from before the session, anything printed outside it (plain
  `print()`) and entries `history_limit` dropped don't come back.

### Long Content

A collapsed box shows at most `max_lines` rows (at least 1; session
default: `max_thinking_height`, at least 2). When content overflows, the
box keeps the **newest** lines under a `+N earlier lines... ctrl-t to
expand` hint, so a stream stays visibly live; a one-row box has no room
for the hint and shows just the newest line. Ctrl+T expands the box to fit its content, up to
the space the terminal has. When the box finishes, the console echo keeps
the same end the box showed.

For content whose first lines matter most — a task list, a plan — keep the
head instead:

```python
tasks = session.start_thinking(title="Tasks", max_lines=10, overflow="head")
# or: async with session.thinking(overflow="head") as box: ...
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
async with session.thinking(title="Processing") as box:
    box.append_rich("[dim]  ○ Load data[/dim]\n")
    box.append_rich("[dim]  ○ Transform[/dim]\n")

    box.set_line_rich(0, "[bold cyan]  ⟳ Load data…[/bold cyan]")
    box.set_title("Loading")
    await asyncio.sleep(1)
    box.set_line_rich(0, "[green]  ✓ Load data[/green]")

    box.set_line_rich(1, "[bold cyan]  ⟳ Transform…[/bold cyan]")
    box.set_title("Transforming")
    await asyncio.sleep(1)
    box.set_line_rich(1, "[green]  ✓ Transform[/green]")
```

### Dynamic Titles & In-Place Updates

Use `set_title()` to change the thinking header and `set_line()` to update lines in place:

```python
async with session.thinking(title="Downloading") as box:
    box.append("Progress: 0%\n")
    for i in range(1, 101):
        box.set_line(-1, f"Progress: {i}%")
        box.set_title(f"Downloading {i}%")
        await asyncio.sleep(0.02)
```

`set_line()` and `set_line_rich()` replace one line, so their text must be one
line: a newline in it, or markup that renders to several lines (a `Panel`, a
`Table`), raises `ValueError`. Indices past the end add empty lines up to it.
Lines are numbered as `len(box)` counts them, so `-1` is the last line, and a
trailing newline ends a line rather than starting one. A negative index on an
empty box raises `IndexError`.

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

Dialogs open over a running session: call them from an input handler, or
from a task started while `run()`/`run_async()` is running. On a session
that isn't running they raise `RuntimeError`. If the session exits while a
dialog is open, awaiting it raises `asyncio.CancelledError`.

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
from thinking_prompt import Dialog, ButtonConfig
result = await session.show_dialog(Dialog(
    title="Custom",
    body="Choose an option:",
    buttons=[
        ButtonConfig("Option A", result="a"),
        ButtonConfig("Option B", result="b"),
    ],
))
```

A button either returns a fixed `result` or runs a `handler`, which decides
what happens: `set_result(...)` or `cancel()` closes the dialog, doing
nothing keeps it open (e.g. while input is invalid). For a form, give the
dialog `fields` and read what they hold with `dialog.values`; for other
content, pass any prompt_toolkit container as `body`, or subclass `Dialog`
and override `build_body()` / `get_buttons()`:

```python
from thinking_prompt import ButtonConfig, Dialog, TextField

class LoginDialog(Dialog):
    title = "Login"
    fields = [TextField("user", "Username")]

    def get_buttons(self):
        return [
            ButtonConfig("Login", handler=self.login),
            ButtonConfig("Cancel", handler=self.cancel),
        ]

    def login(self):
        if self.values["user"]:  # stays open while empty
            self.set_result(self.values["user"])

name = await session.show_dialog(LoginDialog())
```

Escape closes any dialog and returns `None` (or the dialog's
`escape_result`). To require a button press instead, pass
`escapable=False` to `Dialog(...)`, or set `escapable = False` on a
subclass.

A `Dialog` has no buttons unless you give it some, and it needs something
to take keyboard focus: at least one button, fields, or a focusable body (e.g. a
`TextArea`, closed with Escape). Otherwise `show_dialog()` raises
`ValueError`. Other options: `escape_result`, `escapable`, `width` (box
only; never narrower than the buttons), `max_height`, `fields`, `align_values`.

**Where a box sits.** Under the prompt, above the status bar: where an inline
dialog would be. When the rest of the screen takes rows (a thinking box, a
longer prompt), the box shares them as an inline dialog does: it takes the
rows it gets and scrolls the rest. Only when those are fewer than its title, one row and its buttons
need is it centered over the screen.

**Long content scrolls.** A dialog is never taller than the terminal (less
the prompt's rows), nor than `max_height` rows if you pass it — counting the
whole dialog: title, borders, buttons, hint. What doesn't fit scrolls: rows
with a cursor (fields, lists, actions) follow the cursor, and a text body
scrolls with PgUp/PgDn (and ↑↓ in a box). Every helper takes `max_height=`.

**Small terminals.** A box dialog that can't fit the terminal at all
(narrower than its buttons, or shorter than its frame, buttons and one body
row) shows a short notice in its place, with the size it needs. Keys still
reach the hidden dialog: Esc cancels it and Enter presses its focused button. It comes back as soon as the
terminal is big enough.

**Upgrading from 0.3:** `DialogConfig` and `BaseDialog` were removed.

| 0.3 | 0.4 |
|---|---|
| `DialogConfig(title, body, buttons, ...)` | `Dialog(title, body, buttons, ...)` |
| `class MyDialog(BaseDialog)` | `class MyDialog(Dialog)` |
| `get_buttons()` returning `("OK", handler)` | `ButtonConfig("OK", handler=handler)` |
| `escape_result = _UNSET` | `escapable = False` |
| `BaseDialog` subclass relying on its default OK button | `buttons = (ButtonConfig("OK"),)` |
| `Dialog(height=N)` | `max_height=N`: the dialog sizes to its content, up to N rows |
| `top` on a dialog subclass | Drop it: a box sits under the prompt, where an inline dialog would (a subclass's `top` attribute is ignored) |
| `SettingsDialog(title, items, ...)`, `show_settings_dialog(title, items, ...)` | `Dialog(title, fields=items, buttons=..., width=60)`: see Form fields |
| `SettingsItem`, `InlineSelectItem`, `DropdownItem`, `CheckboxItem`, `TextItem` | `Field`, `SelectField`, `DropdownField`, `CheckboxField`, `TextField` (frozen; same attributes) |
| A settings dialog's changed-values result | Compare `dialog.values` with your config, or `config.update(values)` |
| `can_cancel=False` | One Done button and `escapable=False` |
| Ctrl+S in a settings dialog | Removed: Tab (or ↓ inline) to the Save button |

### Inline dialogs

Any dialog can also be drawn inline: rows under the prompt, above the status
bar, in the rows a box dialog would take, but laid out as plain rows instead of a bordered box. Its buttons become a numbered list:

```
 Delete 3 files?
 This can't be undone.

 ❯ 1. Delete
   2. Keep

 ↑↓ navigate · Enter select · Esc cancel
```

Choose per session, per dialog, or per call:

```python
from thinking_prompt import ButtonConfig, Dialog, ThinkingPromptSession

session = ThinkingPromptSession(dialog_placement="inline")   # default: "box"

ok = await session.yes_no_dialog("Delete?", "3 files", placement="box")   # this call only
buttons = [ButtonConfig("A", result="a"), ButtonConfig("B", result="b")]
await session.show_dialog(Dialog("Pick", "Which one?", buttons, placement="inline"))
```

One cursor walks every row: ↑↓ move (Tab / Shift+Tab too), Enter runs the
highlighted action, 1–9 run an action directly, Esc closes an escapable
dialog. Fields are edited in place: ←→ change a selector, Enter opens a
dropdown's menu, Space toggles a checkbox, Enter edits a text field.

Check, radio and choice lists show one option per line, in both styles:

```python
from thinking_prompt import ButtonConfig, ChecklistField, ChoiceField, Dialog, RadioField

tools = await session.checklist_dialog(
    "Tools", "Enable any:", ["search", "code", "files"], defaults=["search"],
)   # the checked options, or None if cancelled

await session.show_dialog(Dialog("Settings", fields=[
    ChecklistField("tools", "Tools", options=["search", "code"]),
    RadioField("mode", "Mode", options=["fast", "careful"], default="fast"),
    ChoiceField("theme", "Theme", options=["dark", "light"]),
], buttons=[ButtonConfig("Done")]))
```

A long text body scrolls with PgUp/PgDn, and the hint line says so while it
overflows; rows and actions scroll within 12 rows, following the cursor,
unless `max_height` says otherwise. `width` applies to box dialogs only.

Dialogs need a running session; to ask something before
`run_async()` starts or after it ends, use prompt_toolkit's own `choice()`
(prompt_toolkit 3.0.52 or later).

### Form fields

Any dialog can hold form fields, under its body. `dialog.values` holds what
they're set to, by key; a button handler returns it. A settings dialog is a
few lines:

```python
from thinking_prompt import (
    ButtonConfig, CheckboxField, Dialog, DropdownField, TextField,
)

dialog = Dialog(
    "Settings",
    fields=[
        DropdownField("model", "Model", options=["gpt-4", "o1"], default=config["model"]),
        CheckboxField("stream", "Stream responses", default=config["stream"]),
        TextField("name", "Name", description="Shown to others", default=config["name"]),
    ],
    buttons=[
        ButtonConfig("Save", handler=lambda: dialog.set_result(dialog.values)),
        ButtonConfig("Cancel"),
    ],
    width=60,
)
values = await session.show_dialog(dialog)   # every field's value, or None
if values is not None:
    config.update(values)
```

Fields are frozen, so a list of them can be a subclass's `fields` class
attribute; each dialog keeps its own values. Keys must be unique.

| Field | Shows | Keys |
|---|---|---|
| `DropdownField` | The value with `▼`; Enter opens a menu of the options under it, in a box and inline | Enter (or Space) to open, ↑↓ to choose, Enter to keep, Escape to put the old value back |
| `SelectField` | A `◀ value ▶` selector | ←→ (or Space) to step through the options |
| `TextField` | Text, edited in place (`password=True` shows dots) | Enter to edit, Enter/Escape to keep/drop the edit |
| `CheckboxField` | `true` / `false` | Space, Enter or ←→ to toggle |
| `ChecklistField` | One `[x]` option per line; value: the checked ones, in option order | ↑↓ between options, Space/Enter to toggle |
| `RadioField` | One `(•)` option per line; value: the picked one | ↑↓ between options, Space/Enter to pick |
| `ChoiceField` | A radio list drawn like prompt_toolkit's `choice()`: no marks, the pick in bold; value: the picked one | ↑↓ between options, Space/Enter to pick. As a dialog's only field (with nothing in the body taking focus), Enter also presses the first button, or with no buttons closes the dialog with the pick |

Every field takes `key`, `label`, `description` and `default`. A check,
radio or choice list with no label and no description shows just its options.

**Keys:** in a box, ↑↓ move a row at a time and Tab / Shift+Tab a field at a
time (Tab on to the buttons after the last field, Shift+Tab from the buttons
back to it; a radio or choice list is always entered at its picked option).
Inline, one cursor walks the rows and the actions.

**Aligning values:** values start two columns after the longest label or
description (`align_values="labels"`, the default), so descriptions don't run
under them; a description too long to leave room for the widest value still
does. Check, radio and choice lists, whose labels and descriptions sit on
rows of their own, don't count. `align_values="right"` puts values at the row's
right edge, and a number starts them at that column, cutting longer labels with
`…`.
When a row is short of width, its label is cut first (down to 3 columns), then
a dropdown or text field gives up its padding, and only then is the value
itself cut with `…`. A box with no `width` is as wide as its fields' rows.

### Session Options

```python
from thinking_prompt import Spinner, ThinkingPromptSession

session = ThinkingPromptSession(
    # Keys
    expand_key="c-t",            # Ctrl+T expands/collapses thinking boxes

    # Thinking boxes
    thinking_title="Thinking",   # Header title of boxes started without one
    spinner=Spinner.DOTS,        # Spinner.LINE, Spinner.ELLIPSIS, your own, or None
    spinner_position="before",   # "before" or "after" the title
    echo_thinking=True,          # Echo a finished box to the console
)
```

A `Spinner` is its frames and the seconds each is shown:
`Spinner(("◐", "◓", "◑", "◒"), interval=0.15)`. One frame makes a static mark.

**Upgrading from 0.3:** full screen (Ctrl+E with
`AppInfo(fullscreen_enabled=True)`) was removed: drop `fullscreen_enabled=`
and `fullscreen_key=`. `switch_to_fullscreen()`, `switch_to_prompt()` and
`is_fullscreen` are gone too. Ctrl+T shows thinking boxes in full, and the
terminal's own scrollback holds the transcript.

### AppInfo

The banner printed when the session starts:

```python
from thinking_prompt import AppInfo

app_info = AppInfo(
    name="MyApp",
    version="1.0.0",
    welcome_message="Welcome to MyApp!",  # Optional; replaces the name/version box
)
session = ThinkingPromptSession(app_info=app_info)
```

`welcome_message` can also be a callable returning a string or a Rich
renderable. Leave `app_info` out for no banner. An empty message (`""`, or a
callable returning `""` or `None`) prints nothing.

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
tokens restyles the whole UI consistently. Derivation happens at render
time, so tweaking a built-in theme works too:

```python
import dataclasses
from thinking_prompt import ThinkingPromptStyles

styles = dataclasses.replace(ThinkingPromptStyles.light(), color_accent="#c2410c")
session = ThinkingPromptSession(theme=styles)
```

Element fields you set explicitly (e.g. `error_message="fg:red"`) win over
the tokens; `styles.to_style_dict()` shows the resolved result.

Code highlighting — fenced code in markdown and `add_code()` alike —
follows the theme's `code_theme`: a Pygments style name (`"monokai"` in
dark, `"default"` in light), or `"ansi_dark"`/`"ansi_light"` to use the
terminal's own 16 colors (the `terminal` theme's choice).

Switch at runtime:

```python
session.set_theme("light")                # live UI re-themes on next paint
session.set_theme("light", repaint=True)  # also clears and re-prints the transcript
```

With `repaint=True`, markdown and code blocks re-render from source in the
new theme; output from `add_rich()` and raw ANSI keeps its original colors.

`NO_COLOR` (non-empty, checked at startup — see no-color.org) forces
colorless rendering regardless of theme, while keeping bold/italic.

**Upgrading from 0.3:** style settings that did nothing were removed.

| 0.3 | 0.4 |
|---|---|
| `ThinkingPromptSession(styles=s)` | `ThinkingPromptSession(theme=s)` |
| `SettingsDialog(..., styles=...)` | Removed with the settings dialog (see Form fields). |
| `setting_*` style fields (`setting_label`, `setting_value_true`, ...) | `field_*` (`field_label`, `field_value_true`, ...); the `setting-*` classes are `field-*` |
| `assistant_prefix`, `select_value`, `user_separator` | Removed: no component drew with them. |
| `checkbox_mark` (styled nothing) | Now styles the `[x]` / `(•)` marks of check and radio lists. |

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
- `settings_dialog_demo.py` - A settings dialog built from Dialog fields, box and inline
- `demo_showcase.py` - Feature showcase for demos and screenshots; dialogs start inline, `/inline` switches to boxes
- `demo.tape` - [VHS](https://github.com/charmbracelet/vhs) script that records the demo GIF above from `demo_showcase.py`: `vhs examples/demo.tape`
- `completer_demo.py` - Slash-command autocompletion (like Claude Code)
- `demo_themes.py` - Built-in themes and runtime theme switching
- `inline_dialogs.py` - Dialogs drawn inline under the prompt (and the same ones as boxes)

## License

MIT
