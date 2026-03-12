# Unreleased Changes

<!--
Add your changes here using Keep a Changelog format.
Run `git log --oneline <last-tag>..HEAD` to see commits for reference.
-->

### Added
- Multiple thinking boxes: `start_thinking()` can be called multiple times to create independent boxes
- `ThinkingContext.finish()` method for finishing individual boxes
- Box ordering via `order` parameter (higher = closer to prompt)
- Per-box `max_lines` configuration
- `ThinkingHeader` class (renamed from `ThinkingSeparator`)
- Multi-box example: `examples/demo_multi_box.py`

### Changed
- `start_thinking()` now accepts optional `order` and `max_lines` parameters
- `thinking()` context manager now accepts `order` and `max_lines` parameters
- `finish_thinking()` finishes all active boxes (backward compatible)
- `is_thinking` returns True if any box is active
- Ctrl+T expands/collapses all boxes together

### Fixed
-

### Removed
-
