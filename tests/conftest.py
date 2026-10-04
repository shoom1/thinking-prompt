"""
Shared fixtures for thinking_prompt tests.
"""
from __future__ import annotations

import asyncio
import pytest
from typing import AsyncIterator, Callable, List

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from thinking_prompt import ThinkingPromptSession, ThinkingPromptStyles
from thinking_prompt.thinking import ThinkingBoxControl
from thinking_prompt.history import FormattedTextHistory


@pytest.fixture
def thinking_control() -> ThinkingBoxControl:
    """Create a fresh ThinkingBoxControl instance."""
    return ThinkingBoxControl(max_collapsed_lines=15)


@pytest.fixture
def small_thinking_control() -> ThinkingBoxControl:
    """Create a ThinkingBoxControl with small max lines for testing truncation."""
    return ThinkingBoxControl(max_collapsed_lines=5)


@pytest.fixture
def history() -> FormattedTextHistory:
    """Create a fresh FormattedTextHistory instance."""
    return FormattedTextHistory()


@pytest.fixture
def default_styles() -> ThinkingPromptStyles:
    """Create default styles instance."""
    return ThinkingPromptStyles()


@pytest.fixture
def content_builder() -> Callable[[], tuple[List[str], Callable[[], str]]]:
    """
    Factory fixture that returns a content list and getter function.

    Usage:
        chunks, get_content = content_builder()
        control.start(get_content)
        chunks.append("Hello")
        assert control.content == "Hello"
    """
    def factory() -> tuple[List[str], Callable[[], str]]:
        chunks: List[str] = []
        def get_content() -> str:
            return ''.join(chunks)
        return chunks, get_content
    return factory


@pytest.fixture
def multiline_content() -> str:
    """Generate multiline content for testing."""
    return "\n".join([f"Line {i}" for i in range(20)])


@pytest.fixture
def short_content() -> str:
    """Generate short content that fits in collapsed view."""
    return "\n".join([f"Line {i}" for i in range(3)])


@pytest.fixture
async def running_session() -> AsyncIterator[ThinkingPromptSession]:
    """A session whose app is running (piped input, no output).

    Dialogs need one: only a running app can answer them, so show_dialog()
    refuses to open on a session that isn't running.
    """
    with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
        session = ThinkingPromptSession()
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
