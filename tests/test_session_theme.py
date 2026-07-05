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
