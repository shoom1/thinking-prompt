"""Tests for theme tokens, factories, and resolution."""
from __future__ import annotations

import dataclasses

from thinking_prompt.styles import ThinkingPromptStyles


class TestTokenCompletion:
    """Every formerly-hardcoded element default must be token-derived,
    with byte-identical dark values (the dark palette is 0.4's default
    look). Derived styles are resolved when the Style is built, so read
    them from to_style_dict() — the fields themselves hold only explicit
    overrides."""

    def test_dark_values_byte_identical(self):
        d = ThinkingPromptStyles.dark().to_style_dict()
        assert d["thinking-box"] == "fg:#a0a0a0 italic"
        assert d["transcript.thinking"] == "fg:#a0a0a0 italic"
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
        assert d["transcript.thinking"] == "fg:#123456 italic"
        assert d["status"] == "bg:#111111 fg:#222222"

    def test_empty_tokens_yield_attribute_only_styles(self):
        d = ThinkingPromptStyles(color_thinking="", color_error="").to_style_dict()
        assert d["thinking-box"] == "italic"
        assert d["transcript.error"] == "bold"

    def test_new_fields_defaults(self):
        s = ThinkingPromptStyles()
        assert s.color_depth is None
        assert s.code_theme == "ansi_dark"



def _rules(s: ThinkingPromptStyles) -> dict[str, str]:
    """The style rules prompt_toolkit actually receives, by class name."""
    return dict(s.to_style().style_rules)


class TestTokensResolveAtRender:
    """Element styles derive from the color tokens when the Style is built,
    not once at construction — so replace() and mutation restyle everything
    that isn't explicitly overridden."""

    def test_replace_token_restyles_derived_elements(self):
        s = dataclasses.replace(ThinkingPromptStyles.light(), color_error="#ff00ff")
        assert _rules(s)["transcript.error"] == "fg:#ff00ff bold"

    def test_mutating_token_restyles_derived_elements(self):
        s = ThinkingPromptStyles.light()
        s.color_accent = "#123456"
        assert _rules(s)["field-indicator"] == "fg:#123456"

    def test_explicit_override_survives_replace(self):
        s = dataclasses.replace(
            ThinkingPromptStyles(thinking_box="fg:red"), color_thinking="#000000"
        )
        assert _rules(s)["thinking-box"] == "fg:red"
        assert _rules(s)["transcript.thinking"] == "fg:#000000 italic"

    def test_to_style_dict_matches_to_style(self):
        s = ThinkingPromptStyles.light()
        assert s.to_style_dict() == _rules(s)


import pytest

from prompt_toolkit.output import ColorDepth

from thinking_prompt.styles import resolve_theme


def _all_style_values(s: ThinkingPromptStyles) -> list[str]:
    return [v for v in s.to_style().style_rules for v in [v[1]]]


class TestThemeFactories:
    def test_the_default_follows_the_terminal(self):
        """A bare ThinkingPromptStyles() is the default theme, terminal: the
        same as the session's when theme= isn't given."""
        assert ThinkingPromptStyles() == ThinkingPromptStyles.terminal()

    def test_dark_is_a_fixed_palette(self):
        s = ThinkingPromptStyles.dark()
        assert s.color_accent == "#88c0d0"
        assert s.code_theme == "monokai"
        # Selections show by background color, not the default's reverse.
        assert s.to_style_dict()["completion-menu.completion.current"] == "fg:#88c0d0 bg:#454545 noreverse"

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
            (d["field-label"], d["field-label-selected"]),
            (d["field-value"], d["field-value-selected"]),
            (d["field-desc"], d["field-desc-selected"]),
            (d["dialog-choice"], d["dialog-choice-selected"]),
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


