"""Tests for theme selection and color-depth enforcement on the session."""
from __future__ import annotations

import asyncio
import io
import re
from typing import Callable

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.vt100 import Vt100_Output

from tests.helpers import keep_console, transcript_texts
from tests.test_end_to_end import run_with, wait_until
from thinking_prompt import AppInfo, ThinkingPromptSession, ThinkingPromptStyles


class _ColorTerminal(Vt100_Output):
    """A terminal ``rows`` x ``columns`` that shows 24-bit color unless told
    otherwise, and keeps what's written to it, text and escapes. (capsys'
    stdout isn't a tty: prompt_toolkit prints plain text to it.)"""

    def __init__(self, rows: int = 24, columns: int = 80) -> None:
        self._written = io.StringIO()
        self.size = Size(rows=rows, columns=columns)
        super().__init__(
            self._written,
            lambda: self.size,
            term="xterm-256color",
            default_color_depth=ColorDepth.DEPTH_24_BIT,
            enable_cpr=False,
        )

    def text(self) -> str:
        return self._written.getvalue()


def _written_by(terminal: _ColorTerminal, act: Callable[[], None]) -> str:
    """What ``act`` writes to ``terminal``."""
    start = len(terminal.text())
    act()
    return terminal.text()[start:]


def _plain(written: str) -> str:
    """``written`` without its escapes and carriage returns."""
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", written).replace("\r", "")


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


def _respond(session: ThinkingPromptSession) -> None:
    session.add_response("plain reply")
    session.add_response(FormattedText([("fg:#ff0000 bold", "hot"), ("italic", " take")]))


colorless = pytest.mark.parametrize(
    "no_color, theme", [("1", "dark"), ("", "mono")], ids=["NO_COLOR", "mono"]
)


class TestColorlessOutput:
    """Under NO_COLOR, and in the mono theme, the session draws and prints
    without color on a terminal that has it, keeping bold and italic."""

    @colorless
    def test_the_app_draws_in_one_bit_color(self, monkeypatch, no_color, theme):
        monkeypatch.setenv("NO_COLOR", no_color)
        with create_app_session(output=_ColorTerminal()):
            session = ThinkingPromptSession(theme=theme)
        assert session.app.color_depth is ColorDepth.DEPTH_1_BIT

    @colorless
    def test_responses_print_without_color_but_bold_and_italic(self, monkeypatch, no_color, theme):
        monkeypatch.setenv("NO_COLOR", no_color)
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            session = ThinkingPromptSession(theme=theme)
            printed = _written_by(terminal, lambda: _respond(session))
        assert "plain reply" in printed
        assert "38;" not in printed
        assert "\x1b[0;1mhot" in printed
        assert "\x1b[0;3m take" in printed

    @colorless
    def test_a_repaint_prints_without_color(self, monkeypatch, no_color, theme):
        monkeypatch.setenv("NO_COLOR", no_color)
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            session = ThinkingPromptSession(theme=theme)
            _respond(session)
            repainted = _written_by(terminal, lambda: session.set_theme(theme, repaint=True))
        assert "\x1b[3J" in repainted
        assert "plain reply" in repainted
        assert "38;" not in repainted

    def test_a_color_theme_prints_color_on_the_same_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            session = ThinkingPromptSession(theme="dark")
            printed = _written_by(terminal, lambda: _respond(session))
        assert session.app.color_depth is ColorDepth.DEPTH_24_BIT
        assert "38;2;255;0;0" in printed


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
    def test_transcript_limit_keeps_the_last_entries(self):
        s = ThinkingPromptSession(transcript_limit=3)
        keep_console(s._display)
        for n in range(1, 5):
            s.add_response(str(n))
        assert transcript_texts(s._display) == ["2\n", "3\n", "4\n"]

    def test_transcript_limit_defaults_to_unbounded(self):
        s = ThinkingPromptSession()
        assert s._display.transcript._max_entries is None


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


def _repainted(session: ThinkingPromptSession, terminal: _ColorTerminal) -> str:
    """What set_theme("light", repaint=True) writes, with no app running."""
    return _written_by(terminal, lambda: session.set_theme("light", repaint=True))


