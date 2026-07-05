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


import pytest

from prompt_toolkit.output import ColorDepth

from thinking_prompt.styles import THEMES, resolve_theme


def _all_style_values(s: ThinkingPromptStyles) -> list[str]:
    return [v for v in s.to_style().style_rules for v in [v[1]]]


class TestThemeFactories:
    def test_dark_equals_default(self):
        assert ThinkingPromptStyles.dark() == ThinkingPromptStyles()

    def test_factories_return_fresh_instances(self):
        a = ThinkingPromptStyles.light()
        b = ThinkingPromptStyles.light()
        assert a is not b
        a.thinking_box = "fg:red"
        assert b.thinking_box != "fg:red"

    def test_mono_has_no_colors_and_1bit_depth(self):
        s = ThinkingPromptStyles.mono()
        joined = " ".join(_all_style_values(s))
        assert "#" not in joined
        assert "ansi" not in joined
        assert s.color_depth is ColorDepth.DEPTH_1_BIT

    def test_mono_selection_states_distinguishable(self):
        """Every selected/focused style must differ from its unselected
        counterpart in mono, or selection is invisible without color."""
        s = ThinkingPromptStyles.mono()
        pairs = [
            (s.menu_item, s.menu_item_selected),
            (s.menu_meta, s.menu_meta_selected),
            (s.dialog_button, s.dialog_button_focused),
            (s.setting_label, s.setting_label_selected),
            (s.setting_value, s.setting_value_selected),
            (s.setting_desc, s.setting_desc_selected),
            (s.radio_list, s.radio_selected),
            (s.checkbox_list, s.checkbox_selected),
        ]
        for unselected, selected in pairs:
            assert selected, "selected state must not be empty in mono"
            assert selected != unselected

    def test_terminal_uses_named_ansi_only(self):
        s = ThinkingPromptStyles.terminal()
        joined = " ".join(_all_style_values(s))
        assert "#" not in joined
        assert s.color_depth is None
        assert "ansicyan" in joined and "ansired" in joined

    def test_light_sets_light_code_theme(self):
        assert ThinkingPromptStyles.light().markdown_code_theme == "default"


class TestResolveTheme:
    def test_instance_passthrough(self):
        s = ThinkingPromptStyles.light()
        assert resolve_theme(s) is s

    def test_names(self):
        for name in ("dark", "light", "mono", "terminal"):
            assert isinstance(resolve_theme(name), ThinkingPromptStyles)

    def test_unknown_name_raises_with_valid_list(self):
        with pytest.raises(ValueError, match="mono"):
            resolve_theme("solarized")

    def test_auto_no_color_wins(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLORFGBG", "0;15")
        assert resolve_theme("auto").color_depth is ColorDepth.DEPTH_1_BIT

    def test_auto_colorfgbg_light(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORFGBG", "0;15")
        assert resolve_theme("auto").markdown_code_theme == "default"

    def test_auto_colorfgbg_dark(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORFGBG", "15;0")
        assert resolve_theme("auto") == ThinkingPromptStyles.dark()

    def test_auto_fallback_is_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("COLORFGBG", raising=False)
        s = resolve_theme("auto")
        assert "#" not in " ".join(_all_style_values(s))

    def test_auto_malformed_colorfgbg_is_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("COLORFGBG", "default;default")
        s = resolve_theme("auto")
        assert "#" not in " ".join(_all_style_values(s))

    def test_empty_no_color_does_not_trigger(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "")
        monkeypatch.delenv("COLORFGBG", raising=False)
        assert resolve_theme("auto").color_depth is None
