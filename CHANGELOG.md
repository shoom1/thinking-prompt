# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
