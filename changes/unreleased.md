# Unreleased Changes

<!--
Add your changes here using Keep a Changelog format.
Run `git log --oneline <last-tag>..HEAD` to see commits for reference.
-->

### Added
- `SettingsListControl` - clean settings list with focus indicator and right-aligned values
- `description` field on SettingsItem for optional help text below labels
- `CompactSelect` widget - compact single-line dropdown that cycles with left/right keys
- `CompactCheckbox` widget - compact single-line checkbox `[x]`/`[ ]` toggle
- Dialog width control: `width` parameter on BaseDialog and SettingsDialog
- Dialog vertical positioning: `top` parameter on BaseDialog and SettingsDialog
- Settings list styles: indicator, label, value, description with selected states
- Vim-style keybindings (j/k/h/l) for settings navigation

### Changed
- SettingsDialog now uses clean list with `›` focus indicator and right-aligned values
- Dialog background now uses dark theme (`bg:#2a2a2a`) to match terminal
- Checkbox values display as `true`/`false` text with green/grey styling
- SettingsDialog navigation: Up/Down (j/k) moves rows, Left/Right (h/l) changes values
- Removed light background overlay from dialogs (`with_background=False`)

### Fixed
- Dialog styling now consistent with dark terminal themes

### Removed
-
