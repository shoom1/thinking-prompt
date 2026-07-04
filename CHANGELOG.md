# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.4] - 2026-07-04

### Fixed

- Input handlers that return without finishing their thinking boxes no longer leave the UI stuck with a permanently animating orphan box. `_run_handler` now finishes leftover boxes on normal completion — both async and sync handlers — matching the cleanup already performed on the cancellation and error paths. Leftover content is discarded, as on the Ctrl+C path.
- Ctrl+D now resolves a pending `prompt_async()` with the documented `EOFError` instead of leaving direct callers hanging forever, and only exits on an empty input line (readline semantics). With text in the buffer, prompt_toolkit's default emacs binding deletes the character under the cursor instead of discarding the draft and killing the session.
- Collapsed thinking-box height is computed against the real terminal width instead of a hardcoded 80 columns, so wrapped lines no longer clip content on narrow terminals or reserve excess height on wide ones.
- `examples/completer_demo.py` `/quit` now exits via `session.exit()`. The previous `raise KeyboardInterrupt` escaped the handler wrapper (`except Exception`), killed the input loop without exiting the app, and left a zombie UI.
- Docstrings no longer teach broken or deprecated code: the `ThinkingPromptSession` class, `on_input`, and `run_async` examples use the `thinking()` context manager instead of the deprecated `finish_thinking()`, and the `on_input` example no longer passes a nonexistent `header=` kwarg. README no longer claims `set_status()` parses Rich markup strings — pass `Text.from_markup(...)` instead. The package docstring's key-binding list notes the empty-line qualifier as well. README's key-bindings table carries the same qualifier, and its examples list now includes `chat_demo.py` and `clear_demo.py`.

### Changed

- Dependency floors corrected: `prompt_toolkit>=3.0.36` (the old `>=3.0.0` floor resolved but crashed at import — `ScrollablePane`, used by the dialog system, was added in 3.0.15), `pygments>=2.15.0` (ReDoS hardening), and `rich` capped `<16` (the markdown renderer subclasses `rich.markdown.Heading` internals; 13–15 are the tested majors). New standalone `pygments` extra for code highlighting without rich.
- CI: Python 3.13 added to the test matrix, plus a minimal job that runs the suite without optional extras so the rich/pygments fallback paths are actually exercised. Rich-dependent tests now skip cleanly when rich is absent.

## [0.3.3] - 2026-06-13

### Fixed

- First Ctrl+C at an idle prompt now exits the session. Previously the live pending-input future was treated as in-flight work: the binding cancelled it (killing the input loop) but never exited the app, leaving a zombie session that echoed typed input without delivering it; only a second Ctrl+C exited. Behavior change for apps driving `prompt_async()` directly with their own loop: Ctrl+C at an idle prompt now also calls `app.exit()` in addition to raising `KeyboardInterrupt`, so a caller that swallowed the exception to keep the session alive will now observe the application exiting.
- `DialogManager.show()` now raises `RuntimeError` when a dialog is already open instead of overwriting it — a second concurrent dialog used to orphan the first dialog's result future, hanging its awaiter forever.
- `show_settings_dialog(can_cancel=False)` no longer returns the string `"close"` when Escape is pressed (violating the documented `dict | None` contract). Escape is now disabled in that mode; the Done button is the only way out.
- Custom `AppInfo.expand_key` is now reflected in the thinking-box truncation hint. The hint previously always read `ctrl-t to expand` even when the actual binding was different.
- `StreamingContent.set_line()` with an out-of-range negative index now raises a clear `IndexError` naming the index the caller passed, and leaves content untouched.
- The deprecated `finish_thinking()` now truncates each box to its own `max_lines` instead of the session-wide `max_thinking_height`, matching `ThinkingContext.finish()`. (`ThinkingBoxManager.finish_all()` result tuples gained a fifth element, `max_collapsed_lines`.)
- `clear()` now clears the screen through `app.renderer.clear()` while the app is running. The previous raw `\033[2J\033[H` write bypassed the renderer and left its screen state stale, corrupting the next repaint.
- Thinking-box height estimation strips ANSI styling escapes before measuring line wrap, so heavily styled `content_format="ansi"` content no longer renders an oversized box.
- The thinking header separator is sized to the terminal width instead of a hardcoded 80 columns.

### Changed

