"""Tests for theme tokens, factories, and resolution."""
from __future__ import annotations

from thinking_prompt.styles import ThinkingPromptStyles


class TestTokenCompletion:
    """Every formerly-hardcoded element default must be token-derived,
    with byte-identical dark values (backward-compat guarantee)."""

    def test_dark_defaults_byte_identical(self):
        s = ThinkingPromptStyles()
        assert s.thinking_box == "fg:#a0a0a0 italic"
        assert s.thinking_message == "fg:#a0a0a0 italic"
        assert s.thinking_box_border == "fg:#606060"
        assert s.thinking_box_hint == "fg:#707070 italic"
        assert s.status_bar == "bg:#202040 fg:#808090"
        assert s.input_separator == "fg:#444444"
        assert s.dialog_shadow == "bg:#000000"
        assert s.dialog_button == "bg:#404040 fg:#e0e0e0"
        assert s.menu_item_selected == "fg:#88c0d0 bg:#454545 noreverse"
        assert s.menu_meta_selected == "fg:#88c0d0 bg:#454545 noreverse"

    def test_new_tokens_drive_derivation(self):
        s = ThinkingPromptStyles(
            color_thinking="#123456",
            color_bg_status="#111111",
            color_text_status="#222222",
        )
        assert s.thinking_box == "fg:#123456 italic"
        assert s.thinking_message == "fg:#123456 italic"
        assert s.status_bar == "bg:#111111 fg:#222222"

    def test_empty_tokens_yield_attribute_only_styles(self):
        s = ThinkingPromptStyles(color_thinking="", color_error="")
        assert s.thinking_box == "italic"
        assert s.error_message == "bold"

    def test_explicit_element_override_wins(self):
        s = ThinkingPromptStyles(thinking_box="fg:red")
        assert s.thinking_box == "fg:red"

    def test_new_fields_defaults(self):
        s = ThinkingPromptStyles()
        assert s.color_depth is None
        assert s.markdown_code_theme == "monokai"
