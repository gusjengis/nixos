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
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field

Sink = Callable[[str], None]

REQUIRED_EXPERIMENTAL_FEATURES = ("flakes", "nix-command")


def merged_nix_config(
    existing: str, *, required: Iterable[str] = REQUIRED_EXPERIMENTAL_FEATURES
) -> str:
    """Add `required` to the `experimental-features` line of a NIX_CONFIG value.

    Every other setting in `existing` is left alone and in place; only the
    `experimental-features` line is rewritten, gaining whatever from `required`
    it did not already have.
    """

    features = set(required)
    found = False
    lines: list[str] = []
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped.startswith("experimental-features"):
            found = True
            _, _, value = stripped.partition("=")
            features.update(value.split())
            lines.append(f"experimental-features = {' '.join(sorted(features))}")
        else:
            lines.append(line)
    if not found:
        lines.append(f"experimental-features = {' '.join(sorted(features))}")
    return "\n".join(line for line in lines if line.strip())


def ensure_experimental_features(env: MutableMapping[str, str]) -> None:
    """Guarantee `nix-command` and `flakes` for every subprocess this program starts.

    A stock installer ISO's default `nix.conf` does not enable either. Typing
    `--extra-experimental-features` on the `nix run` that starts the installer
    only covers that one process; every `nix eval`, `nix build`, `nixos-install`,
    and `disko` invocation this program makes afterwards is a fresh process that
    never sees it. `NIX_CONFIG` is read by all of those, so setting it once here,
    before anything is cloned or evaluated, means the flag on the command line
    that starts the installer is generous documentation rather than something
    every internal step has to repeat, and a shorter command line still works.
    """

    env["NIX_CONFIG"] = merged_nix_config(env.get("NIX_CONFIG", ""))


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


class CommandTimeout(CommandError):
    """A command did not finish within the time it was given.

    Distinguished from a plain `CommandError` because a caller checking a
    network-dependent command, like whether a token is valid, wants to tell
    someone "GitHub did not answer" apart from "GitHub said no".
    """


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
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, reporting it and its output.

    `stream=True` forwards output line by line as it arrives, which is what the
    long-running steps want: `nixos-install` can spend twenty minutes building,
    and silence for twenty minutes is indistinguishable from a hang.

    `timeout` is for the opposite kind of step: a network call that should
    fail fast rather than hang, such as checking a token against GitHub before
    anything destructive has happened. It only applies with `stream=False`;
    nothing here needs both.
    """

    reporter.command(_redact(command, secrets))

    if not stream:
        try:
            completed = subprocess.run(  # noqa: S603 - commands are constructed, never shell-parsed
                list(command),
                cwd=cwd,
                env=dict(env) if env is not None else None,
                input=stdin_text,
                capture_output=capture,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            output = "".join(
                part
                for part in (
                    error.stdout.decode()
                    if isinstance(error.stdout, bytes)
                    else error.stdout,
                    error.stderr.decode()
                    if isinstance(error.stderr, bytes)
                    else error.stderr,
                )
                if part
            )
            raise CommandTimeout(
                command, -1, output or f"timed out after {timeout:g}s"
            ) from error
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