# Class stacks as the session draws them: a box dialog's body, its title,
# its focused button, a text area in it, a scrollbar (its cells carry only
# the scrollbar's classes); the completion menu, with a FuzzyCompleter's
# match classes; a dropdown's option, in its framed menu.
_DRAWN = [
    "class:dialog class:dialog.body",
    "class:dialog class:frame.label",
    "class:dialog class:dialog.body class:button class:button.focused",
    "class:dialog class:dialog.body class:text-area",
    "class:scrollbar.background",
    "class:scrollbar.button",
    "class:completion-menu class:completion-menu.completion",
    "class:completion-menu class:completion-menu.completion.current",
    "class:completion-menu class:completion-menu.meta.completion",
    "class:completion-menu class:completion-menu.meta.completion.current",
    "class:completion-menu class:completion-menu.completion class:fuzzymatch.outside",
    "class:completion-menu class:completion-menu.completion.current class:fuzzymatch.outside",
    "class:field-dropdown-border class:field-dropdown class:field-dropdown-item",
]


def _drawn(theme: ThinkingPromptStyles, classes: str):  # type: ignore[no-untyped-def]
    """The attributes a cell with ``classes`` gets: prompt_toolkit's own
    default style under the theme's, as the Application merges them."""
    from prompt_toolkit.styles import default_ui_style, merge_styles

    return merge_styles([default_ui_style(), theme.to_style()]).get_attrs_for_style_str(classes)


class TestNoPromptToolkitColors:
    """prompt_toolkit's default style paints its widgets (a white dialog
    body, a red title, a gray completion menu); a theme without those
    colors (an empty token: the terminal's own) must not let them show."""

    @pytest.mark.parametrize("theme", ["terminal", "mono"])
    @pytest.mark.parametrize("classes", _DRAWN)
    def test_no_color_comes_from_prompt_toolkit(self, theme: str, classes: str):
        import re

        attrs = _drawn(resolve_theme(theme), classes)
        for color in (attrs.color, attrs.bgcolor):
            assert not re.fullmatch(r"[0-9a-f]{6}", color or ""), (classes, attrs)

    def test_a_focused_button_still_stands_out(self):
        attrs = _drawn(ThinkingPromptStyles(), _DRAWN[2])
        assert attrs.reverse and attrs.bold

    def test_the_current_completion_still_stands_out(self):
        attrs = _drawn(ThinkingPromptStyles(), _DRAWN[7])
        assert attrs.reverse

    def test_the_terminals_own_color_is_no_color(self):
        """An empty color, not "default": prompt_toolkit's legacy Windows
        console output draws "default" black (it keeps the console's own
        colors only for an empty one)."""
        for theme in ("terminal", "mono"):
            for classes in _DRAWN:
                attrs = _drawn(resolve_theme(theme), classes)
                assert "default" not in (attrs.color, attrs.bgcolor), (theme, classes)

    def test_a_fuzzy_completers_unmatched_letters_are_muted(self):
        """prompt_toolkit's #444444 was readable on its own gray menu, not
        on a dark terminal's background."""
        s = ThinkingPromptStyles()
        assert _drawn(s, _DRAWN[10]).color == s.color_text_muted

    def test_a_dropdowns_options_are_the_terminals_own_color(self):
        """Not the border's muted color, which the frame passes on."""
        assert _drawn(ThinkingPromptStyles(), _DRAWN[12]).color == ""

    def test_an_explicit_selection_isnt_reversed_by_prompt_toolkit(self):
        """prompt_toolkit's current completion is reverse video: a selection
        set by colors came out swapped, in the completion menu only."""
        s = ThinkingPromptStyles(menu_item_selected="bg:#222222 fg:ansiyellow")
        assert not _drawn(s, _DRAWN[7]).reverse

    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_themes_with_colors_keep_them(self, theme: str):
        s = resolve_theme(theme)
        body = _drawn(s, _DRAWN[0])
        assert body.bgcolor == s.color_bg_dialog.lstrip("#") and body.color == s.color_text.lstrip("#")


