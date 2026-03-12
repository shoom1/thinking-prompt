"""
Demo: Multiple thinking boxes running concurrently.

Shows:
- Multiple independent boxes with different lifetimes
- Box ordering (task list anchored near prompt)
- Boxes appearing and disappearing dynamically
"""
import asyncio
from thinking_prompt import ThinkingPromptSession, AppInfo


async def main():
    app_info = AppInfo(
        name="MultiBoxDemo",
        version="1.0.0",
        thinking_text="Thinking",
    )
    session = ThinkingPromptSession(app_info=app_info, message=">>> ")

    @session.on_input
    async def handle(text: str):
        if not text.strip():
            return

        if text.strip() == "/quit":
            session.exit()
            return

        # Task list box — anchored near prompt with order=100
        tasks = session.start_thinking(title="Tasks", order=100, max_lines=10)
        tasks.append_rich("[dim]  ○ Download data[/dim]\n")
        tasks.append_rich("[dim]  ○ Process data[/dim]\n")
        tasks.append_rich("[dim]  ○ Generate report[/dim]\n")

        # Step 1: Download
        tasks.set_line_rich(0, "[bold cyan]  ⟳ Downloading data…[/bold cyan]")
        dl = session.start_thinking(title="Download", max_lines=2)
        for pct in range(0, 101, 20):
            dl.set_line(0, f"  {pct}% complete")
            await asyncio.sleep(0.3)
        dl.finish(echo_to_console=False, add_to_history=False)
        tasks.set_line_rich(0, "[green]  ✓ Download data[/green]")

        # Step 2: Process
        tasks.set_line_rich(1, "[bold cyan]  ⟳ Processing data…[/bold cyan]")
        proc = session.start_thinking(title="Process", max_lines=2)
        for i in range(5):
            proc.set_line(0, f"  Processing batch {i+1}/5...")
            await asyncio.sleep(0.4)
        proc.finish(echo_to_console=False, add_to_history=False)
        tasks.set_line_rich(1, "[green]  ✓ Process data[/green]")

        # Step 3: Report
        tasks.set_line_rich(2, "[bold cyan]  ⟳ Generating report…[/bold cyan]")
        await asyncio.sleep(0.5)
        tasks.set_line_rich(2, "[green]  ✓ Generate report[/green]")

        await asyncio.sleep(0.5)
        tasks.finish(echo_to_console=False, add_to_history=False)

        session.add_success("All tasks complete!")

    await session.run_async()


if __name__ == "__main__":
    asyncio.run(main())
