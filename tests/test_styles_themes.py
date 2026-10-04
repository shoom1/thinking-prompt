"""Tests for theme tokens, factories, and resolution."""
from __future__ import annotations

from thinking_prompt.styles import ThinkingPromptStyles


class TestTokenCompletion:
    """Every formerly-hardcoded element default must be token-derived,
    with byte-identical dark values (backward-compat guarantee). Derived
    styles are resolved when the Style is built, so read them from
    to_style_dict() — the fields themselves hold only explicit overrides."""

    def test_dark_defaults_byte_identical(self):
        d = ThinkingPromptStyles().to_style_dict()
        assert d["thinking-box"] == "fg:#a0a0a0 italic"
        assert d["history.thinking"] == "fg:#a0a0a0 italic"
        assert d["thinking-box.border"] == "fg:#606060"
        assert d["thinking-box.hint"] == "fg:#707070 italic"
        assert d["status"] == "bg:#202040 fg:#808090"
        assert d["input-separator"] == "fg:#444444"
        assert d["dialog shadow"] == "bg:#000000"
        assert d["button"] == "bg:#404040 fg:#e0e0e0"
        assert d["completion-menu.completion.current"] == "fg:#88c0d0 bg:#454545 noreverse"
        assert d["completion-menu.meta.completion.current"] == "fg:#88c0d0 bg:#454545 noreverse"

    def test_new_tokens_drive_derivation(self):
        d = ThinkingPromptStyles(
            color_thinking="#123456",
            color_bg_status="#111111",
            color_text_status="#222222",
        ).to_style_dict()
        assert d["thinking-box"] == "fg:#123456 italic"
        assert d["history.thinking"] == "fg:#123456 italic"
        assert d["status"] == "bg:#111111 fg:#222222"

    def test_empty_tokens_yield_attribute_only_styles(self):
        d = ThinkingPromptStyles(color_thinking="", color_error="").to_style_dict()
        assert d["thinking-box"] == "italic"
        assert d["history.error"] == "bold"

    def test_explicit_element_override_wins(self):
        s = ThinkingPromptStyles(thinking_box="fg:red")
        assert s.thinking_box == "fg:red"
        assert s.to_style_dict()["thinking-box"] == "fg:red"

    def test_new_fields_defaults(self):
        s = ThinkingPromptStyles()
        assert s.color_depth is None
        assert s.code_theme == "monokai"



def _rules(s: ThinkingPromptStyles) -> dict[str, str]:
    """The style rules prompt_toolkit actually receives, by class name."""
    return dict(s.to_style().style_rules)


class TestTokensResolveAtRender:
    """Element styles derive from the color tokens when the Style is built,
    not once at construction — so replace() and mutation restyle everything
    that isn't explicitly overridden."""

    def test_replace_token_restyles_derived_elements(self):
        import dataclasses

        s = dataclasses.replace(ThinkingPromptStyles.light(), color_error="#ff00ff")
        assert _rules(s)["history.error"] == "fg:#ff00ff bold"

    def test_mutating_token_restyles_derived_elements(self):
        s = ThinkingPromptStyles.light()
        s.color_accent = "#123456"
        assert _rules(s)["setting-indicator"] == "fg:#123456"

    def test_explicit_override_survives_replace(self):
        import dataclasses

        s = dataclasses.replace(
            ThinkingPromptStyles(thinking_box="fg:red"), color_thinking="#000000"
        )
        assert _rules(s)["thinking-box"] == "fg:red"
        assert _rules(s)["history.thinking"] == "fg:#000000 italic"

    def test_to_style_dict_matches_to_style(self):
        s = ThinkingPromptStyles.light()
        assert s.to_style_dict() == _rules(s)


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
        d = ThinkingPromptStyles.mono().to_style_dict()
        pairs = [
            (d["completion-menu.completion"], d["completion-menu.completion.current"]),
            (d["completion-menu.meta.completion"], d["completion-menu.meta.completion.current"]),
            (d["button"], d["button.focused"]),
            (d["setting-label"], d["setting-label-selected"]),
            (d["setting-value"], d["setting-value-selected"]),
            (d["setting-desc"], d["setting-desc-selected"]),
            (d["radio-list"], d["radio-selected"]),
            (d["checkbox-list"], d["checkbox-selected"]),
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
        assert ThinkingPromptStyles.light().code_theme == "default"


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
        assert resolve_theme("auto").code_theme == "default"

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


class TestStyleClassesDefined:
    def test_every_class_the_package_uses_is_themed(self):
        """A widget styled with a class the theme doesn't define silently
        ignores the theme (the settings text field used an undefined
        class:setting-input). Scans string literals, not docstrings."""
        import ast
        import pathlib
        import re

        import thinking_prompt

        used: set[str] = set()
        for path in pathlib.Path(thinking_prompt.__file__).parent.glob("*.py"):
            tree = ast.parse(path.read_text())
            docstrings = {
                id(n.value) for n in ast.walk(tree)
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
            }
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings):
                    used.update(re.findall(r"class:([A-Za-z0-9_.-]+)", node.value))

        assert used, "scan found no style classes — scanner broken?"
        assert used - set(ThinkingPromptStyles().to_style_dict()) == set()

    def test_every_themed_class_is_used(self):
        """The reverse: a style field whose class nothing draws with is a
        setting that silently does nothing (assistant_prefix, select_value,
        checkbox_mark and user_separator were, until 0.4). Classes count as
        used when this package or prompt_toolkit's widgets name them, or
        name a dotted child (class:a.b.c also carries a and a.b)."""
        import pathlib
        import re

        import prompt_toolkit

        import thinking_prompt

        used: set[str] = set()
        for package in (thinking_prompt, prompt_toolkit):
            for path in pathlib.Path(package.__file__).parent.rglob("*.py"):
                for name in re.findall(r"class:([A-Za-z0-9_.-]+)", path.read_text()):
                    parts = name.split(".")
                    used.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))

        unused = {
            selector
            for selector in ThinkingPromptStyles().to_style_dict()
            if any(cls not in used for cls in selector.split())
        }
        assert unused == set()


class TestRemovedStyleFields:
    """0.4 removes style fields no component drew with (no deprecation)."""

    @pytest.mark.parametrize(
        "name", ["assistant_prefix", "select_value", "checkbox_mark", "user_separator"]
    )
    def test_field_is_gone(self, name):
        with pytest.raises(TypeError, match=name):
            ThinkingPromptStyles(**{name: "bold"})
