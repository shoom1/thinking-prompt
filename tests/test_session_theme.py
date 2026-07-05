"""Tests for theme selection and color-depth enforcement on the session."""
from __future__ import annotations

import pytest
from prompt_toolkit.output import ColorDepth

from thinking_prompt import ThinkingPromptSession, ThinkingPromptStyles


class TestThemeParam:
    def test_theme_by_name(self):
        s = ThinkingPromptSession(theme="light")
        assert s.styles.markdown_code_theme == "default"

    def test_theme_by_instance(self):
        styles = ThinkingPromptStyles.mono()
        s = ThinkingPromptSession(theme=styles)
        assert s.styles is styles

    def test_theme_and_styles_together_raises(self):
        with pytest.raises(ValueError, match="theme"):
            ThinkingPromptSession(theme="dark", styles=ThinkingPromptStyles())

    def test_unknown_theme_raises(self):
        with pytest.raises(ValueError, match="Valid themes"):
            ThinkingPromptSession(theme="solarized")

    def test_default_is_dark(self):
        s = ThinkingPromptSession()
        assert s.styles == ThinkingPromptStyles.dark()

    def test_styles_param_still_works(self):
        styles = ThinkingPromptStyles(color_accent="#ff6600")
        s = ThinkingPromptSession(styles=styles)
        assert s.styles is styles


class TestEffectiveColorDepth:
    def test_no_color_forces_1bit(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        s = ThinkingPromptSession(theme="dark")
        assert s._effective_color_depth() is ColorDepth.DEPTH_1_BIT

    def test_empty_no_color_ignored(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "")
        s = ThinkingPromptSession(theme="dark")
        assert s._effective_color_depth() is None

    def test_mono_theme_1bit(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = ThinkingPromptSession(theme="mono")
        assert s._effective_color_depth() is ColorDepth.DEPTH_1_BIT

    def test_default_depth_none(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = ThinkingPromptSession()
        assert s._effective_color_depth() is None


from unittest.mock import MagicMock


class TestSetTheme:
    def test_set_theme_swaps_styles_and_invalidates(self):
        s = ThinkingPromptSession(theme="dark")
        s.app = MagicMock()
        s.app.is_running = True

        s.set_theme("light")

        assert s.styles.markdown_code_theme == "default"
        s.app.invalidate.assert_called()

    def test_set_theme_accepts_instance(self):
        s = ThinkingPromptSession()
        custom = ThinkingPromptStyles(color_accent="#ff6600")
        s.set_theme(custom)
        assert s.styles is custom

    def test_set_theme_updates_display_style(self):
        s = ThinkingPromptSession(theme="dark")
        before = s._display._get_style()
        s.set_theme("light")
        assert s._display._get_style() is not before

    def test_set_theme_recomputes_depth(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = ThinkingPromptSession(theme="dark")
        assert s._effective_color_depth() is None
        s.set_theme("mono")
        from prompt_toolkit.output import ColorDepth
        assert s._effective_color_depth() is ColorDepth.DEPTH_1_BIT

    def test_app_style_is_dynamic(self):
        from prompt_toolkit.styles import DynamicStyle
        s = ThinkingPromptSession()
        assert isinstance(s.app.style, DynamicStyle)


class TestHistoryLimit:
    def test_history_limit_flows_to_display(self):
        s = ThinkingPromptSession(history_limit=3)
        assert s._display.history._max_entries == 3

    def test_history_limit_defaults_to_unbounded(self):
        s = ThinkingPromptSession()
        assert s._display.history._max_entries is None
