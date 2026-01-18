# Unreleased Changes

<!--
Add your changes here using Keep a Changelog format.
Run `git log --oneline <last-tag>..HEAD` to see commits for reference.
-->

### Added
- `CompactSelect` widget - compact single-line dropdown that cycles with left/right keys
- `CompactCheckbox` widget - compact single-line checkbox `[x]`/`[ ]` toggle
- Dialog width control: `width` parameter on BaseDialog and SettingsDialog
  - `None` or `0`: auto-size to content
  - positive int: minimum width (default 60 for SettingsDialog)
  - `-1`: maximum width (stretch to fill)

### Changed
- Dialog background now uses dark theme (`bg:#2a2a2a`) to match terminal
- DropdownItem now renders as compact `[value ▼]` instead of full RadioList
- CheckboxItem now renders as compact `[x]`/`[ ]` instead of CheckboxList
- SettingsDialog navigation: Up/Down moves between rows, Left/Right changes values
- Removed light background overlay from dialogs (`with_background=False`)

### Fixed
- Dialog styling now consistent with dark terminal themes

### Removed
-
