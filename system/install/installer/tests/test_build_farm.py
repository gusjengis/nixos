from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from nixos_installer import build_farm
from nixos_installer.proc import Reporter


class Workspace:
    def eval_json(self, attr):
        if attr.endswith(".nixBuildFarm"):
            return {
                "client": {"enable": True},
                "serverHost": "omega",
                "tailnetDomain": "example.ts.net",
                "serverHostKey": "ssh-ed25519 AAAATEST",
                "sshUser": "nixremote",
                "port": 5000,
                "sshKey": "/home/gusjengis/.config/secrets/ssh/shared_ed25519",
            }
        if attr.endswith(".text"):
            return (
                "ssh-ng://nixremote@omega.example.ts.net x86_64-linux "
                "/home/gusjengis/.config/secrets/ssh/shared_ed25519 4 4 - - -\n"
            )
        return {
            "substituters": [
                "http://omega.example.ts.net:5000",
                "https://cache.nixos.org/",
            ],
            "trusted-public-keys": ["cache-key", "omega-key"],
        }


class CacheResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_disabled_client_does_not_require_tailnet(monkeypatch):
    class ServerWorkspace(Workspace):
        def eval_json(self, attr):
            cfg = super().eval_json(attr)
            cfg["client"]["enable"] = False
            return cfg

    monkeypatch.setattr(
        build_farm,
        "run",
        lambda *_a, **_kw: pytest.fail("disabled client used build farm"),
    )
    with build_farm.bootstrap(ServerWorkspace(), "omega", None, Reporter()) as farm:
        assert farm is None


def test_bootstrap_uses_ephemeral_credentials_and_cleans_up(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:2] == ["git", "clone"]:
            checkout = Path(command[-1])
            (checkout / "ssh").mkdir(parents=True)
            (checkout / "ssh/shared_ed25519").write_text("private-key")
            (checkout / "api_keys").mkdir()
            (checkout / "api_keys/env_vars").write_text("TAILSCALE_AUTH_KEY=secret")
        output = ""
        if command[:2] == ["tailscale", "status"]:
            output = json.dumps({"BackendState": "NeedsLogin"})
        if command[:2] == ["bash", "-c"]:
            output = "secret"
        if command[:2] == ["tailscale", "up"]:
            auth_file = Path(
                command[command.index("--auth-key") + 1].removeprefix("file:")
            )
            assert auth_file.read_text() == "secret"
            assert auth_file.stat().st_mode & 0o777 == 0o600
        error = ""
        if command[:2] == ["nix", "store"]:
            error = "Store URL: ssh-ng://omega\nTrusted: 1\n"
        return subprocess.CompletedProcess(command, 0, output, error)

    monkeypatch.setattr(build_farm, "run", fake_run)
    monkeypatch.setattr(
        build_farm.urllib.request, "urlopen", lambda *_a, **_kw: CacheResponse()
    )
    with build_farm.bootstrap(
        Workspace(), "newhost", "github-token", Reporter()
    ) as farm:
        assert farm is not None
        assert farm.secrets.exists()
        assert farm.options[farm.options.index("max-jobs") + 1] == "0"
        assert str(farm.secrets / "ssh/shared_ed25519") in farm.options[2]
        assert "TS_AUTHKEY=secret" not in " ".join(farm.options)
        assert "StrictHostKeyChecking=yes" in farm.env["NIX_SSHOPTS"]

    assert not farm.secrets.exists()
    assert calls[-1][0] == ["tailscale", "logout"]
    assert calls[3][0][:2] == ["tailscale", "up"]
    auth_file = Path(
        calls[3][0][calls[3][0].index("--auth-key") + 1].removeprefix("file:")
    )
    assert not auth_file.exists()
    assert calls[3][1].get("env") is None
    assert "secret" not in " ".join(calls[3][0])


@pytest.mark.parametrize(
    ("dns_name", "reusable", "trusted"),
    [
        ("install-newhost.example.ts.net.", True, True),
        ("install-newhost.example.ts.net.", True, False),
        ("somebody-else.example.ts.net.", False, True),
    ],
)
def test_existing_identity_is_reused_only_for_same_installer(
    monkeypatch, dns_name, reusable, trusted
):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["git", "clone"]:
            checkout = Path(command[-1])
            (checkout / "ssh").mkdir(parents=True)
            (checkout / "ssh/shared_ed25519").write_text("private-key")
            (checkout / "api_keys").mkdir()
            (checkout / "api_keys/env_vars").write_text("TAILSCALE_AUTH_KEY=secret")
        output = ""
        if command[0] == "bash":
            output = "secret"
        if command[:2] == ["tailscale", "status"]:
            output = json.dumps(
                {"BackendState": "Running", "Self": {"DNSName": dns_name}}
            )
        error = ""
        if command[:2] == ["nix", "store"]:
            error = f"Store URL: ssh-ng://omega\nTrusted: {int(trusted)}\n"
        return subprocess.CompletedProcess(command, 0, output, error)

    monkeypatch.setattr(build_farm, "run", fake_run)
    monkeypatch.setattr(
        build_farm.urllib.request, "urlopen", lambda *_a, **_kw: CacheResponse()
    )
    if reusable and trusted:
        with build_farm.bootstrap(Workspace(), "newhost", "github-token", Reporter()):
            pass
    else:
        message = (
            "did not grant builder access"
            if reusable
            else "different Tailscale identity"
        )
        with (
            pytest.raises(RuntimeError, match=message),
            build_farm.bootstrap(Workspace(), "newhost", "github-token", Reporter()),
        ):
            pytest.fail("different identity should be rejected")

    assert not any(command[:2] == ["tailscale", "up"] for command in calls)
    assert not any(command[:2] == ["tailscale", "logout"] for command in calls)


def test_failed_remote_store_still_logs_out_before_partition(monkeypatch):
    def fake_run(command, **kwargs):
        if command[:2] == ["git", "clone"]:
            checkout = Path(command[-1])
            (checkout / "ssh").mkdir(parents=True)
            (checkout / "ssh/shared_ed25519").write_text("private-key")
            (checkout / "api_keys").mkdir()
            (checkout / "api_keys/env_vars").write_text("TAILSCALE_AUTH_KEY=secret")
        if command[:2] == ["nix", "store"]:
            raise RuntimeError("unreachable")
        output = "secret" if command[0] == "bash" else '{"BackendState":"NeedsLogin"}'
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, output, "")

    calls = []
    monkeypatch.setattr(build_farm, "run", fake_run)
    with (
        pytest.raises(RuntimeError, match="unreachable"),
        build_farm.bootstrap(Workspace(), "newhost", "github-token", Reporter()),
    ):
        pytest.fail("bootstrap should fail")
    assert calls[-1] == ["tailscale", "logout"]
