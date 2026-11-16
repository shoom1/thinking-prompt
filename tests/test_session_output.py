"""The session's output methods: what each one prints to the console and
keeps in the transcript."""
from __future__ import annotations

import io
import re
from typing import Any

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.formatted_text import (
    ANSI,
    HTML,
    FormattedText,
    fragment_list_to_text,
    to_formatted_text,
)
from prompt_toolkit.output.vt100 import Vt100_Output

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
            ("add_response", ("x",), "class:transcript.assistant-message", "x\n"),
            ("add_success", ("x",), "class:transcript.success", "[OK] x\n"),
            ("add_warning", ("x",), "class:transcript.warning", "[WARN] x\n"),
            ("add_error", ("x",), "class:transcript.error", "[ERROR] x\n"),
            ("add_system", ("x",), "class:transcript.system", "x\n"),
        ],
        ids=[
            "add_response",
            "add_success",
            "add_warning",
            "add_error",
            "add_system",
        ],
    )
    def test_prints_and_keeps_its_text_in_its_style(self, method, args, style, text):
        session = _session()
        getattr(session, method)(*args)

        (entry,) = _entries(session)
        assert (entry.kind, entry.style, entry.text) == ("styled", style, text)
        (printed,) = session._display.kept
        # The newline unstyled: a background ends with the text.
        assert to_formatted_text(printed) == [(style, text.rstrip("\n")), ("", "\n")]


