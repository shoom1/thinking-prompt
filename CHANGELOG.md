# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
