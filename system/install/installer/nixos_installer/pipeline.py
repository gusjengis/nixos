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
import shlex
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
HOME_GENERATION = f"/{MARKER_DIR}/home-manager-generation"
PENDING_HOME = f"/{MARKER_DIR}/pending-home-manager"
REPO_SYNC_ATTEMPTS = 3


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
        """Build the Home Manager generation into the installed system's store."""

        host = self.answers.host
        assert host

        marker_dir = self.mountpoint / MARKER_DIR
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "pending-home-manager").write_text(f"{host}\n")

        self.reporter.step("Building the Home Manager closure into the new system")
        installed = Workspace(
            root=self.mountpoint / "etc" / "nixos", reporter=self.reporter
        )
        run(
            [
                "nix",
                "build",
                "--store",
                str(self.mountpoint),
                "--no-write-lock-file",
                "--out-link",
                str(self.mountpoint) + HOME_GENERATION,
                f"{installed.flake}#homeConfigurations.{host}.activationPackage",
            ],
            reporter=self.reporter,
            stream=True,
        )

    def activate_home_manager(self) -> None:
        """Activate the staged generation as the installed user before reboot."""

        generation = self.mountpoint / HOME_GENERATION.lstrip("/")
        if not generation.exists() and not generation.is_symlink():
            raise RuntimeError("The staged Home Manager generation is missing.")

        self.reporter.step("Activating Home Manager in the installed system")
        self._run_as_target_user(f"exec {HOME_GENERATION}/activate")

        # From here onward first boot does not need the recovery service. A
        # failed activation leaves this marker intact so manually rebooting an
        # interrupted installation still gets one more chance to recover.
        (self.mountpoint / PENDING_HOME.lstrip("/")).unlink(missing_ok=True)

    def sync_repositories(self) -> None:
        """Populate user repositories before reboot, retrying transient failures."""

        if not self.answers.github_token:
            self.reporter.warn(
                "No GitHub token was given, so repositories were not synchronized."
            )
            return

        self.reporter.step("Synchronizing user repositories")
        sync = f"{HOME_GENERATION}/home-path/bin/sync-repos"
        session_vars = "/home/gusjengis/.nix-profile/etc/profile.d/hm-session-vars.sh"
        command = f"""
if [ -r {session_vars} ]; then
  . {session_vars}
fi
if [ -n "${{NIXOS_INSTALL_TOKEN_FILE:-}}" ] && [ -r "$NIXOS_INSTALL_TOKEN_FILE" ]; then
  GH_TOKEN="$(<"$NIXOS_INSTALL_TOKEN_FILE")"
  export GH_TOKEN
fi
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15'
export SYNC_REPOS_FAIL_ON_ERROR=1
attempt=1
while [ "$attempt" -le {REPO_SYNC_ATTEMPTS} ]; do
  if {sync}; then
    exit 0
  fi
  echo "repository sync attempt $attempt of {REPO_SYNC_ATTEMPTS} failed" >&2
  attempt=$((attempt + 1))
  [ "$attempt" -gt {REPO_SYNC_ATTEMPTS} ] || sleep 5
done
exit 1
""".strip()

        try:
            self._run_as_target_user(command, github_token=self.answers.github_token)
        except CommandError as error:
            self.reporter.warn(
                "One or more repositories could not be synchronized after "
                f"{REPO_SYNC_ATTEMPTS} attempts. The installed desktop is ready, "
                "and the normal update service will retry after boot.\n" + error.output
            )

    def record_deployed_revision(self) -> None:
        """Tell the first user-session update that this revision is deployed."""

        installed = self.mountpoint / "etc" / "nixos"
        revision = run(
            ["git", "-c", f"safe.directory={installed}", "rev-parse", "HEAD"],
            reporter=self.reporter,
            cwd=str(installed),
        ).stdout.strip()
        state = self.mountpoint / "home" / TARGET_USER / ".local/state/home-manager"
        state.mkdir(parents=True, exist_ok=True)
        (state / "deployed-revision").write_text(f"{revision}\n")
        uid, gid = self._target_user_ids()
        _chown_tree(state, uid, gid)

        generation = self.mountpoint / HOME_GENERATION.lstrip("/")
        generation.unlink(missing_ok=True)

    def _run_as_target_user(
        self, command: str, *, github_token: str | None = None
    ) -> None:
        """Run one user command against the target store through a temporary daemon."""

        user_command = shlex.quote(command)
        script = f"""
set -eu
system=/nix/var/nix/profiles/system
user={TARGET_USER}
uid="$($system/sw/bin/id -u "$user")"
runtime=/run/user/$uid
socket=/nix/var/nix/daemon-socket/socket
token_file=
daemon=

cleanup() {{
  if [ -n "$daemon" ]; then
    kill "$daemon" 2>/dev/null || true
    wait "$daemon" 2>/dev/null || true
  fi
  $system/sw/bin/rm -f "$socket"
  $system/sw/bin/rm -rf "$runtime"
}}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

$system/sw/bin/install -d -m 700 -o "$user" -g users "$runtime"
$system/sw/bin/install -d -m 755 /nix/var/nix/daemon-socket
$system/sw/bin/install -d -m 700 -o "$user" -g users \
  /home/$user/.local/state/nix/profiles \
  /home/$user/.local/state/home-manager
if [ -n "${{NIXOS_INSTALL_GITHUB_TOKEN:-}}" ]; then
  token_file="$runtime/github-token"
  (umask 077; printf '%s' "$NIXOS_INSTALL_GITHUB_TOKEN" >"$token_file")
  $system/sw/bin/chown "$user":users "$token_file"
fi
$system/sw/bin/rm -f "$socket"

$system/sw/bin/env -i \
  HOME=/root USER=root LOGNAME=root \
  PATH=$system/sw/bin:/nix/var/nix/profiles/default/bin \
  NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
  SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
  LOCALE_ARCHIVE=$system/sw/lib/locale/locale-archive \
  TZDIR=/etc/zoneinfo \
  $system/sw/bin/nix-daemon --daemon \
  >/tmp/nixos-install-nix-daemon.log 2>&1 &
daemon=$!

ready=0
for _ in $($system/sw/bin/seq 1 100); do
  if [ -S "$socket" ]; then
    ready=1
    break
  fi
  $system/sw/bin/sleep 0.1
done
if [ "$ready" -ne 1 ]; then
  echo "target nix-daemon did not become ready" >&2
  $system/sw/bin/cat /tmp/nixos-install-nix-daemon.log >&2 || true
  exit 1
fi

$system/sw/bin/runuser -u "$user" -- \
  $system/sw/bin/env -i \
    HOME=/home/$user USER=$user LOGNAME=$user SHELL=$system/sw/bin/bash \
    PATH=/home/$user/.nix-profile/bin:/etc/profiles/per-user/$user/bin:$system/sw/bin \
    NIX_REMOTE=daemon \
    NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt \
    LOCALE_ARCHIVE=$system/sw/lib/locale/locale-archive \
    TZDIR=/etc/zoneinfo LANG=en_US.UTF-8 \
    XDG_RUNTIME_DIR="$runtime" NIXOS_INSTALL_TOKEN_FILE="$token_file" \
    $system/sw/bin/bash -c {user_command}
""".strip()

        env = dict(os.environ)
        if github_token:
            env["NIXOS_INSTALL_GITHUB_TOKEN"] = github_token
        run(
            [
                "nixos-enter",
                "--root",
                str(self.mountpoint),
                "--command",
                script,
            ],
            reporter=self.reporter,
            env=env,
            secrets=[github_token] if github_token else (),
            stream=True,
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
        self.set_passwords()
        self.publish()
        self.stage_home_manager()
        self.activate_home_manager()
        self.sync_repositories()
        self.record_deployed_revision()

        self.reporter.step(f"{self.answers.host} is installed")
        self.reporter.info("NixOS, Home Manager, and user repositories are ready.")


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