class TestInputEcho:
    def test_an_echoed_input_is_the_prompt_and_the_text_on_one_line(self):
        session = _session(message="you> ")
        session._display.user_input(session._get_prompt_string(), "hello")

        fragments = [
            ("class:transcript.user-prefix", "you> "),
            ("class:transcript.user-message", "hello"),
            ("", "\n"),
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
    def test_formatted_text_is_printed_and_kept_with_a_newline(self, content):
        session = _session()
        session.add_response(content)

        # Ended as a str response is: a newline (a blank line after it).
        ended = [*_FRAGMENTS, ("", "\n")]
        (entry,) = _entries(session)
        assert (entry.kind, entry.fragments) == ("formatted", ended)
        (printed,) = session._display.kept
        assert to_formatted_text(printed) == ended

    @pytest.mark.parametrize(
        "content",
        [
            FormattedText(_FRAGMENTS),
            list(_FRAGMENTS),
            HTML("<b>Title: </b>Content"),
            ANSI("\x1b[1mTitle: \x1b[0mContent"),
        ],
        ids=["FormattedText", "list", "HTML", "ANSI"],
    )
    def test_formatted_text_reaches_the_terminal_as_its_text(self, content):
        """prompt_toolkit's print shows a plain list as its repr, and an
        object it doesn't take as a str: the terminal gets the text, as the
        transcript does."""
        terminal = io.StringIO()
        output = Vt100_Output(terminal, lambda: Size(rows=24, columns=80), term="xterm")
        with create_app_session(output=output):
            session = ThinkingPromptSession()
            session.add_response(content)

        printed = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", terminal.getvalue())
        assert "Title: Content" in printed
        assert "(" not in printed
        (entry,) = _entries(session)
        assert fragment_list_to_text(entry.fragments) == "Title: Content\n"

    @pytest.mark.parametrize(
        "content",
        [FormattedText([("", "answer")]), [("bold", "answer")], HTML("answer"), ANSI("answer")],
        ids=["FormattedText", "list", "HTML", "ANSI"],
    )
    def test_formatted_text_is_spaced_as_a_str_is(self, content):
        """A blank line after it, as after every message: it had none."""
        def printed(given: Any) -> str:
            return _shown(_terminal(lambda s: s.add_response(given)))

        assert printed(content) == printed("answer")

    @pytest.mark.parametrize(
        "content",
        [
            42,
            None,
            lambda: "hi",
            ["ab", "cd"],
            [("bold",)],
            [("bold", 1)],
            [("a", "text")],
            ANSI("\x1b[38;2;300;0;0mX"),
            HTML('<style fg="nope">x</style>'),
        ],
        ids=[
            "int", "None", "callable", "strings", "short pair", "text not a str", "bad style",
            "ANSI color over 255", "HTML bad color",
        ],
    )
    def test_something_that_isnt_text_is_refused_and_not_kept(self, content):
        """Kept, a bad fragment would fail every repaint after it."""
        session = _session()
        with pytest.raises(ValueError, match=r"add_response\(\) takes"):
            session.add_response(content)
        assert _entries(session) == []
        assert session._display.kept == []

    def test_a_fragment_can_name_style_classes(self):
        """The check read a class name as a color and refused it."""
        session = _session()
        session.add_response([("class:transcript.system bold", "note")])
        (entry,) = _entries(session)
        assert entry.fragments == [("class:transcript.system bold", "note"), ("", "\n")]

    def test_markdown_takes_a_str(self):
        session = _session()
        with pytest.raises(ValueError, match=r"add_response\(markdown=True\) takes a str"):
            session.add_response(HTML("<b>x</b>"), markdown=True)
        assert _entries(session) == []

    def test_a_sequence_of_pairs_is_formatted_text(self):
        session = _session()
        session.add_response((("bold", "Title: "), ("", "Content")))
        (entry,) = _entries(session)
        assert entry.fragments == [*_FRAGMENTS, ("", "\n")]

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


def _terminal(action: Any, **session: Any) -> str:
    """What ``action(session)`` writes to a real (vt100) terminal, for a
    session made with ``session``."""
    terminal = io.StringIO()
    output = Vt100_Output(terminal, lambda: Size(rows=24, columns=80), term="xterm")
    with create_app_session(output=output):
        action(ThinkingPromptSession(**session))
    return terminal.getvalue()


def _shown(raw: str) -> str:
    """``raw`` as the terminal shows it: its color codes dropped."""
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", raw)


# Text that, written raw, sets the terminal's window title.
_INJECTED = "\x01\x1b]0;pwned\x07\x02"


class TestBackgroundsEndWithTheirLine:
    """A newline written with a background color set makes the terminal
    fill the next line with it: a full-width bar after the line (the input
    echo, in the dark and light themes)."""

    @staticmethod
    def _bg_across_a_newline(raw: str) -> bool:
        """True if a newline in ``raw`` comes after a background color
        (48;…) with no color code between."""
        return re.search(r"\x1b\[[0-9;]*48;[0-9;]*m[^\x1b]*\n", raw) is not None

    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_the_input_echo(self, theme: str):
        raw = _terminal(lambda s: s._display.user_input(">>> ", "hello"), theme=theme)
        assert "hello" in raw and not self._bg_across_a_newline(raw), repr(raw)

    def test_a_message_with_a_background(self):
        from thinking_prompt import ThinkingPromptStyles

        theme = ThinkingPromptStyles.dark()
        theme.system_message = "bg:#202020 fg:#ffffff"
        raw = _terminal(lambda s: s.add_system("note"), theme=theme)
        assert "note" in raw and not self._bg_across_a_newline(raw), repr(raw)


def _session_at(columns: int) -> ThinkingPromptSession:
    """A session (keeping its console output) on a terminal ``columns`` wide."""
    with create_app_session(output=_ShortOutput(24, columns=columns)):
        return _session()


def _style_of(fragments: Any, text: str) -> str:
    """The style of the first character of ``text`` in ``fragments`` (one
    character each, as an ANSI parse gives them)."""
    fragments = to_formatted_text(fragments)
    return fragments[fragment_list_to_text(fragments).index(text)][0]


class TestLinks:
    """A link shows its text, then its URL in brackets, `the docs (URL)`,
    laid out by Rich within the width. Rich writes a link as an OSC 8
    hyperlink, which prompt_toolkit's ANSI parser doesn't know (it printed
    "8;id=…;URL" as text), and which hides the URL where the terminal
    doesn't support them."""

    def test_a_markdown_link_shows_its_text_and_url(self):
        pytest.importorskip("rich")
        raw = _terminal(lambda s: s.add_response("See [the docs](https://example.com/docs) for more.", markdown=True))
        assert "\x1b]" not in raw and "8;id=" not in raw
        assert "the docs (https://example.com/docs)" in _shown(raw)

    def test_rich_link_markup_shows_its_text_and_url(self):
        pytest.importorskip("rich")
        from rich.text import Text

        raw = _terminal(lambda s: s.add_rich(Text.from_markup("[link=https://e.com]site[/link] here")))
        assert "\x1b]" not in raw and "8;id=" not in raw
        assert "site (https://e.com) here" in _shown(raw)

    def test_a_link_keeps_its_url_where_rich_sees_a_legacy_windows_console(self, monkeypatch):
        """Rich writes no hyperlinks for a legacy Windows console, so the
        URL was lost on Windows: the session's output isn't one (it goes
        through prompt_toolkit)."""
        pytest.importorskip("rich")
        import rich.console

        monkeypatch.setattr(rich.console, "detect_legacy_windows", lambda: True)
        raw = _terminal(lambda s: s.add_response("See [the docs](https://example.com/docs) for more.", markdown=True))
        assert "the docs (https://example.com/docs)" in _shown(raw)
        raw = _terminal(lambda s: s.add_rich("[link=https://e.com]site[/link] here"))
        assert "site (https://e.com) here" in _shown(raw)

    @pytest.mark.parametrize("source, url", [
        ("Docs: <https://example.com/x>", "https://example.com/x"),
        ("Docs: [https://example.com/x](https://example.com/x)", "https://example.com/x"),
        ("Mail <me@example.com>", "me@example.com"),
    ], ids=["autolink", "text is the URL", "email"])
    def test_a_link_whose_text_is_its_url_shows_it_once(self, source, url):
        pytest.importorskip("rich")
        raw = _terminal(lambda s: s.add_response(source, markdown=True))
        assert _shown(raw).count(url) == 1

    def test_a_link_with_no_text_shows_its_url(self):
        """It showed nothing."""
        pytest.importorskip("rich")
        raw = _terminal(lambda s: s.add_response("See [](https://e.com/empty) here.", markdown=True))
        assert "See https://e.com/empty here." in _shown(raw)

    def test_an_image_shows_its_text_and_url(self):
        pytest.importorskip("rich")
        raw = _terminal(lambda s: s.add_response("![a chart](https://e.com/c.png)", markdown=True))
        assert "a chart (https://e.com/c.png)" in _shown(raw)

    def test_a_links_formatted_text_keeps_its_format(self):
        pytest.importorskip("rich")
        raw = _terminal(lambda s: s.add_response("See [**the** docs](https://e.com) now.", markdown=True))
        assert "the docs (https://e.com) now." in _shown(raw)
        assert re.search(r"\x1b\[[0-9;]*1[0-9;]*mthe", raw)  # "the" bold

    def test_markdown_link_styles_the_text_and_markdown_link_url_the_url(self):
        """markdown_link styled nothing, and markdown_link_url the text."""
        pytest.importorskip("rich")
        from thinking_prompt import ThinkingPromptStyles

        session = _session(theme=ThinkingPromptStyles(markdown_link="bold", markdown_link_url="italic"))
        session.add_response("See [the docs](https://e.com/d) now.", markdown=True)
        (printed,) = session._display.kept
        text, url = _style_of(printed, "the docs"), _style_of(printed, "https://e.com/d")
        assert "bold" in text and "italic" not in text
        assert "italic" in url and "bold" not in url

    @pytest.mark.parametrize("source", [
        "A paragraph long enough to wrap, with [a link to the docs](https://example.com/docs/page) in it and more words after.",
        "> A quote with [a link](https://example.com/quoted/page) near the end of a line of text here.",
        "[one](https://example.com/one) [two](https://example.com/two) [three](https://example.com/three)",
        "- an item with [a short link](https://example.com/short) in it, wrapping onto a second line",
        "| Name | Link |\n|------|------|\n| docs | [here](https://example.com/table-docs) |",
    ], ids=["paragraph", "quote", "links on one line", "list item", "table"])
    def test_markdown_with_links_stays_within_the_width(self, source):
        """The URL was put in after Rich laid the text out, so lines ran
        past the width and the terminal broke them mid-word."""
        pytest.importorskip("rich")
        session = _session_at(40)
        session.add_response(source, markdown=True)
        (printed,) = echoed(session._display)
        assert max(len(line) for line in printed.splitlines()) <= 40, printed

    def test_a_url_that_fits_a_line_isnt_broken_by_a_newline(self):
        """The terminal finds a URL on its line: one cut by a newline opens
        a wrong page. (One longer than a line Rich folds.)"""
        pytest.importorskip("rich")
        url = "https://example.com/" + "a" * 50
        raw = _terminal(lambda s: s.add_response(f"See the long sentence before [the docs]({url}) for more.", markdown=True))
        assert url in _shown(raw)

    def test_rich_text_with_a_link_stays_within_the_width(self):
        pytest.importorskip("rich")
        session = _session_at(40)
        session.add_rich("Some words before [link=https://example.com/a/long/page]the link[/link] and after it")
        (printed,) = echoed(session._display)
        assert max(len(line) for line in printed.splitlines()) <= 40, printed
        assert "the link (https://example.com/a/long/page)" in " ".join(printed.split())

    def test_a_panels_links_are_listed_under_it(self):
        """Its right border was pushed out of line."""
        pytest.importorskip("rich")
        from rich.panel import Panel

        session = _session_at(40)
        session.add_rich(Panel("See [link=https://e.com/docs]the docs[/link] and [link=https://e.com]https://e.com[/link]."))
        (printed,) = echoed(session._display)
        lines = printed.splitlines()
        assert {len(line) for line in lines[:3]} == {40}, printed  # the panel
        assert "See the docs and https://e.com." in lines[1]
        assert lines[3:] == ["the docs (https://e.com/docs)", "https://e.com"]

    def test_a_boxs_rich_text_keeps_no_escapes(self):
        pytest.importorskip("rich")
        session = _session()
        box = session.start_thinking()
        box.append_rich(f"[link=https://e.com]site[/link] {_INJECTED}\n")
        assert "\x1b]" not in box.text and "\x01" not in box.text
        assert "site (https://e.com)" in _shown(box.text)


class TestEscapesInRichOutput:
    """prompt_toolkit writes what's between \x01 and \x02 to the terminal
    raw, so text (a model's answer) could set the window title or the
    clipboard."""


    @pytest.mark.parametrize("path", ["markdown", "rich", "code"])
    @pytest.mark.parametrize("injected", [_INJECTED, "\x9d0;pwned\x07"], ids=["marked", "C1"])
    def test_escapes_in_the_text_never_reach_the_terminal_raw(self, path: str, injected: str):
        """Nor C1 controls (U+009D starts an OSC, U+009B a CSI)."""
        pytest.importorskip("rich")
        pytest.importorskip("pygments")
        text = f"a {injected} b"
        if path == "markdown":
            raw = _terminal(lambda s: s.add_response(text, markdown=True))
        elif path == "rich":
            raw = _terminal(lambda s: s.add_rich(text))
        else:
            raw = _terminal(lambda s: s.add_code(f"x = '{text}'"))
        assert "\x1b]0;" not in raw and "\x01" not in raw and "\x9d" not in raw


# Color codes prompt_toolkit's parser raised on, at print and at every
# repaint after (the entry is kept): a component over 255 (the color
# "#12c0000"), a digit that isn't ASCII (int("²")).
_BAD_CODES = {
    "color over 255": "\x1b[38;2;300;0;0m",
    "background over 255": "\x1b[48;2;0;0;300m",
    "superscript digit": "\x1b[²m",
    "circled digit": "\x1b[①m",
}


def _add(session: ThinkingPromptSession, path: str, text: str) -> None:
    """Print ``text`` as markdown, Rich markup or code."""
    if path == "markdown":
        session.add_response(text, markdown=True)
    elif path == "rich":
        session.add_rich(text)
    else:
        session.add_code(f"x = '{text}'")


class TestMalformedColorCodes:
    @pytest.mark.parametrize("path", ["markdown", "rich", "code"])
    @pytest.mark.parametrize("code", _BAD_CODES.values(), ids=_BAD_CODES.keys())
    def test_text_with_one_prints_and_repaints(self, path: str, code: str):
        pytest.importorskip("rich")
        pytest.importorskip("pygments")

        def print_and_repaint(session: ThinkingPromptSession) -> None:
            _add(session, path, f"before {code}inside\x1b[0m after")
            session._display.print_now(session.app.output, session._display.printed_contents())

        assert _shown(_terminal(print_and_repaint)).count("after") == 2

    @pytest.mark.parametrize("path", ["markdown", "rich", "code"])
    def test_a_cursor_move_isnt_spaces(self, path: str):
        """\x1b[9999C made 9,999 spaces."""
        pytest.importorskip("rich")
        pytest.importorskip("pygments")
        raw = _terminal(lambda s: _add(s, path, "a\x1b[9999Cb"))
        assert "a" + " " * 10 not in _shown(raw)

    @pytest.mark.parametrize("cut", [False, True], ids=["whole", "streamed in two"])
    @pytest.mark.parametrize("code", _BAD_CODES.values(), ids=_BAD_CODES.keys())
    def test_an_ansi_box_draws_one(self, code: str, cut: bool):
        """It raised at every frame."""
        from prompt_toolkit.styles import Style

        from thinking_prompt.thinking_control import ThinkingBoxControl

        text = f"before {code}inside\x1b[0m after\n"
        content = [text[: text.index(code) + 4] if cut else text]
        control = ThinkingBoxControl(lambda: content[0], max_collapsed_lines=5, content_format="ansi")
        control.create_content(80, 5)
        content[0] = text
        drawn = control.create_content(80, 5)
        fragments = [fragment for i in range(drawn.line_count) for fragment in drawn.get_line(i)]
        for style, *_ in fragments:
            Style([]).get_attrs_for_style_str(style)  # raises for a color it can't use
        assert "inside after" in fragment_list_to_text(fragments)


# Control characters a terminal acts on: U+009D starts an OSC (this one
# sets the window title), U+009B a CSI (this one clears the screen); BEL
# rings, BS moves back, SO switches to the line-drawing set, CR to the
# line's start.
_CONTROLS = "\x9d0;pwned\x9c \x9b2J \x07 \x08 \x0e \r"


def _plain_box(session: ThinkingPromptSession, text: str) -> None:
    box = session.start_thinking()
    box.append(text)
    box.finish()


class TestControlCharactersInPlainText:
    """prompt_toolkit's print replaces only ESC: C1 controls, and C0 ones
    but newline and tab, reached the terminal raw from plain text."""

    @pytest.mark.parametrize("print_it", [
        lambda s, text: s.add_response(text),
        lambda s, text: s.add_system(text),
        lambda s, text: s.add_error(text),
        lambda s, text: s.add_response(FormattedText([("bold", text)])),
        lambda s, text: s._display.user_input(">>> ", text),
        _plain_box,
    ], ids=["response", "system", "error", "formatted text", "input echo", "plain box echo"])
    def test_none_reaches_the_terminal(self, print_it):
        def print_and_repaint(session: ThinkingPromptSession) -> None:
            print_it(session, f"before {_CONTROLS} after\tend")
            session._display.print_now(session.app.output, session._display.printed_contents())

        raw = _terminal(print_and_repaint, thinking_echo=True)
        for control in "\x9d\x9c\x9b\x07\x08\x0e\r":
            assert control not in raw.replace("\r\n", "\n"), repr(control)
        assert _shown(raw).count("after\tend") == 2

    def test_an_escape_the_app_marks_zero_width_is_its_own(self):
        """prompt_toolkit writes the text between \\x01 and \\x02 of an
        ANSI() as given: an app's own hyperlink, say."""
        link = "\x1b]8;;https://e.com\x1b\\"
        raw = _terminal(lambda s: s.add_response(ANSI(f"\x01{link}\x02site")))
        assert link in raw


class TestRichWidth:
    """Rich lays its output out at the width of the session's terminal,
    which needn't be the process's (here there's none: Rich alone would
    take 80 columns)."""

    def test_add_rich_lays_a_panel_out_at_the_terminal_width(self):
        pytest.importorskip("rich")
        from rich.panel import Panel

        session = _session_at(40)
        session.add_rich(Panel("boxed"))
        (printed,) = echoed(session._display)
        assert {len(line) for line in printed.splitlines()} == {40}

    def test_markdown_wraps_at_the_terminal_width(self):
        pytest.importorskip("rich")
        session = _session_at(40)
        session.add_response(" ".join(["word"] * 30), markdown=True)
        (printed,) = echoed(session._display)
        assert max(len(line) for line in printed.splitlines()) <= 40

    def test_a_panel_in_a_box_spans_the_terminal_width(self):
        """Not 9999 columns, wrapped into hundreds of rows."""
        pytest.importorskip("rich")
        from rich.panel import Panel

        session = _session_at(40)
        box = session.start_thinking()
        box.append_rich(Panel("boxed"))
        lines = fragment_list_to_text(to_formatted_text(ANSI(box.text))).splitlines()
        assert {len(line) for line in lines} == {40}
