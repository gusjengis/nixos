"""Subprocess and logging helpers.

Everything the installer runs goes through here so that a single place decides
how commands are echoed, how their output is captured, and what a failure looks
like. That matters more than usual for this program: it is normally watched by
someone standing at a machine that has just been wiped, and "it failed" without
the command and its output is not a recoverable situation.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

Sink = Callable[[str], None]


class CommandError(RuntimeError):
    """A command exited non-zero.

    Carries the command and captured output so callers can report something
    actionable instead of a bare exit status.
    """

    def __init__(self, command: Sequence[str], returncode: int, output: str) -> None:
        self.command = list(command)
        self.returncode = returncode
        self.output = output
        super().__init__(
            f"command failed with exit status {returncode}: {shlex.join(self.command)}"
        )


@dataclass
class Reporter:
    """Where progress goes.

    The command line writes to stderr; the interface redirects the same stream
    into its log pane. Keeping this behind an object means no step needs to
    know which of the two is running.
    """

    sinks: list[Sink] = field(default_factory=list)
    verbose: bool = False

    def add_sink(self, sink: Sink) -> None:
        self.sinks.append(sink)

    def emit(self, line: str) -> None:
        if not self.sinks:
            print(line, file=sys.stderr, flush=True)
            return
        for sink in self.sinks:
            sink(line)

    def step(self, message: str) -> None:
        self.emit(f"==> {message}")

    def info(self, message: str) -> None:
        self.emit(f"    {message}")

    def warn(self, message: str) -> None:
        self.emit(f"!!! {message}")

    def command(self, command: Sequence[str]) -> None:
        if self.verbose:
            self.emit(f"  $ {shlex.join(command)}")


def _redact(command: Sequence[str], secrets: Iterable[str]) -> list[str]:
    """Replace secret values wherever they appear in a command line.

    The installer handles a GitHub token and two passwords. None of them should
    ever reach a log, a terminal, or a crash report.
    """

    cleaned = []
    real_secrets = [secret for secret in secrets if secret]
    for part in command:
        for secret in real_secrets:
            if secret in part:
                part = part.replace(secret, "<redacted>")
        cleaned.append(part)
    return cleaned


def run(
    command: Sequence[str],
    *,
    reporter: Reporter,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    stdin_text: str | None = None,
    check: bool = True,
    capture: bool = True,
    stream: bool = False,
    secrets: Iterable[str] = (),
) -> subprocess.CompletedProcess[str]:
    """Run a command, reporting it and its output.

    `stream=True` forwards output line by line as it arrives, which is what the
    long-running steps want: `nixos-install` can spend twenty minutes building,
    and silence for twenty minutes is indistinguishable from a hang.
    """

    reporter.command(_redact(command, secrets))

    if not stream:
        completed = subprocess.run(  # noqa: S603 - commands are constructed, never shell-parsed
            list(command),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            input=stdin_text,
            capture_output=capture,
            text=True,
            check=False,
        )
        if check and completed.returncode != 0:
            output = "".join(
                part for part in (completed.stdout, completed.stderr) if part
            )
            raise CommandError(command, completed.returncode, output)
        return completed

    process = subprocess.Popen(  # noqa: S603
        list(command),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    collected: list[str] = []

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            collected.append(line)
            reporter.info(line.rstrip("\n"))

    if stdin_text is not None and process.stdin is not None:
        process.stdin.write(stdin_text)
        process.stdin.close()

    pump_thread = threading.Thread(target=pump, daemon=True)
    pump_thread.start()
    returncode = process.wait()
    pump_thread.join(timeout=5)

    output = "".join(collected)
    if check and returncode != 0:
        raise CommandError(command, returncode, output)

    return subprocess.CompletedProcess(list(command), returncode, output, "")


def which(name: str) -> bool:
    """Whether a program is on PATH.

    The package pins every runtime dependency, so a miss here means the
    installer is running outside its wrapper rather than that something is
    merely uninstalled.
    """

    import shutil

    return shutil.which(name) is not None
