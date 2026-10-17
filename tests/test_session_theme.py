"""Tests for theme selection and color-depth enforcement on the session."""
from __future__ import annotations

import pytest
from prompt_toolkit.output import ColorDepth

from tests.helpers import history_texts, keep_console
from thinking_prompt import ThinkingPromptSession, ThinkingPromptStyles


class TestThemeParam:
    def test_theme_by_name(self):
        s = ThinkingPromptSession(theme="light")
        assert s.styles.code_theme == "default"

    def test_theme_by_instance(self):
        styles = ThinkingPromptStyles.mono()
        s = ThinkingPromptSession(theme=styles)
        assert s.styles is styles

    def test_unknown_theme_raises(self):
        with pytest.raises(ValueError, match="Valid themes"):
            ThinkingPromptSession(theme="solarized")

    def test_default_is_dark(self):
        s = ThinkingPromptSession()
        assert s.styles == ThinkingPromptStyles.dark()

    def test_default_styles_are_not_shared(self, monkeypatch):
        """Without theme=, each session gets its own default styles, so
        tweaking one session's styles doesn't restyle the next session or
        the module-level DEFAULT_STYLES. (monkeypatch restores the field
        even when the instance is shared.)"""
        from thinking_prompt import DEFAULT_STYLES

        first = ThinkingPromptSession()
        monkeypatch.setattr(first.styles, "color_accent", "#ff0000")

        assert ThinkingPromptSession().styles.color_accent != "#ff0000"
        assert DEFAULT_STYLES.color_accent != "#ff0000"


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

    def test_light_theme_depth_none(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = ThinkingPromptSession(theme="light")
        assert s._effective_color_depth() is None

    def test_terminal_theme_depth_none(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        s = ThinkingPromptSession(theme="terminal")
        assert s._effective_color_depth() is None


from unittest.mock import MagicMock


class TestSetTheme:
    def test_set_theme_swaps_styles_and_invalidates(self):
        s = ThinkingPromptSession(theme="dark")
        s.app = MagicMock()
        s.app.is_running = True

        s.set_theme("light")

        assert s.styles.code_theme == "default"
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
    def test_history_limit_keeps_the_last_entries(self):
        s = ThinkingPromptSession(history_limit=3)
        keep_console(s._display)
        for n in range(1, 5):
            s.add_response(str(n))
        assert history_texts(s._display) == ["2\n", "3\n", "4\n"]

    def test_history_limit_defaults_to_unbounded(self):
        s = ThinkingPromptSession()
        assert s._display.history._max_entries is None


class TestRepaint:
    """set_theme(repaint=True) with no app running re-prints the transcript
    through the process-wide AppSession's Output — that Output
    lazily binds sys.stdout the first time any test triggers it and then
    caches that binding for the rest of the run (same issue documented on
    TestTranscriptWiring.test_markdown_stored_as_source in test_display.py).
    Wrapping the act phase in a fresh create_app_session(output=create_output())
    forces a binding to the *current* capsys-patched stdout so the assertions
    don't depend on suite/test ordering.
    """

    def test_repaint_not_running_clears_and_reprints(self, capsys):
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.output.defaults import create_output

        s = ThinkingPromptSession(theme="dark")
        s.app = MagicMock()
        s.app.is_running = False
        with create_app_session(output=create_output()):
            s.add_response("earlier message")
            capsys.readouterr()

            s.set_theme("light", repaint=True)

            out = capsys.readouterr().out
        assert "\x1b[3J" in out          # scrollback erase
        assert "earlier message" in out  # transcript reprinted

    def test_thinking_truncation_reproduced_on_repaint(self, capsys):
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.output.defaults import create_output

        s = ThinkingPromptSession(theme="dark")
        s.app = MagicMock()
        s.app.is_running = False
        with create_app_session(output=create_output()):
            s._display.thinking("l1\nl2\nl3\nl4", truncate_lines=2)
            capsys.readouterr()
            s.set_theme("light", repaint=True)
            out = capsys.readouterr().out
        assert "l1" in out and "..." in out and "l4" not in out

    def test_thinking_exact_truncate_lines_no_ellipsis_on_repaint(self, capsys):
        """A thinking entry whose content is exactly truncate_lines lines
        must NOT grow a stray '...' marker on repaint. The stored entry
        carries an extra trailing "\\n" on top of the content's own
        newlines; feeding that raw into truncate_to_lines miscounts the
        line total and falsely triggers truncation (off-by-one)."""
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.output.defaults import create_output

        s = ThinkingPromptSession(theme="dark")
        s.app = MagicMock()
        s.app.is_running = False
        with create_app_session(output=create_output()):
            s._display.thinking("l1\nl2", truncate_lines=2)
            capsys.readouterr()
            s.set_theme("light", repaint=True)
            out = capsys.readouterr().out
        assert "l1" in out and "l2" in out
        assert "..." not in out

    def test_user_input_reprints_on_one_line(self, capsys):
        """Prompt prefix and message are one transcript entry: repaint must
        render '>>> hello' exactly as the original echo did, not split
        across lines (the prefix has no trailing newline of its own)."""
        from prompt_toolkit.application.current import create_app_session
        from prompt_toolkit.output.defaults import create_output

        s = ThinkingPromptSession(theme="dark")
        s.app = MagicMock()
        s.app.is_running = False
        with create_app_session(output=create_output()):
            s._display.user_input(">>> ", "hello")
            capsys.readouterr()
            s.set_theme("light", repaint=True)
            out = capsys.readouterr().out
        assert ">>> hello" in out

class TestLayoutAppliesThemeClasses:
    """The prompt style field only works if the layout tags its window
    with its class. (Async: rendering the input buffer
    starts a history-loading task, which needs a running loop.)"""

    @staticmethod
    def _cell_style(session: ThinkingPromptSession, text: str) -> str:
        """Render the layout; return the style of the cell where `text` starts."""
        from prompt_toolkit.application.current import set_app
        from prompt_toolkit.layout.mouse_handlers import MouseHandlers
        from prompt_toolkit.layout.screen import Screen, WritePosition

        width, height = 40, 20
        screen = Screen()
        with set_app(session.app):
            session.layout.container.write_to_screen(
                screen, MouseHandlers(), WritePosition(0, 0, width, height), "", True, None
            )
        for y in range(height):
            row = "".join(screen.data_buffer[y][x].char for x in range(width))
            if text in row:
                return screen.data_buffer[y][row.index(text)].style
        raise AssertionError(f"{text!r} not rendered")

    async def test_prompt_window_uses_prompt_class(self):
        s = ThinkingPromptSession(message="PROMPT> ")
        assert "class:prompt" in self._cell_style(s, "PROMPT>")
