#!/usr/bin/env python3
"""
Run shell commands as background jobs, each streaming its output into its
own numbered thinking box while the prompt takes the next command.

    python examples/shell_jobs.py

Try `ping -c 20 127.0.0.1`, then another command while it runs. `/stop 1`
stops job 1, and `rm ...` asks first. Ctrl+C at the prompt leaves the jobs
running; Ctrl+D exits and stops them. Ctrl+T shows all of the output.
"""
import asyncio
import itertools

from thinking_prompt import AppInfo, ThinkingPromptSession


async def main() -> None:
    # The demo owns its jobs: each runs in its own task, which feeds its box.
    jobs: dict[int, asyncio.Task[None]] = {}
    numbers = itertools.count(1)
    session = ThinkingPromptSession(
        app_info=AppInfo(name="Shell jobs", welcome_message="Commands run as background jobs."),
        message="$ ",
        status_text=lambda: f"{len(jobs)} running | /stop N stops one | Ctrl+D: exit",
    )

    async def run_job(n: int, command: str) -> None:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        assert proc.stdout is not None
        try:
            # The box belongs to this task: it stays open after the handler
            # that started the job returns, and Ctrl+C at the prompt leaves it.
            async with session.thinking(title=f"[{n}] {command}") as box:
                async for line in proc.stdout:
                    box.append(line.decode(errors="replace"))
            code = await proc.wait()
        except asyncio.CancelledError:  # /stop, or the demo exiting
            if proc.returncode is None:
                proc.kill()
            raise
        report = session.add_success if code == 0 else session.add_error
        report(f"[{n}] {command}: exit {code}")

    @session.on_input
    async def handle(text: str) -> None:
        command = text.strip()
        if command.startswith("/stop"):
            args = command.split()[1:]
            if not args:
                session.add_warning("Usage: /stop N")
            for arg in args:
                job = jobs.get(int(arg)) if arg.isdigit() else None
                if job is None:
                    session.add_warning(f"No job {arg}.")
                else:
                    job.cancel()
        elif command.split()[:1] == ["rm"] and not await session.yes_no_dialog(
            "Run it?", command
        ):
            session.add_warning("Not run.")
        elif command:
            n = next(numbers)
            jobs[n] = asyncio.create_task(run_job(n, command))
            jobs[n].add_done_callback(lambda _: jobs.pop(n))

    await session.run_async()
    # The jobs are the demo's to stop: stop the ones still running.
    running = list(jobs.values())
    for job in running:
        job.cancel()
    await asyncio.gather(*running, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
