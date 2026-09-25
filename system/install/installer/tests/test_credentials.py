"""Tests for how the GitHub token is handled.

The token is the one secret that has to travel through several subprocesses,
and the installed system's `/etc/nixos` is about to be committed to a public
repository. So: it must not be written anywhere that outlives the step using
it, and it must not appear in anything the installer prints.
"""

from __future__ import annotations

import os
from pathlib import Path

from nixos_installer.proc import Reporter, _redact
from nixos_installer.workspace import git_credentials

TOKEN = "ghp_thisisnotarealtoken"


class TestCredentialHelper:
    def test_helper_exists_only_inside_the_context(self):
        with git_credentials(TOKEN) as env:
            helper = Path(env["GIT_ASKPASS"])
            assert helper.exists()
        assert not helper.exists()
        assert not helper.parent.exists()

    def test_helper_is_private(self):
        with git_credentials(TOKEN) as env:
            helper = Path(env["GIT_ASKPASS"])
            assert helper.stat().st_mode & 0o077 == 0
            assert helper.parent.stat().st_mode & 0o077 == 0

    def test_helper_supplies_the_token(self):
        import subprocess

        with git_credentials(TOKEN) as env:
            result = subprocess.run(
                [env["GIT_ASKPASS"], "Password for 'https://github.com':"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == TOKEN

    def test_git_is_never_left_to_prompt(self):
        with git_credentials(TOKEN) as env:
            assert env["GIT_TERMINAL_PROMPT"] == "0"

    def test_other_credential_helpers_are_disabled(self):
        """A cached `gh` login or keychain helper must not get to answer first.

        Without this, whatever is already configured wherever this runs would
        authenticate silently, and the token just given to the installer
        would never actually be the one git used. Checking a token would then
        say "accepted" regardless of whether that specific token works.
        """

        with git_credentials(TOKEN) as env:
            assert env["GIT_CONFIG_COUNT"] == "1"
            assert env["GIT_CONFIG_KEY_0"] == "credential.helper"
            assert env["GIT_CONFIG_VALUE_0"] == ""

    def test_helper_is_not_placed_next_to_the_checkout(self, tmp_path):
        """The bug this guards against put the token on the installed disk.

        An earlier version wrote the helper beside the repository root, which
        for the installed checkout meant /mnt/etc, i.e. onto the new machine.
        """

        with git_credentials(TOKEN) as env:
            helper = Path(env["GIT_ASKPASS"])
            assert str(helper).startswith(str(Path(os.environ.get("TMPDIR", "/tmp"))))


class TestRedaction:
    def test_secrets_are_replaced_in_logged_commands(self):
        command = ["git", "push", f"https://{TOKEN}@github.com/x"]
        assert _redact(command, [TOKEN]) == [
            "git",
            "push",
            "https://<redacted>@github.com/x",
        ]

    def test_empty_secrets_do_not_redact_everything(self):
        command = ["git", "status"]
        assert _redact(command, ["", None]) == ["git", "status"]  # type: ignore[list-item]

    def test_reporter_writes_to_its_sinks(self):
        lines: list[str] = []
        reporter = Reporter()
        reporter.add_sink(lines.append)
        reporter.step("doing a thing")
        reporter.warn("a problem")
        assert lines == ["==> doing a thing", "!!! a problem"]

    def test_commands_are_only_echoed_when_verbose(self):
        lines: list[str] = []
        reporter = Reporter()
        reporter.add_sink(lines.append)
        reporter.command(["git", "status"])
        assert lines == []

        reporter.verbose = True
        reporter.command(["git", "status"])
        assert lines == ["  $ git status"]