- Importing `thinking_prompt` no longer monkey-patches `rich.markdown.Markdown` globally. The left-aligned heading style is applied through an internal `Markdown` subclass used only by this library's own markdown rendering; host applications' Rich output is unaffected.
- Rich/Pygments helpers moved from `display` to a new `rich_utils` module (`display` re-exports the old names for backward compatibility). The public `rich_to_ansi` export is unchanged.
- Removed dead `ThinkingBoxControl.get_key_bindings()` and `get_console_output()` — neither had a production caller; expand/collapse is owned by the session-level binding and console truncation by `Display.thinking()`.
- `DEFAULT_SPINNER_FRAMES` now lives in `types` as the single source of truth (still importable from `layout`); `AppInfo.thinking_animation` defaults to it.
- README and docstrings now state explicitly that sync input handlers block the event loop (frozen UI, no Ctrl+C) and recommend async handlers with `asyncio.to_thread` for blocking work.
- `examples/demo_showcase.py` now sources its displayed version from `thinking_prompt.__version__` instead of a hardcoded string, so the welcome banner can't drift from the package version.

## [0.3.2] - 2026-05-01

### Fixed

- Ctrl+C now cancels a running input handler instead of letting it run to completion. The handler is tracked as an `asyncio.Task` and cancelled on Ctrl+C, with active thinking boxes finished and pending input cancelled.
- Input submitted while a handler is running is no longer silently dropped. `accept_handler` now refuses to deliver input while busy, leaves the buffer intact, and surfaces a `Busy — press Ctrl+C to cancel` status hint.
- Handler exceptions no longer leave thinking boxes stuck in the active state — cleanup runs in the exception path so callers using `start_thinking()` are not left in a permanent "thinking" state.
- Ctrl+C with only an orphan thinking box (no running handler) now clears the box without also exiting the app. Previously the same keypress finished the boxes and then fell through to `app.exit()`.
- `_user_cancelled_handler` flag is now reset in `finally` so it can't stay sticky when a handler suppresses `CancelledError` or cancellation races with natural completion. Prevents a leftover `True` state from swallowing a later outer cancellation and stalling shutdown.
- `TextItem(password=True)` now masks input during editing, matching the masking already applied in view mode (previously the secret was visible while typing).
- `DialogConfig.width` is now actually applied to the rendered dialog (was a public field that `_ConfigBasedDialog` never copied to `BaseDialog.width`).
- `ButtonConfig.style` and `ButtonConfig.focused` are now honored — the configured style wraps each button's window style, and the configured focused button receives initial focus when the dialog opens.
- `_renderable_to_ansi` (and the public `rich_to_ansi`, `StreamingContent.append_rich`, `StreamingContent.set_line_rich`) now ignore `NO_COLOR=1`. These APIs explicitly produce ANSI for the thinking box; honoring `NO_COLOR` at the converter layer silently stripped styling and made tests environment-sensitive.

### Changed

- Demo password fields in `demo_showcase.py` and `settings_dialog_demo.py` now mask API-key values in display output so demos don't print secrets the user just typed.

## [0.3.1] - 2026-04-20

### Added

- Optional `BaseDialog.height` (and `height=` parameter on `SettingsDialog` / `show_settings_dialog()`) for one-shot dialog rendering — when set, the dialog allocates its full height in a single render frame instead of growing line-by-line, and body overflow scrolls within the pane. The value is clamped to `terminal_height - 4`; terminals too small for the minimum viable dialog (12 rows) short-circuit to the dialog's escape result.
- `ThinkingBoxManager.is_expanded` public property.
- CI workflow (`.github/workflows/ci.yml`) running ruff, mypy, and pytest on Python 3.9–3.12 for pushes and PRs to `main` and `develop`.

### Changed

- `SettingControl` is now `Generic[T]` over its concrete `SettingsItem` subclass, exposing subclass-only fields (`options`, `width`, `password`, `edit_width`) to the type checker without runtime casts.
- Public dialog APIs (`yes_no_dialog`, `choice_dialog`, `dropdown_dialog`, `show_settings_dialog`, `prompt_async`) now return precise types instead of leaking `Any`.
- `FormattedTextHistory` storage typed as `List[OneStyleAndTextTuple]`; `append_formatted` accepts any `Iterable`.
- `create_thinking_area` now requires a `ThinkingBoxManager` (the previous `Optional` default was unreachable).

### Fixed

