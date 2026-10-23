"""The session's output methods: what each one prints to the console and
keeps in the transcript."""
from __future__ import annotations

import re
from typing import Any

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.formatted_text import (
    ANSI,
    FormattedText,
    fragment_list_to_text,
    to_formatted_text,
)

from tests.helpers import echoed, keep_console
from tests.test_end_to_end import _ShortOutput
from thinking_prompt import ThinkingPromptSession


def _session(**kwargs: Any) -> ThinkingPromptSession:
    """A session that keeps its console output (echoed() reads it)."""
    session = ThinkingPromptSession(**kwargs)
    keep_console(session._display)
    return session


def _entries(session: ThinkingPromptSession) -> list[Any]:
    return session._display.transcript.iter_entries()


class TestStyledLines:
    """Each of these prints its text in its own style, and the transcript
    keeps that text and style."""

    @pytest.mark.parametrize(
        "method, args, style, text",
        [
            ("add_response", ("x",), "class:history.assistant-message", "x\n"),
            ("add_success", ("x",), "class:history.success", "[OK] x\n"),
            ("add_warning", ("x",), "class:history.warning", "[WARN] x\n"),
            ("add_error", ("x",), "class:history.error", "[ERROR] x\n"),
            ("add_message", ("assistant", "x"), "class:history.assistant-message", "x\n"),
            ("add_message", ("system", "x"), "class:history.system", "x\n"),
            ("add_message", ("thinking", "x"), "class:history.thinking", "x\n"),
        ],
        ids=[
            "add_response",
            "add_success",
            "add_warning",
            "add_error",
            "add_message-assistant",
            "add_message-system",
            "add_message-thinking",
        ],
    )
    def test_prints_and_keeps_its_text_in_its_style(self, method, args, style, text):
        session = _session()
        getattr(session, method)(*args)

        (entry,) = _entries(session)
        assert (entry.kind, entry.style, entry.text) == ("styled", style, text)
        (printed,) = session._display.kept
        assert to_formatted_text(printed) == [(style, text)]


class TestAddMessage:
    def test_a_user_message_is_the_prompt_and_the_text_on_one_line(self):
        session = _session(message="you> ")
        session.add_message("user", "hello")

        fragments = [
            ("class:history.user-prefix", "you> "),
            ("class:history.user-message", "hello\n"),
        ]
        (entry,) = _entries(session)
        assert (entry.kind, entry.fragments) == ("formatted", fragments)
        (printed,) = session._display.kept
        assert to_formatted_text(printed) == fragments


_FRAGMENTS = [("bold", "Title: "), ("", "Content")]


class TestAddResponse:
    @pytest.mark.parametrize(
        "content", [FormattedText(_FRAGMENTS), list(_FRAGMENTS)], ids=["FormattedText", "list"]
    )
    def test_formatted_text_is_printed_and_kept_as_given(self, content):
        session = _session()
        session.add_response(content)

        (entry,) = _entries(session)
        assert (entry.kind, entry.fragments) == ("formatted", _FRAGMENTS)
        (printed,) = session._display.kept
        assert to_formatted_text(printed) == _FRAGMENTS

    def test_markdown_is_printed_rendered_and_kept_as_its_source(self):
        pytest.importorskip("rich")
        source = "# Title\n\n- one\n- two"
        session = _session()
        session.add_response(source, markdown=True)

        (entry,) = _entries(session)
        assert (entry.kind, entry.source) == ("markdown", source)
        (printed,) = echoed(session._display)
        assert "Title" in printed
        assert "#" not in printed
        assert "• one" in printed


class TestAddCode:
    def test_code_is_printed_highlighted_and_kept_as_its_source(self):
        pytest.importorskip("pygments")
        source = "def hello():\n    return 'world'"
        session = _session()
        session.add_code(source)

        (entry,) = _entries(session)
        assert (entry.kind, entry.source, entry.language) == ("code", source, "python")
        (printed,) = session._display.kept
        assert isinstance(printed, ANSI)
        assert re.search(r"\x1b\[[0-9;]*mhello", printed.value)
        assert echoed(session._display) == [source + "\n"]

    def test_the_language_reaches_the_transcript(self):
        session = _session()
        session.add_code("let x = 1;", language="javascript")
        (entry,) = _entries(session)
        assert entry.language == "javascript"


class TestAddRich:
    def test_the_renderable_is_printed_as_rich_draws_it_and_kept_as_drawn(self, monkeypatch):
        pytest.importorskip("rich")
        from rich.panel import Panel

        monkeypatch.delenv("NO_COLOR", raising=False)
        session = _session()
        session.add_rich(Panel("boxed", border_style="green"))

        (printed,) = session._display.kept
        assert isinstance(printed, ANSI)
        # The panel's green corner: ╭, or ┌ where Rich can't tell the console
        # handles it (Windows without a console).
        assert re.search("\x1b\\[32m[╭┌]", printed.value)
        assert "boxed" in echoed(session._display)[0]
        (entry,) = _entries(session)
        assert (entry.kind, entry.source) == ("ansi", printed.value)


class TestRichWidth:
    """Rich lays its output out at the width of the session's terminal,
    which needn't be the process's (here there's none: Rich alone would
    take 80 columns)."""

    @staticmethod
    def _session_at(columns: int) -> ThinkingPromptSession:
        with create_app_session(output=_ShortOutput(24, columns=columns)):
            return _session()

    def test_add_rich_lays_a_panel_out_at_the_terminal_width(self):
        pytest.importorskip("rich")
        from rich.panel import Panel

        session = self._session_at(40)
        session.add_rich(Panel("boxed"))
        (printed,) = echoed(session._display)
        assert {len(line) for line in printed.splitlines()} == {40}

    def test_markdown_wraps_at_the_terminal_width(self):
        pytest.importorskip("rich")
        session = self._session_at(40)
        session.add_response(" ".join(["word"] * 30), markdown=True)
        (printed,) = echoed(session._display)
        assert max(len(line) for line in printed.splitlines()) <= 40

    def test_a_panel_in_a_box_spans_the_terminal_width(self):
        """Not 9999 columns, wrapped into hundreds of rows."""
        pytest.importorskip("rich")
        from rich.panel import Panel

        session = self._session_at(40)
        box = session.start_thinking()
        box.append_rich(Panel("boxed"))
        lines = fragment_list_to_text(to_formatted_text(ANSI(box.text))).splitlines()
        assert {len(line) for line in lines} == {40}
