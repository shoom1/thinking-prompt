#!/usr/bin/env python3
"""
Demo: Progress indicator with in-place updates.

This demo shows how to update a single line in the thinking box
to show progress, rather than appending new lines for each update.

The chunk processing step shows "Processing chunk X/20..." that
updates in place, demonstrating real-time progress feedback.

Run:
    python examples/demo_progress_line.py
"""
import asyncio
import threading

from thinking_prompt import ThinkingPromptSession, AppInfo


class ProgressContent:
    """
    Content manager that supports in-place line updates.

    Maintains completed lines and a current "progress" line that
    can be updated without creating new lines.
    """

    def __init__(self):
        self._lines: list[str] = []
        self._progress_line: str = ""
        self._lock = threading.Lock()

    def add_line(self, text: str) -> None:
        """Add a completed line (with newline)."""
        with self._lock:
            # If there was a progress line, finalize it first
            if self._progress_line:
                self._lines.append(self._progress_line)
                self._progress_line = ""
            self._lines.append(text)

    def set_progress(self, text: str) -> None:
        """Set the current progress line (updates in place)."""
        with self._lock:
            self._progress_line = text

    def clear_progress(self) -> None:
        """Clear the progress line without adding it to lines."""
        with self._lock:
            self._progress_line = ""

    def finalize_progress(self) -> None:
        """Move progress line to completed lines."""
        with self._lock:
            if self._progress_line:
                self._lines.append(self._progress_line)
                self._progress_line = ""

    def get_content(self) -> str:
        """Get the full content for display."""
        with self._lock:
            result = "\n".join(self._lines)
            if self._progress_line:
                if result:
                    result += "\n" + self._progress_line
                else:
                    result = self._progress_line
            return result

    def clear(self) -> None:
        """Clear all content."""
        with self._lock:
            self._lines.clear()
            self._progress_line = ""


async def main():
    app_info = AppInfo(
        name="ProgressDemo",
        version="1.0.0",
        echo_thinking=False,  # Don't echo thinking to console after completion
    )

    session = ThinkingPromptSession(
        app_info=app_info,
        message=">>> ",
        max_thinking_height=10,
    )

    @session.on_input
    async def handle(user_input: str):
        """Process user input with progress indicator."""
        if not user_input.strip():
            return

        content = ProgressContent()
        session.start_thinking(content.get_content)

        try:
            # Phase 1: Setup
            content.add_line("Starting analysis...")
            await asyncio.sleep(0.3)

            content.add_line("Phase 1: Initializing")
            await asyncio.sleep(0.2)
            content.add_line("  ✓ Configuration loaded")
            await asyncio.sleep(0.2)
            content.add_line("  ✓ Resources allocated")
            await asyncio.sleep(0.2)

            # Phase 2: Processing with progress indicator
            content.add_line("Phase 2: Processing data")
            total_chunks = 20

            for i in range(1, total_chunks + 1):
                # Update progress in place (same line)
                progress_bar = "█" * (i * 20 // total_chunks) + "░" * (20 - i * 20 // total_chunks)
                content.set_progress(f"  [{progress_bar}] Chunk {i:2d}/{total_chunks}")
                await asyncio.sleep(0.1)

            # Finalize the progress line
            content.finalize_progress()
            content.add_line("  ✓ All chunks processed")
            await asyncio.sleep(0.2)

            # Phase 3: Verification with spinner-like progress
            content.add_line("Phase 3: Verifying results")
            spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

            for i in range(30):  # Spin for 30 frames
                frame = spinner_frames[i % len(spinner_frames)]
                content.set_progress(f"  {frame} Validating integrity...")
                await asyncio.sleep(0.05)

            content.clear_progress()
            content.add_line("  ✓ Verification complete")
            await asyncio.sleep(0.2)

            # Phase 4: Cleanup with countdown
            content.add_line("Phase 4: Finalizing")
            for i in range(5, 0, -1):
                content.set_progress(f"  Completing in {i}...")
                await asyncio.sleep(0.2)

            content.clear_progress()
            content.add_line("  ✓ Done!")
            await asyncio.sleep(0.2)

            content.add_line("")
            content.add_line(f"Analysis complete for: {user_input[:40]}{'...' if len(user_input) > 40 else ''}")

        finally:
            session.finish_thinking()

        # Show result
        session.add_success(f"Processed: {user_input}")

    # Run the session
    await session.run_async()


if __name__ == "__main__":
    print("Progress Line Demo")
    print("==================")
    print("Type anything to see in-place progress updates in the thinking box.")
    print("Watch the progress bar and spinner update on the same line!")
    print("Press Ctrl+C or Ctrl+D to exit.\n")
    asyncio.run(main())
