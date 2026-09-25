"""Tests for validating a GitHub token before it is trusted.

The token is typed once, hidden, on a live medium with no way to see what was
actually typed. Confirming it against GitHub before anything is destroyed
turns "I'm not sure if that was right" into a definite answer, in the same
place `preflight()` already refuses to start on a machine it cannot install
onto.

None of these tests touch the network: `nixos_installer.workspace.run` is
replaced with a fake that raises exactly what a real `git ls-remote` would for
each case, so the branching in `check_github_token` is what gets exercised.
"""

from __future__ import annotations

from nixos_installer.proc import CommandError, CommandTimeout
from nixos_installer.workspace import SECRETS_REPO, check_github_token

TOKEN = "ghp_thisisnotarealtoken"


class TestCheckGithubToken:
    def test_empty_token_is_rejected_without_touching_the_network(self, monkeypatch):
        def fail_if_called(*args, **kwargs):
            raise AssertionError("should not run a command for an empty token")

        monkeypatch.setattr("nixos_installer.workspace.run", fail_if_called)
        ok, message = check_github_token("")
        assert ok is False
        assert "no token" in message.lower()

    def test_success_reports_the_repository_as_reachable(self, monkeypatch):
        def fake_run(command, **kwargs):
            assert command[:2] == ["git", "ls-remote"]
            assert SECRETS_REPO in command

        monkeypatch.setattr("nixos_installer.workspace.run", fake_run)
        ok, message = check_github_token(TOKEN)
        assert ok is True
        assert "reachable" in message.lower()

    def test_rejected_token_is_reported_distinctly_from_a_network_problem(
        self, monkeypatch
    ):
        def fake_run(command, **kwargs):
            raise CommandError(
                command, 128, "remote: Repository not found.\nfatal: ..."
            )

        monkeypatch.setattr("nixos_installer.workspace.run", fake_run)
        ok, message = check_github_token(TOKEN)
        assert ok is False
        assert "rejected" in message.lower()

    def test_dns_failure_is_reported_as_a_network_problem_not_a_bad_token(
        self, monkeypatch
    ):
        def fake_run(command, **kwargs):
            raise CommandError(
                command,
                128,
                "fatal: unable to access 'https://github.com/...': "
                "Could not resolve host: github.com",
            )

        monkeypatch.setattr("nixos_installer.workspace.run", fake_run)
        ok, message = check_github_token(TOKEN)
        assert ok is False
        assert "reach" in message.lower()
        assert "rejected" not in message.lower()

    def test_timeout_is_reported_as_a_network_problem(self, monkeypatch):
        def fake_run(command, **kwargs):
            raise CommandTimeout(command, -1, "timed out after 15s")

        monkeypatch.setattr("nixos_installer.workspace.run", fake_run)
        ok, message = check_github_token(TOKEN)
        assert ok is False
        assert "timed out" in message.lower()

    def test_the_token_itself_never_appears_in_the_message(self, monkeypatch):
        def fake_run(command, **kwargs):
            raise CommandError(command, 128, f"fatal: bad credentials {TOKEN}")

        monkeypatch.setattr("nixos_installer.workspace.run", fake_run)
        _, message = check_github_token(TOKEN)
        assert TOKEN not in message

    def test_checks_a_custom_repo_when_given_one(self, monkeypatch):
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command

        monkeypatch.setattr("nixos_installer.workspace.run", fake_run)
        check_github_token(TOKEN, repo="https://github.com/example/other.git")
        assert "https://github.com/example/other.git" in seen["command"]