class TestSelectionStyles:
    """A selection (the current completion, a dropdown's pick, the focused
    button) derives from the tokens like every element: the accent on the
    selection's background color when the theme has one, else reverse
    video. A field set explicitly still wins."""

    def test_the_fields_hold_no_override_by_default(self):
        s = ThinkingPromptStyles()
        assert (s.menu_item_selected, s.menu_meta_selected, s.dialog_button_focused) == ("", "", "")

    def test_a_selection_background_token_colors_the_selection(self):
        d = ThinkingPromptStyles(color_accent="#ff6600", color_bg_selected="#222222").to_style_dict()
        for name in ("completion-menu.completion.current", "field-dropdown-selected"):
            words = d[name].split()
            assert "fg:#ff6600" in words and "bg:#222222" in words and "reverse" not in words

    @pytest.mark.parametrize("theme", ["dark", "light"])
    @pytest.mark.parametrize("part", ["button.text", "button.arrow"])
    def test_a_focused_buttons_label_and_arrows_are_in_its_colors(self, theme: str, part: str):
        """They carry the button class again, so the button rule painted
        over the focused one: the focused button looked like the others,
        but bold."""
        s = resolve_theme(theme)
        attrs = _drawn(s, f"class:dialog class:dialog.body class:button.focused class:{part}")
        assert attrs.bgcolor == s.color_accent_button.lstrip("#")
        assert attrs.color == "ffffff" and attrs.bold

    def test_a_button_token_colors_the_focused_button(self):
        words = ThinkingPromptStyles(color_accent_button="#0066cc").to_style_dict()["button.focused"].split()
        assert "bg:#0066cc" in words and "reverse" not in words

    @pytest.mark.parametrize("theme", ["terminal", "mono"])
    def test_without_them_selections_are_reverse_video(self, theme: str):
        d = resolve_theme(theme).to_style_dict()
        assert "reverse" in d["completion-menu.completion.current"].split()
        assert {"bold", "reverse"} <= set(d["button.focused"].split())

    def test_an_explicit_selection_style_wins(self):
        d = ThinkingPromptStyles(color_bg_selected="#222222", menu_item_selected="underline").to_style_dict()
        assert "underline" in d["completion-menu.completion.current"].split()
        assert "bg:#222222" not in d["completion-menu.completion.current"].split()


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

    def test_auto_is_not_a_theme(self):
        """The default follows the terminal, so there's nothing to pick."""
        with pytest.raises(ValueError, match="Valid themes: dark, light, mono, terminal$"):
            resolve_theme("auto")


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
            tree = ast.parse(path.read_text(encoding="utf-8"))
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
        setting that silently does nothing (assistant_prefix, select_value
        and user_separator were, until 0.4). Classes count as
        used when this package or prompt_toolkit's widgets name them, or
        name a dotted child (class:a.b.c also carries a and a.b)."""
        import pathlib
        import re

        import prompt_toolkit

        import thinking_prompt

        used: set[str] = set()
        for package in (thinking_prompt, prompt_toolkit):
            for path in pathlib.Path(package.__file__).parent.rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                for name in re.findall(r"class:([A-Za-z0-9_.-]+)", source):
                    parts = name.split(".")
                    used.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))

        unused = {
            selector
            for selector in ThinkingPromptStyles().to_style_dict()
            if any(cls not in used for cls in selector.split())
        }
        assert unused == set()


class TestDialogRowStyles:
    """Inline dialog rows: numbered actions and check/radio marks."""

    def test_dark_values(self):
        d = ThinkingPromptStyles.dark().to_style_dict()
        assert d["dialog-choice"] == "fg:#e0e0e0"
        assert d["dialog-choice-selected"] == "fg:#88c0d0 bold"
        assert d["checkbox-mark"] == "fg:#88c0d0"
        assert d["dialog-hint"] == "fg:#888888 italic"
        assert d["dialog-title"] == d["dialog frame.label"]


def test_form_fields_have_field_styles():
    """The settings styles were renamed for form fields: no setting_* field
    or setting-* class is left."""
    names = {f.name for f in dataclasses.fields(ThinkingPromptStyles)}
    assert {"field_indicator", "field_label", "field_value_true_selected", "field_desc_selected"} <= names
    assert not any(name.startswith("setting_") for name in names)
    rules = ThinkingPromptStyles.dark().to_style_dict()
    assert {"field-label", "field-dropdown", "field-dropdown-selected"} <= set(rules)
    assert not any(name.startswith("setting-") for name in rules)
