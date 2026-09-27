"""Temporary build-farm access for builds made from the live installer."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .proc import CommandError, Reporter, run
from .workspace import SECRETS_REPO, Workspace, git_credentials


@dataclass
class BuildFarm:
    options: list[str]
    env: dict[str, str]
    secrets: Path


@contextlib.contextmanager
def bootstrap(
    workspace: Workspace, host: str, token: str | None, reporter: Reporter
) -> Iterator[BuildFarm | None]:
    cfg = workspace.eval_json(f"nixosConfigurations.{host}.config.nixBuildFarm")
    if not cfg["client"]["enable"]:
        yield None
        return

    if not token:
        raise RuntimeError("Build-farm installation requires the GitHub secrets token.")

    reporter.step("Connecting the live installer to the build farm")
    with tempfile.TemporaryDirectory(prefix="nixos-install-build-farm.") as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        secrets = root / "secrets"
        with git_credentials(token) as env:
            run(
                ["git", "clone", "--recurse-submodules", SECRETS_REPO, str(secrets)],
                reporter=reporter,
                env=env,
                secrets=[token],
                stream=True,
            )

        ssh_key = secrets / "ssh" / "shared_ed25519"
        env_vars = secrets / "api_keys" / "env_vars"
        if not ssh_key.is_file() or not env_vars.is_file():
            raise RuntimeError(
                "Secrets checkout lacks the build SSH key or Tailscale auth key file."
            )
        ssh_key.chmod(0o600)

        # The private repo already uses shell syntax for env_vars. Never pass the
        # resulting value as an argument, print it, or put it in Nix evaluation.
        auth_key = run(
            [
                "bash",
                "-c",
                'source "$1"; printf "%s" "${TAILSCALE_AUTH_KEY:-}"',
                "bash",
                str(env_vars),
            ],
            reporter=reporter,
        ).stdout
        if not auth_key:
            raise RuntimeError(
                "TAILSCALE_AUTH_KEY is missing from the secrets checkout."
            )

        state = json.loads(
            run(["tailscale", "status", "--json"], reporter=reporter).stdout
        )
        installer_name = f"install-{host}"
        if state["BackendState"] == "Running":
            dns_name = state.get("Self", {}).get("DNSName", "").rstrip(".")
            if dns_name != f"{installer_name}.{cfg['tailnetDomain']}":
                raise RuntimeError(
                    "Live environment already has a different Tailscale identity; "
                    "refusing to replace it."
                )
            reporter.info("Reusing this installer's existing Tailscale connection")

        logged_in = False
        try:
            if state["BackendState"] != "Running":
                auth_file = root / "tailscale-auth-key"
                auth_file.write_text(auth_key)
                auth_file.chmod(0o600)
                logged_in = True
                run(
                    [
                        "tailscale",
                        "up",
                        "--auth-key",
                        f"file:{auth_file}",
                        "--hostname",
                        installer_name,
                        "--timeout",
                        "30s",
                    ],
                    reporter=reporter,
                )
            fqdn = f"{cfg['serverHost']}.{cfg['tailnetDomain']}"
            known_hosts = root / "known_hosts"
            known_hosts.write_text(f"{fqdn} {cfg['serverHostKey']}\n")
            ssh_options = (
                f"-F /dev/null -i {ssh_key} -o UserKnownHostsFile={known_hosts} "
                "-o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null "
                "-o IdentitiesOnly=yes -o ConnectTimeout=5 -o BatchMode=yes"
            )
            build_env = dict(os.environ)
            build_env["NIX_SSHOPTS"] = ssh_options
            store = run(
                [
                    "nix",
                    "store",
                    "info",
                    "--store",
                    f"ssh-ng://{cfg['sshUser']}@{fqdn}",
                ],
                reporter=reporter,
                env=build_env,
                timeout=15,
            ).stdout
            if "Trusted: 1" not in store:
                raise RuntimeError(
                    "Omega's remote Nix store did not grant builder access."
                )

            cache = f"http://{fqdn}:{cfg['port']}"
            try:
                with urllib.request.urlopen(
                    f"{cache}/nix-cache-info", timeout=10
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Build cache returned HTTP {response.status}."
                        )
            except OSError as error:
                raise RuntimeError(
                    f"Cannot reach Omega build cache: {error}"
                ) from error

            machines = workspace.eval_json(
                f'nixosConfigurations.{host}.config.environment.etc."nix/machines".text'
            )
            settings = workspace.eval_json(
                f"nixosConfigurations.{host}.config.nix.settings"
            )
            configured_key = str(cfg["sshKey"])
            if configured_key not in machines:
                raise RuntimeError(
                    "Build machines do not reference the expected SSH key."
                )
            machines = machines.replace(configured_key, str(ssh_key))
            options = [
                "--option",
                "builders",
                machines,
                "--option",
                "max-jobs",
                "0",
                "--option",
                "builders-use-substitutes",
                "true",
                "--option",
                "substituters",
                " ".join(settings["substituters"]),
                "--option",
                "trusted-public-keys",
                " ".join(settings["trusted-public-keys"]),
                "--option",
                "fallback",
                "true",
                "--option",
                "connect-timeout",
                "5",
                "--option",
                "download-attempts",
                "3",
            ]
            reporter.info(
                "Omega verified; both initial builds will use remote jobs only"
            )
            yield BuildFarm(options, build_env, secrets)
        finally:
            if logged_in:
                with contextlib.suppress(CommandError):
                    run(["tailscale", "logout"], reporter=reporter)