class TestRepaintedContent:
    """A repaint prints markdown and code rendered, not their source, and
    Rich output as it was first printed."""

    def test_markdown_is_repainted_rendered(self):
        pytest.importorskip("rich")
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            session = ThinkingPromptSession(theme="dark")
            session.add_response("# Title\n\nbody", markdown=True)
            repainted = _plain(_repainted(session, terminal))
        assert "Title" in repainted
        assert "─────" in repainted
        assert "# Title" not in repainted

    def test_code_is_repainted_highlighted(self, monkeypatch):
        pytest.importorskip("pygments")
        monkeypatch.delenv("NO_COLOR", raising=False)
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            session = ThinkingPromptSession(theme="dark")
            session.add_code("def hello():\n    return 'world'")
            repainted = _repainted(session, terminal)
        assert "def hello():" in _plain(repainted)
        assert re.search(r"\x1b\[[0-9;]*mhello", repainted)

    @pytest.mark.parametrize("shown_by", ["add_rich", "banner"])
    def test_rich_output_is_repainted_as_first_printed(self, monkeypatch, shown_by):
        pytest.importorskip("rich")
        monkeypatch.delenv("NO_COLOR", raising=False)
        from rich.panel import Panel

        panel = Panel("boxed", border_style="green")
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            if shown_by == "banner":
                session = ThinkingPromptSession(
                    theme="dark", app_info=AppInfo(name="App", welcome_message=lambda: panel)
                )
                printed = _written_by(terminal, session._print_welcome)
            else:
                session = ThinkingPromptSession(theme="dark")
                printed = _written_by(terminal, lambda: session.add_rich(panel))
            repainted = _repainted(session, terminal)
        # The panel's green corner: ╭, or ┌ where Rich can't tell the console
        # handles it (Windows without a console).
        assert re.search("\x1b\\[0;32m[╭┌]", printed)
        assert printed in repainted


    def test_a_response_repaints_with_its_own_spacing(self):
        """Its trailing newlines too: a repaint prints what was printed."""
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            session = ThinkingPromptSession()
            printed = _plain(_written_by(terminal, lambda: session.add_response("answer\n\n")))
            repainted = _plain(_repainted(session, terminal))
        assert printed == "answer\n\n\n\n"
        assert printed in repainted

    @pytest.mark.parametrize(
        "session_kwargs, finish_kwargs",
        [({"echo_thinking": False}, {}), ({}, {"echo_to_console": False})],
        ids=["echo_thinking", "echo_to_console"],
    )
    def test_a_box_not_echoed_is_not_repainted(self, session_kwargs, finish_kwargs):
        """A repaint prints what was printed: a box finished without its
        echo doesn't appear when the terminal is repainted."""
        terminal = _ColorTerminal()
        with create_app_session(output=terminal):
            session = ThinkingPromptSession(**session_kwargs)
            box = session.start_thinking()
            box.append("unseen thought\n")
            box.finish(**finish_kwargs)
            session.add_response("seen reply")
            repainted = _plain(_repainted(session, terminal))
        assert "seen reply" in repainted
        assert "unseen thought" not in repainted

class TestRepaintAfterShrinking:
    """Once a running session's terminal stops shrinking, the transcript
    repaints the same way: banner, markdown and code rendered."""

    async def test_the_banner_markdown_and_code_are_repainted_rendered(self, monkeypatch):
        pytest.importorskip("rich")
        pytest.importorskip("pygments")
        monkeypatch.delenv("NO_COLOR", raising=False)
        terminal = _ColorTerminal()

        async def handler(text: str) -> None:
            pass

        with create_pipe_input() as inp, create_app_session(input=inp, output=terminal):
            session = ThinkingPromptSession(app_info=AppInfo(name="App", version="1.0"))

            async def script(run: asyncio.Task[None]) -> None:
                session.add_response("# Title\n\nbody", markdown=True)
                session.add_code("def hello():\n    return 'world'")
                await wait_until(lambda: "'world'" in terminal.text())
                start = len(terminal.text())
                terminal.size = Size(rows=12, columns=80)
                session.app.invalidate()
                await wait_until(lambda: "\x1b[3J" in terminal.text()[start:])

                repainted = terminal.text()[start:].split("\x1b[3J", 1)[1]
                plain = _plain(repainted)
                assert "App v1.0" in plain
                assert "Title" in plain and "# Title" not in plain
                assert "def hello():" in plain
                assert re.search(r"\x1b\[[0-9;]*mhello", repainted)

            await run_with(session, handler, script)

    async def test_markdown_is_repainted_at_the_new_width(self):
        """After the terminal narrows, markdown is laid out again at the
        new width, not as rendered for an earlier repaint."""
        pytest.importorskip("rich")
        terminal = _ColorTerminal(columns=80)

        async def handler(text: str) -> None:
            pass

        with create_pipe_input() as inp, create_app_session(input=inp, output=terminal):
            session = ThinkingPromptSession()

            async def script(run: asyncio.Task[None]) -> None:
                session.add_response(" ".join(["word"] * 30), markdown=True)
                await wait_until(lambda: "word" in terminal.text())
                # Shorter first, then narrower: two repaints.
                for size in (Size(rows=12, columns=80), Size(rows=12, columns=40)):
                    start = len(terminal.text())
                    terminal.size = size
                    session.app.invalidate()
                    await wait_until(lambda start=start: "\x1b[3J" in terminal.text()[start:])

                repainted = _plain(terminal.text()[start:])
                assert "word" in repainted
                # 16 words fit a line 80 columns wide; 8 fit 40.
                assert not re.search(r"(word ){8}word", repainted)

            await run_with(session, handler, script)


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
