"""
Shared fixtures for thinking_prompt tests.
"""
from __future__ import annotations

import asyncio
import sys
import pytest
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from prompt_toolkit.application import create_app_session
from prompt_toolkit.application.current import get_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput, Output
from prompt_toolkit.output import defaults as output_defaults
from prompt_toolkit.output.plain_text import PlainTextOutput

from thinking_prompt import ThinkingPromptSession
from thinking_prompt.transcript import Transcript


@pytest.fixture(autouse=True)
def _plain_text_when_stdout_is_not_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sessions made without an output get prompt_toolkit's default one. When
    stdout isn't a terminal, that's plain text on Linux and macOS, but on
    Windows it raises NoConsoleScreenBufferError (a CI runner has no
    console). Give Windows the plain text too."""
    real = output_defaults.create_output

    def create_output(stdout: Any = None, always_prefer_tty: bool = False) -> Output:
        out = sys.stdout if stdout is None else stdout
        if out is not None and not out.isatty():
            return PlainTextOutput(out)
        return real(stdout, always_prefer_tty)

    monkeypatch.setattr(output_defaults, "create_output", create_output)


class _CurrentStdout:
    """sys.stdout as it is at each write: a test's capsys while it runs."""

    def write(self, data: str) -> int:
        return sys.stdout.write(data)

    def flush(self) -> None:
        sys.stdout.flush()

    def isatty(self) -> bool:
        return sys.stdout.isatty()

    def fileno(self) -> int:
        return sys.stdout.fileno()

    @property
    def encoding(self) -> str:
        return getattr(sys.stdout, "encoding", None) or "utf-8"

    @property
    def buffer(self) -> Any:
        """Its bytes: a stdout that can't encode a character is written
        through it (pytest -s on a cp1252 console)."""
        return sys.stdout.buffer


@pytest.fixture(autouse=True, scope="session")
def _the_default_output_follows_stdout() -> None:
    """prompt_toolkit's process-wide output, which a session made without
    one prints through, is made at the first print and kept. Made under a
    test's capsys, it wrote to a stream pytest closes after that test, and
    every print after it failed ("I/O operation on closed file"): the suite
    depended on the tests' order. It writes to stdout as it is now."""
    get_app_session()._output = PlainTextOutput(_CurrentStdout())  # type: ignore[arg-type]


@pytest.fixture
def transcript() -> Transcript:
    """Create a fresh Transcript instance."""
    return Transcript()


@pytest.fixture
def multiline_content() -> str:
    """Generate multiline content for testing."""
    return "\n".join([f"Line {i}" for i in range(20)])


@asynccontextmanager
async def _running(**kwargs: Any) -> AsyncIterator[ThinkingPromptSession]:
    """A session (built with ``kwargs``) whose app runs on piped input with no output."""
    with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
        session = ThinkingPromptSession(**kwargs)
        run = asyncio.ensure_future(session.run_async(lambda text: None))
        deadline = asyncio.get_running_loop().time() + 2
        while not (session.app.is_running and session.app.future is not None):
            assert asyncio.get_running_loop().time() < deadline, "app didn't start"
            await asyncio.sleep(0.01)
        try:
            yield session
        finally:
            session.exit()
            await asyncio.wait_for(run, timeout=2)


@pytest.fixture
async def running_session() -> AsyncIterator[ThinkingPromptSession]:
    """A session whose app is running (piped input, no output).

    Dialogs need one: only a running app can answer them, so show_dialog()
    refuses to open on a session that isn't running.
    """
    async with _running() as session:
        yield session


@pytest.fixture
def run_session() -> Callable[..., Any]:
    """Like running_session, with session options:
    ``async with run_session(dialog_placement="inline") as session``."""
    return _running
