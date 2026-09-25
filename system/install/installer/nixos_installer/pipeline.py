"""Turning resolved answers into an installed machine.

The steps run in one order and each one is separately reportable, because this
is the part someone watches. Nothing here asks a question: by the time the
pipeline starts, every decision has already been made, either on the command
line or in the interface.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .model import Answers, Catalog
from .probe import is_portable
from .proc import CommandError, Reporter, run
from .workspace import SECRETS_REPO, Workspace, check_github_token, git_credentials

TARGET_USER = "gusjengis"
MOUNTPOINT = Path("/mnt")
MARKER_DIR = "var/lib/nixos-install"


class PreflightError(RuntimeError):
    """Something about this machine makes the installation unsafe to start."""


@dataclass
class Installer:
    workspace: Workspace
    answers: Answers
    catalog: Catalog
    reporter: Reporter
    facter_report: dict[str, object]
    mountpoint: Path = MOUNTPOINT
    prebuild_home: bool = True

    # -- checks -----------------------------------------------------------

    def preflight(self) -> None:
        """Refuse to start on a machine where this cannot work.

        Every check here is one that would otherwise fail later, after the
        disk has been erased.
        """

        self.reporter.step("Checking this machine")

        if os.geteuid() != 0:
            raise PreflightError(
                "The installer partitions disks and installs a system, so it "
                "has to run as root. Re-run it with sudo."
            )

        if not Path("/sys/firmware/efi").exists():
            raise PreflightError(
                "This machine booted without UEFI firmware, but the shared "
                "configuration installs GRUB in EFI mode. Switch the firmware "
                "out of legacy/CSM boot and try again."
            )

        device = Path(self.answers.disk or "")
        if not device.exists():
            raise PreflightError(f"{device} does not exist.")
        if not device.is_block_device():
            raise PreflightError(f"{device} is not a block device.")

        if self._is_live_medium(device):
            raise PreflightError(
                f"{device} is the medium this installer booted from. "
                "Choose the disk you want to install onto."
            )

        self.reporter.info("UEFI firmware, running as root, target disk is real")

        if self.answers.github_token:
            self.reporter.step("Checking the GitHub token")
            ok, message = check_github_token(
                self.answers.github_token, reporter=self.reporter
            )
            if not ok:
                raise PreflightError(
                    f"{message} Fix it on the Secrets tab, or clear the token "
                    "and continue without one; the machine will still "
                    "install, just without secrets."
                )
            self.reporter.info(message)

    def _is_live_medium(self, device: Path) -> bool:
        """Whether the chosen disk is the one currently supplying the ISO.

        Overwriting it mid-install is not recoverable, and it is an easy
        mistake when the installer USB shows up alongside the real disks.
        """

        try:
            completed = run(
                ["findmnt", "--json", "--target", "/iso"],
                reporter=self.reporter,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                payload = json.loads(completed.stdout)
                for entry in payload.get("filesystems", []):
                    source = str(entry.get("source", ""))
                    if source.startswith(str(device)):
                        return True
        except (CommandError, json.JSONDecodeError):
            pass
        return False

    # -- steps ------------------------------------------------------------

    def partition(self) -> None:
        host = self.answers.host
        assert host

        self.reporter.step(f"Partitioning {self.answers.disk} with Disko")
        self.reporter.warn(f"Everything on {self.answers.disk} is being destroyed now")

        run(
            [
                "disko",
                "--mode",
                "destroy,format,mount",
                "--flake",
                f"{self.workspace.flake}#{host}",
                "--root-mountpoint",
                str(self.mountpoint),
                "--yes-wipe-all-disks",
            ],
            reporter=self.reporter,
            stream=True,
        )

    def install_system(self) -> None:
        host = self.answers.host
        assert host

        self.reporter.step(f"Installing NixOS for {host}")
        self.reporter.info("This is the long part. Output follows.")

        run(
            [
                "nixos-install",
                "--flake",
                f"{self.workspace.flake}#{host}",
                "--root",
                str(self.mountpoint),
                # Passwords are set explicitly afterwards, for both accounts,
                # so nixos-install must not stop to prompt for one.
                "--no-root-password",
                "--no-channel-copy",
            ],
            reporter=self.reporter,
            stream=True,
        )

    def place_repository(self) -> None:
        """Put the configuration where every command expects to find it.

        `/mnt/etc/nixos` now is `/etc/nixos` after the reboot; it is the same
        directory, seen from the installer rather than from the installed
        system. `rebuild`, `rehome`, and `update` all read that path.
        """

        target = self.mountpoint / "etc" / "nixos"
        self.reporter.step(f"Placing the configuration at /etc/nixos ({target})")

        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.workspace.root, target, symlinks=True)

        uid, gid = self._target_user_ids()
        _chown_tree(target, uid, gid)

        # Owned by the user who edits it, readable by root, which evaluates it
        # on every rebuild. Not group- or world-writable: root evaluating a
        # tree that other accounts can edit is a privilege escalation.
        os.chmod(target, 0o755)

    def install_secrets(self) -> None:
        """Clone the private secrets checkout into the new home directory.

        One GitHub token is enough to finish the machine: the checkout carries
        the personal access token the shell exports, the SSH keys, the SMB
        credentials, and the Tailscale auth key that the autoconnect unit reads
        on first boot. Without it the machine comes up with no credentials and,
        if it is headless, no way to reach it.
        """

        token = self.answers.github_token
        if not token:
            self.reporter.warn(
                "No GitHub token given, so no secrets were installed. "
                "This machine will not join the tailnet by itself."
            )
            return

        self.reporter.step("Installing secrets")

        home = self.mountpoint / "home" / TARGET_USER
        target = home / ".config" / "secrets"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)

        try:
            with git_credentials(token) as env:
                run(
                    ["git", "clone", "--recurse-submodules", SECRETS_REPO, str(target)],
                    reporter=self.reporter,
                    env=env,
                    stream=True,
                )
        except CommandError as error:
            raise RuntimeError(
                "Could not clone the secrets repository. The token needs `repo` "
                "scope to read a private repository.\n" + error.output
            ) from error

        uid, gid = self._target_user_ids()
        _chown_tree(target, uid, gid)
        _chown_tree(home / ".config", uid, gid)

        # Git does not preserve modes beyond the executable bit, so private
        # keys arrive world-readable. Home Manager repairs this on activation
        # too, but the window between now and then includes a reboot.
        os.chmod(target, 0o700)
        ssh_dir = target / "ssh"
        if ssh_dir.is_dir():
            os.chmod(ssh_dir, 0o700)
            for entry in ssh_dir.iterdir():
                if entry.is_file():
                    os.chmod(entry, 0o644 if entry.suffix == ".pub" else 0o600)

        self._check_tailscale_key(target)

    def _check_tailscale_key(self, secrets: Path) -> None:
        env_vars = secrets / "api_keys" / "env_vars"
        if not env_vars.exists():
            self.reporter.warn(
                "The secrets checkout has no api_keys/env_vars, so this machine "
                "will not authenticate to Tailscale on its own."
            )
            return
        if "TAILSCALE_AUTH_KEY" not in env_vars.read_text():
            self.reporter.warn(
                "No TAILSCALE_AUTH_KEY in the secrets checkout. A headless "
                "machine will come up unreachable."
            )

    def stage_home_manager(self) -> None:
        """Build the Home Manager closure into the new system's store.

        Activation itself waits for first boot, where there is a nix-daemon, a
        real session, and an initialised per-user profile. Building it now
        means that first boot links an existing closure instead of compiling a
        desktop, so the machine comes up finished rather than busy.
        """

        host = self.answers.host
        assert host

        marker_dir = self.mountpoint / MARKER_DIR
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "pending-home-manager").write_text(f"{host}\n")

        if not self.prebuild_home:
            self.reporter.info(
                "Skipping the Home Manager pre-build; first boot will build it."
            )
            return

        self.reporter.step("Building the Home Manager closure into the new system")
        try:
            run(
                [
                    "nix",
                    "build",
                    "--store",
                    str(self.mountpoint),
                    "--no-write-lock-file",
                    "--no-link",
                    "--print-out-paths",
                    f"{self.workspace.flake}#homeConfigurations.{host}.activationPackage",
                ],
                reporter=self.reporter,
                stream=True,
            )
        except CommandError as error:
            # Not fatal: the first-boot unit can still build it, given network.
            self.reporter.warn(
                "Could not pre-build the Home Manager closure. The machine will "
                "build it on first boot instead, which needs a network "
                f"connection then.\n{error.output}"
            )

    def set_passwords(self) -> None:
        """Set the user and root passwords inside the installed system.

        Passed on stdin rather than as arguments so they never reach a process
        list, and never recorded in the configuration: a password hash in a
        tracked file would be readable by anyone who can read the repository.
        """

        user_password = self.answers.user_password
        root_password = self.answers.effective_root_password()

        if not user_password:
            self.reporter.warn(
                f"No password set for {TARGET_USER}. Set one before rebooting."
            )
            return

        self.reporter.step("Setting account passwords")

        lines = [f"{TARGET_USER}:{user_password}"]
        if root_password:
            lines.append(f"root:{root_password}")

        run(
            ["nixos-enter", "--root", str(self.mountpoint), "--command", "chpasswd"],
            reporter=self.reporter,
            stdin_text="\n".join(lines) + "\n",
            secrets=self.answers.secrets(),
        )

        if not root_password:
            self.reporter.info(
                "Root has no password. sudo is passwordless for the wheel group, "
                "so this is usable; it does mean no root login at the console."
            )

    def publish(self) -> None:
        """Commit and push the new machine's files.

        Done from the installed checkout rather than the temporary one so that
        what gets pushed is exactly what the machine will read afterwards.
        """

        host = self.answers.host
        assert host

        installed = Workspace(
            root=self.mountpoint / "etc" / "nixos", reporter=self.reporter
        )
        installed.commit_and_push(
            host,
            token=self.answers.github_token,
            push=self.answers.push,
        )
        uid, gid = self._target_user_ids()
        _chown_tree(installed.root / ".git", uid, gid)

    # -- helpers ----------------------------------------------------------

    def _target_user_ids(self) -> tuple[int, int]:
        """Look up the installed system's ids for the target user.

        Read from the installed passwd file rather than assumed to be 1000,
        because the installer's own environment has different accounts.
        """

        passwd = self.mountpoint / "etc" / "passwd"
        if passwd.exists():
            for line in passwd.read_text().splitlines():
                fields = line.split(":")
                if len(fields) > 3 and fields[0] == TARGET_USER:
                    return int(fields[2]), int(fields[3])
        self.reporter.warn(
            f"{TARGET_USER} is not in the installed system's passwd file; "
            "falling back to 1000:100"
        )
        return 1000, 100

    def summary(self) -> str:
        host = self.answers.host
        portable = is_portable(self.facter_report)
        selections = self.answers.with_defaults(self.catalog)
        enabled = sorted(role for role, on in selections.items() if on)

        lines = [
            f"Host:     {host}",
            f"Disk:     {self.answers.disk} ({self.answers.layout} layout)",
            f"Chassis:  {'laptop' if portable else 'desktop'} (detected)",
            f"Modules:  {', '.join(enabled) if enabled else 'none'}",
            f"Secrets:  {'yes' if self.answers.github_token else 'no'}",
            f"Push:     {'yes' if self.answers.push else 'no'}",
        ]
        return "\n".join(lines)

    def run_all(self) -> None:
        self.preflight()
        self.partition()
        self.install_system()
        self.place_repository()
        self.install_secrets()
        self.stage_home_manager()
        self.set_passwords()
        self.publish()

        self.reporter.step(f"{self.answers.host} is installed")
        self.reporter.info("Home Manager finishes on the first boot.")


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    if not path.exists():
        return
    os.chown(path, uid, gid)
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            entry = Path(root) / name
            # A dangling symlink or a file removed underneath the walk is not
            # worth failing an installation over.
            with contextlib.suppress(OSError):
                os.lchown(entry, uid, gid)