- History rendering no longer shows literal ANSI escape codes (e.g. `^[[34m`) in fullscreen mode. `Display` output methods (`welcome`, `rich`, `markdown`, `code`, `add_rich`, `raw`) now parse ANSI into `FormattedText` fragments before storing in history, matching the console-print path.
- `create_history_window` cursor calculation unpacked 3-tuple fragments as 2-tuples (would crash on any fragment carrying a mouse handler); now handles both shapes and runs in O(N) instead of O(N·M).
- Codebase now passes strict mypy (was 61 errors) and ruff (was 131 errors) against its own declared rules.

### Chore

- Added `types-Pygments` to dev dependencies.
- `.ruff_cache` and `.mypy_cache` added to `.gitignore`; previously tracked `docs/plans` files untracked.

## [0.3.0] - 2026-04-16

### Added

- **Multiple thinking boxes** — `start_thinking()` can be called multiple times to create independent, concurrent boxes
- `ThinkingContext.finish()` method for finishing individual boxes (per-box lifecycle control)
- Box ordering via `order` parameter (higher values position closer to the prompt)
- Per-box `max_lines` configuration
- `ThinkingBoxManager` for managing collections of thinking boxes with thread-safe operations
- `ThinkingHeader` class (renamed from `ThinkingSeparator`) — exported from package
- `demo_multi_box.py` example showing concurrent thinking boxes with task list pattern

### Changed

- `start_thinking()` now returns a `ThinkingContext` with per-box `finish()`, `set_title()`, and content methods
- `start_thinking()` accepts optional `order` and `max_lines` parameters
- `thinking()` context manager accepts `order` and `max_lines` parameters
- `is_thinking` returns True if any box is active
- Ctrl+T expands/collapses all boxes together
- `/tasks` command in demo_showcase now uses multi-box pattern

### Deprecated

- `finish_thinking()` — use `ctx.finish()` on the `ThinkingContext` returned by `start_thinking()`, or use the `thinking()` async context manager

### Fixed

- Fullscreen exit now restores pre-fullscreen expansion state (boxes that were collapsed before entering fullscreen are collapsed again on exit)

## [0.2.5] - 2026-03-08

### Added

- `rich_to_ansi()` public API — convert Rich markup to ANSI strings for use with callback-based `start_thinking()` API
- Rich/ANSI formatted text support in thinking box via `append_rich()` and `set_line_rich()`
- `demo_task_progress.py` example with Rich-styled task progress and in-place status updates
- `/quit` and `/tasks` commands in demo_showcase
- `environment.yml` and `requirements.txt` for conda/pip environment setup

### Changed

- Deduplicated expand-hint and ANSI truncation logic
- `truncate_ansi_to_lines()` now delegates to `truncate_to_lines()` with ANSI reset suffix
- `thinking()` context manager reuses `ThinkingContext` from `start_thinking()` instead of creating a duplicate
- `finish_thinking()` uses return value of `finish()` instead of double-reading content
- `ThinkingContext.set_format` callback typed as `ContentFormat` instead of `str`
- Redundant `set_format("ansi")` calls guarded with idempotent `_ensure_ansi_format()`

### Fixed

- `_rich_to_ansi` now correctly respects terminal width for layout-aware renderables (Panel, Table)

### Docs

- Updated README with v0.2.3–v0.2.4 features: Rich/ANSI content, dynamic titles, `set_status()`, completions params

## [0.2.4] - 2026-02-09

### Added

- `set_status()` method on ThinkingPromptSession — set status bar text at runtime, accepts plain text, FormattedText, or Rich renderables
- `ThinkingContext` class — returned by `thinking()` context manager, combines content accumulation with separator title control
- `ThinkingContext.set_title()` — dynamically update the thinking box separator title during a thinking session
- `StreamingContent.set_line()` — in-place line editing with negative index support for progress bar updates
- `thinking()` and `start_thinking()` accept optional `title=` parameter
- `/thinking` slash command in demo_showcase.py demonstrating dynamic titles and line editing

## [0.2.3] - 2026-01-23

### Added

- `complete_while_typing` parameter for ThinkingPromptSession - shows completions automatically while typing
- `completions_menu_height` parameter for ThinkingPromptSession - controls dropdown menu height and reserved space (default: 5)
- Completion menu styles matching dark terminal theme (dark background, blue selection)
- `completer_demo.py` example showing slash-command autocompletion

### Changed

- Consolidated theme with base colors and shared menu styles
- Added configurable markdown styles with simplified theme
- Refactored SettingControl base class to extract shared methods (`_check_focus`, `_build_setting_row`)

### Fixed

- Completion menu theme now properly matches dark mode
- Suppress brief "Window too small" message on dialog open
- Inline select now stops at boundaries instead of wrapping

