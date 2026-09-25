from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nixos_installer import pipeline
from nixos_installer.model import Answers, Catalog
from nixos_installer.proc import CommandError, Reporter
from nixos_installer.workspace import Workspace


def installer(tmp_path: Path, messages: list[str] | None = None) -> pipeline.Installer:
    mountpoint = tmp_path / "mnt"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "flake.nix").write_text("{}\n")
    reporter = Reporter(sinks=[messages.append] if messages is not None else [])
    return pipeline.Installer(
        workspace=Workspace(checkout, reporter),
        answers=Answers(host="test-vm", github_token="ghp_test"),
        catalog=Catalog("test-vm", "x86_64-linux", (), (), ()),
        reporter=reporter,
        facter_report={},
        mountpoint=mountpoint,
    )


def completed(command: list[str], stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout, "")


def assert_shell_syntax(script: str) -> None:
    result = subprocess.run(
        ["bash", "-n"], input=script, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_stage_home_manager_builds_target_generation(tmp_path, monkeypatch):
    subject = installer(tmp_path)
    installed = subject.mountpoint / "etc/nixos"
    installed.mkdir(parents=True)
    (installed / "flake.nix").write_text("{}\n")
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return completed(list(command))

    monkeypatch.setattr(pipeline, "run", fake_run)
    subject.stage_home_manager()

    marker = subject.mountpoint / pipeline.PENDING_HOME.lstrip("/")
    assert marker.read_text() == "test-vm\n"
    assert calls == [
        [
            "nix",
            "build",
            "--store",
            str(subject.mountpoint),
            "--no-write-lock-file",
            "--out-link",
            str(subject.mountpoint) + pipeline.HOME_GENERATION,
            f"path:{installed.resolve()}#homeConfigurations.test-vm.activationPackage",
        ]
    ]


def test_activation_uses_target_daemon_and_removes_recovery_marker(
    tmp_path, monkeypatch
):
    subject = installer(tmp_path)
    generation = subject.mountpoint / pipeline.HOME_GENERATION.lstrip("/")
    generation.parent.mkdir(parents=True)
    generation.symlink_to("/nix/store/example-home-manager-generation")
    marker = subject.mountpoint / pipeline.PENDING_HOME.lstrip("/")
    marker.write_text("test-vm\n")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))
        return completed(list(command))

    monkeypatch.setattr(pipeline, "run", fake_run)
    subject.activate_home_manager()

    command, kwargs = calls[0]
    script = command[-1]
    assert command[:3] == ["nixos-enter", "--root", str(subject.mountpoint)]
    assert "$system/sw/bin/nix-daemon --daemon" in script
    assert '$system/sw/bin/runuser -u "$user"' in script
    assert f"exec {pipeline.HOME_GENERATION}/activate" in script
    assert kwargs["stream"] is True
    assert_shell_syntax(script)
    assert not marker.exists()


def test_failed_activation_keeps_recovery_marker(tmp_path, monkeypatch):
    subject = installer(tmp_path)
    generation = subject.mountpoint / pipeline.HOME_GENERATION.lstrip("/")
    generation.parent.mkdir(parents=True)
    generation.symlink_to("/nix/store/example-home-manager-generation")
    marker = subject.mountpoint / pipeline.PENDING_HOME.lstrip("/")
    marker.write_text("test-vm\n")

    def fail(command, **_kwargs):
        raise CommandError(command, 1, "activation failed")

    monkeypatch.setattr(pipeline, "run", fail)
    with pytest.raises(CommandError):
        subject.activate_home_manager()
    assert marker.exists()


def test_target_token_uses_environment_and_temporary_file(tmp_path, monkeypatch):
    subject = installer(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))
        return completed(list(command))

    monkeypatch.setattr(pipeline, "run", fake_run)
    subject._run_as_target_user("true", github_token="secret-token")

    command, kwargs = calls[0]
    script = command[-1]
    assert "secret-token" not in script
    assert "secret-token" not in command
    assert kwargs["env"]["NIXOS_INSTALL_GITHUB_TOKEN"] == "secret-token"
    assert kwargs["secrets"] == ["secret-token"]
    assert "(umask 077; printf" in script
    assert 'rm -rf "$runtime"' in script
    assert_shell_syntax(script)


def test_repository_sync_is_noninteractive_and_retries(tmp_path, monkeypatch):
    subject = installer(tmp_path)
    calls: list[tuple[str, str | None]] = []

    def fake_target(command, *, github_token=None):
        calls.append((command, github_token))

    monkeypatch.setattr(subject, "_run_as_target_user", fake_target)
    subject.sync_repositories()

    command, token = calls[0]
    assert token == "ghp_test"
    assert "NIXOS_INSTALL_TOKEN_FILE" in command
    assert "GIT_TERMINAL_PROMPT=0" in command
    assert "BatchMode=yes" in command
    assert "StrictHostKeyChecking=accept-new" in command
    assert "SYNC_REPOS_FAIL_ON_ERROR=1" in command
    assert f"-le {pipeline.REPO_SYNC_ATTEMPTS}" in command
    assert "hm-session-vars.sh" in command
    assert_shell_syntax(command)


def test_repository_sync_failure_warns_instead_of_aborting(tmp_path, monkeypatch):
    messages: list[str] = []
    subject = installer(tmp_path, messages)

    def fail(_command, *, github_token=None):
        assert github_token == "ghp_test"
        raise CommandError(["sync-repos"], 1, "one repo failed")

    monkeypatch.setattr(subject, "_run_as_target_user", fail)
    subject.sync_repositories()
    assert any("could not be synchronized" in message for message in messages)


def test_records_revision_and_removes_staging_link(tmp_path, monkeypatch):
    subject = installer(tmp_path)
    installed = subject.mountpoint / "etc/nixos"
    installed.mkdir(parents=True)
    generation = subject.mountpoint / pipeline.HOME_GENERATION.lstrip("/")
    generation.parent.mkdir(parents=True, exist_ok=True)
    generation.symlink_to("/nix/store/example-home-manager-generation")

    def fake_run(command, **_kwargs):
        assert command[:4] == [
            "git",
            "-c",
            f"safe.directory={installed}",
            "rev-parse",
        ]
        return completed(list(command), "abc123\n")

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(pipeline, "_chown_tree", lambda *_args: None)
    subject.record_deployed_revision()

    revision = (
        subject.mountpoint
        / "home/gusjengis/.local/state/home-manager/deployed-revision"
    )
    assert revision.read_text() == "abc123\n"
    assert not generation.exists()
    assert not generation.is_symlink()


def test_run_all_completes_home_before_reporting_success(tmp_path, monkeypatch):
    subject = installer(tmp_path)
    order: list[str] = []
    steps = (
        "preflight",
        "partition",
        "install_system",
        "place_repository",
        "install_secrets",
        "set_passwords",
        "publish",
        "stage_home_manager",
        "activate_home_manager",
        "sync_repositories",
        "record_deployed_revision",
    )
    for name in steps:
        monkeypatch.setattr(subject, name, lambda name=name: order.append(name))

    subject.run_all()
    assert order == list(steps)
