"""
Shared fixtures for thinking_prompt tests.
"""
from __future__ import annotations

import pytest
from typing import Callable, List

from thinking_prompt import ThinkingPromptStyles
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