## [0.2.2] - 2026-01-21

### Added

- `DropdownItem`/`DropdownControl` - true dropdown with framed, scrollable list in edit mode
- `InlineSelectItem`/`InlineSelectControl` - inline select that cycles with Left/Right keys
- Arrow indicators: DropdownControl shows `▼`, InlineSelectControl shows `◀`/`▶` based on position
- Settings dialog demo in `demo_showcase.py` showcasing all control types
- `description` field on SettingsItem for optional help text below labels
- TextItem in-place editing: Enter to edit value in-place, Enter/Escape to confirm/cancel
- Dialog width control: `width` parameter on BaseDialog and SettingsDialog
- Dialog vertical positioning: `top` parameter on BaseDialog and SettingsDialog
- Settings list styles: indicator, label, value, description with selected states

### Changed

- SettingsDialog now uses clean list with `›` focus indicator and right-aligned values
- Dialog background now uses dark theme (`bg:#2a2a2a`) to match terminal
- Checkbox values display as `true`/`false` text with green/grey styling
- SettingsDialog navigation: Up/Down or Tab/Shift-Tab navigates all elements, Ctrl+S saves
- Removed light background overlay from dialogs (`with_background=False`)

### Fixed

- Dialog styling now consistent with dark terminal themes

## [0.2.1] - 2026-01-17

### Added

- **Settings Dialog** - Form-based dialog for configuring multiple settings:
  - `SettingsDialog` - Form dialog with vertical layout
  - `DropdownItem` - Select from list of options (RadioList)
  - `CheckboxItem` - Boolean toggle
  - `TextItem` - Text input with optional password masking
  - `session.show_settings_dialog(title, items)` - Convenience method
- New exports: `SettingsItem`, `DropdownItem`, `CheckboxItem`, `TextItem`, `SettingsDialog`
- `examples/settings_dialog_demo.py` - Settings dialog demo

## [0.2.0] - 2025-01-15

### Added

- **Dialog system** - Modal dialogs that integrate with the prompt session:
  - `yes_no_dialog(title, text)` - Yes/No confirmation dialog
  - `message_dialog(title, text)` - Simple message with OK button
  - `choice_dialog(title, text, choices)` - Multiple button choices
  - `dropdown_dialog(title, text, options)` - Radio list selection
  - `show_dialog(config)` - Custom dialogs via `DialogConfig` or `BaseDialog`
- New exports: `DialogConfig`, `ButtonConfig`, `BaseDialog`
- `examples/dialog_test.py` - Comprehensive dialog system demo
- Dialog commands in `demo_showcase.py` (confirm, info, action, theme)

### Changed

- Simplified `Display` class internals (refactored for maintainability)
- Smaller welcome message in demo_showcase (reduced padding)

## [0.1.1] - 2025-01-10

### Added

- `ThinkingPromptSession.add_rich()` - Print Rich renderables (Panel, Table, Text, Tree, etc.) to console and history
- `Display.rich()` - Underlying method for rendering Rich objects
- `ThinkingPromptSession.clear()` - Clear terminal screen, history buffer, and re-print welcome message
- `examples/clear_demo.py` - Example demonstrating the clear functionality

### Changed

- `Display.clear()` now clears both terminal screen (via ANSI escape codes) and history buffer
- `Display.welcome()` now delegates to `Display.rich()` for Rich renderables (internal refactor)

### Removed

- `ThinkingPromptSession.clear_history()` - Replaced by `clear()` with improved semantics

### Migration Guide

If you were using `clear_history()`:

```python
# Before (0.1.0)
session.clear_history()  # Cleared history and switched to fullscreen

# After (0.1.1)
session.clear()  # Clears terminal + history, re-prints welcome, stays in prompt mode
```

## [0.1.0] - 2025-01-09

### Added

- Initial release
- `ThinkingPromptSession` - Main class for chat-like prompt interface with thinking box
- `AppInfo` - Configuration for app name, version, welcome message, and animations
- `ThinkingPromptStyles` - Customizable styles for the interface
- Thinking box with expand/collapse functionality
- Optional fullscreen mode with chat history
- Streaming content support via `StreamingContent` class
- Context manager API: `async with session.thinking() as content`
- Output methods: `add_response()`, `add_message()`, `add_error()`, `add_warning()`, `add_success()`, `add_code()`
- Rich markdown rendering support
- Pygments syntax highlighting support
- 9 example scripts demonstrating various features
