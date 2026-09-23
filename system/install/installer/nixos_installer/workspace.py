"""The working checkout the installation is driven from.

The installer never evaluates the repository over `git+file:` or `github:`,
because both of those ignore files that are not committed and the whole point
of the scaffolding step is to create files that are not committed yet. It uses
`path:` instead, which takes the directory as it stands.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import nixsrc
from .model import Catalog
from .proc import CommandError, Reporter, run

DEFAULT_REPO = "https://github.com/gusjengis/nixos.git"


# Nix's flake reference for "this directory, exactly as it is". Anything else
# would silently drop the host files the installer just wrote.
def path_flake(root: Path) -> str:
    return f"path:{root.resolve()}"


@contextlib.contextmanager
def git_credentials(token: str) -> Iterator[dict[str, str]]:
    """Environment that authenticates git, without the token outliving it.

    Supplied through an askpass helper rather than in the remote URL, because
    git writes a URL into `.git/config` and that file is about to be copied
    onto a disk and committed to a public repository. The helper is written to
    a private temporary directory and removed when this context exits, so it
    never lands on the installed system either.
    """

    directory = tempfile.mkdtemp(prefix="nixos-install-credentials.")
    try:
        os.chmod(directory, 0o700)
        helper = Path(directory) / "askpass"
        helper.write_text(
            '#!/bin/sh\ncase "$1" in\n  *Username*) echo gusjengis ;;\n'
            f"  *) printf '%s\\n' {token!r} ;;\nesac\n"
        )
        helper.chmod(0o700)

        env = dict(os.environ)
        env["GIT_ASKPASS"] = str(helper)
        env["GIT_TERMINAL_PROMPT"] = "0"
        yield env
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@dataclass
class Workspace:
    """A checkout plus the host being built inside it."""

    root: Path
    reporter: Reporter

    @property
    def flake(self) -> str:
        return path_flake(self.root)

    def host_dir(self, host: str) -> Path:
        return self.root / "system" / "hosts" / host

    def home_dir(self, host: str) -> Path:
        return self.root / "home" / "hosts" / host

    def known_hosts(self) -> list[str]:
        hosts = self.root / "system" / "hosts"
        if not hosts.is_dir():
            return []
        return sorted(
            entry.name
            for entry in hosts.iterdir()
            if entry.is_dir() and (entry / "meta.nix").exists()
        )

    # -- creation ---------------------------------------------------------

    @classmethod
    def clone(
        cls,
        destination: Path,
        *,
        reporter: Reporter,
        url: str = DEFAULT_REPO,
        branch: str = "main",
        depth: int = 1,
    ) -> Workspace:
        """Shallow-clone the configuration.

        Shallow on purpose: this repository's history is around 1.5 GiB, which
        is minutes of an installation spent fetching commits nobody is going to
        read from a machine that does not exist yet. The clone is deepened
        later only if something needs to be pushed.
        """

        reporter.step(f"Cloning {url} ({branch})")
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        run(
            [
                "git",
                "clone",
                "--depth",
                str(depth),
                "--branch",
                branch,
                "--recurse-submodules",
                "--shallow-submodules",
                url,
                str(destination),
            ],
            reporter=reporter,
            stream=True,
        )
        return cls(root=destination, reporter=reporter)

    @classmethod
    def existing(cls, root: Path, *, reporter: Reporter) -> Workspace:
        """Use a checkout that is already on disk.

        Mainly for testing the installer against a working tree without
        pushing first.
        """

        if not (root / "flake.nix").exists():
            raise FileNotFoundError(f"{root} does not look like the configuration")
        return cls(root=root.resolve(), reporter=reporter)

    # -- scaffolding ------------------------------------------------------

    def scaffold(
        self,
        host: str,
        *,
        facter_report: Path,
        system: str,
        device: str,
        layout: str,
        description: str,
    ) -> bool:
        """Create the minimum that makes `host` evaluable.

        Returns whether the host was newly created. An existing roster entry is
        left alone apart from its disk description, so evaluating it afterwards
        reports the choices that machine is already running and a reinstall can
        offer them back.
        """

        host_dir = self.host_dir(host)
        home_dir = self.home_dir(host)
        is_new = not (host_dir / "meta.nix").exists()

        host_dir.mkdir(parents=True, exist_ok=True)
        home_dir.mkdir(parents=True, exist_ok=True)

        shutil.copyfile(facter_report, host_dir / "facter.json")

        if is_new:
            self.reporter.info(f"Creating a new roster entry for {host}")
            (host_dir / "meta.nix").write_text(
                nixsrc.render_meta(host, system, description)
            )
            # Placeholder: replaced with the real selections once they are
            # known. It has to exist for the host to evaluate at all, and the
            # catalog is what the selections are chosen from.
            (host_dir / "configuration.nix").write_text(
                '{ ... }:\n\n{\n  system.stateVersion = "25.11";\n}\n'
            )
            (home_dir / "default.nix").write_text("{ }\n")
        else:
            self.reporter.info(f"{host} is already on the roster; reusing its settings")

        (host_dir / "disk.nix").write_text(nixsrc.render_disk(host, device, layout))

        # A machine installed by the installer has no generated
        # hardware-configuration.nix. If one is being reinstalled that still
        # carries the file it was first installed with, it has to go: Disko now
        # owns `fileSystems`, and two definitions of the root filesystem is a
        # conflict, not a merge.
        legacy = host_dir / "hardware-configuration.nix"
        if legacy.exists():
            self.reporter.warn(
                f"Removing {legacy.relative_to(self.root)}; Disko now owns this "
                "machine's filesystems"
            )
            legacy.unlink()

        return is_new

    def write_selections(
        self,
        host: str,
        catalog: Catalog,
        selections: dict[str, bool],
        *,
        state_version: str,
    ) -> None:
        """Write the chosen roles into the host's two configuration files."""

        (self.host_dir(host) / "configuration.nix").write_text(
            nixsrc.render_system_configuration(host, catalog, selections, state_version)
        )
        (self.home_dir(host) / "default.nix").write_text(
            nixsrc.render_home_configuration(host, catalog, selections)
        )

    # -- evaluation -------------------------------------------------------

    def eval_json(self, attribute: str) -> object:
        completed = run(
            [
                "nix",
                "eval",
                "--json",
                "--no-write-lock-file",
                f"{self.flake}#{attribute}",
            ],
            reporter=self.reporter,
        )
        return json.loads(completed.stdout)

    def eval_raw(self, attribute: str) -> str:
        completed = run(
            [
                "nix",
                "eval",
                "--raw",
                "--no-write-lock-file",
                f"{self.flake}#{attribute}",
            ],
            reporter=self.reporter,
        )
        return completed.stdout.strip()

    def catalog(self, host: str) -> Catalog:
        """The role list for `host`, evaluated from this checkout."""

        self.reporter.step(f"Evaluating the module catalog for {host}")
        try:
            payload = self.eval_json(f"roleCatalogs.{host}")
        except CommandError as error:
            raise RuntimeError(
                "Could not evaluate the module catalog.\n"
                "This usually means the scaffolded host does not evaluate yet.\n\n"
                + error.output
            ) from error
        catalog = Catalog.from_json(payload)  # type: ignore[arg-type]
        self.reporter.info(
            f"{len(catalog.roles)} modules to choose from, "
            f"{len(catalog.derived_roles)} detected from hardware"
        )
        return catalog

    def state_version(self) -> str:
        """The NixOS release to pin the new machine's `stateVersion` to."""

        return self.eval_raw("installer.stateVersion")

    # -- publication ------------------------------------------------------

    def commit_and_push(
        self,
        host: str,
        *,
        token: str | None,
        push: bool,
        branch: str = "main",
    ) -> None:
        """Track the new machine's files, and publish them.

        A machine whose configuration exists only on its own disk is not
        managed by this repository in any meaningful sense, so this is part of
        installing rather than something to remember afterwards.
        """

        paths = [
            f"system/hosts/{host}",
            f"home/hosts/{host}",
        ]

        self.reporter.step(f"Committing {host}'s configuration")
        run(["git", "add", "--"] + paths, reporter=self.reporter, cwd=str(self.root))

        status = run(
            ["git", "status", "--porcelain", "--"] + paths,
            reporter=self.reporter,
            cwd=str(self.root),
        )
        if not status.stdout.strip():
            self.reporter.info("Nothing to commit")
            return

        run(
            [
                "git",
                "-c",
                "user.name=gusjengis",
                "-c",
                "user.email=anthony.j.green@outlook.com",
                "commit",
                "--message",
                f"feat(hosts): add {host}",
                "--",
            ]
            + paths,
            reporter=self.reporter,
            cwd=str(self.root),
            stream=True,
        )

        if not push:
            self.reporter.info("Not pushing (--push=false). Push it yourself later.")
            return

        if not token:
            self.reporter.warn("No GitHub token, so the commit stays local.")
            return

        self.reporter.step("Pushing to origin")
        with git_credentials(token) as env:
            try:
                self._push(env, branch)
            except CommandError as error:
                # Never fatal. The machine is installed and working by now; an
                # unpushed commit is an inconvenience, not a failed install.
                self.reporter.warn(
                    "Could not push the new machine's configuration. It is "
                    f"committed locally in /etc/nixos.\n{error.output}"
                )

    def _push(self, env: dict[str, str], branch: str) -> None:
        """Push, deepening the shallow clone only if that is what went wrong.

        Pushing from a `--depth 1` clone works as long as the remote tip is
        still the commit it was cloned from. Fetching the history first would
        be simpler and would also pull roughly 1.5 GiB onto a machine that has
        existed for ten minutes, so it is done only after a push is actually
        rejected.
        """

        try:
            run(
                ["git", "push", "origin", f"HEAD:{branch}"],
                reporter=self.reporter,
                cwd=str(self.root),
                env=env,
                stream=True,
            )
            return
        except CommandError:
            self.reporter.info("Push rejected; the branch has moved. Rebasing.")

        run(
            ["git", "fetch", "--unshallow", "origin", branch],
            reporter=self.reporter,
            cwd=str(self.root),
            env=env,
            check=False,
            stream=True,
        )
        run(
            ["git", "rebase", f"origin/{branch}"],
            reporter=self.reporter,
            cwd=str(self.root),
            env=env,
            stream=True,
        )
        run(
            ["git", "push", "origin", f"HEAD:{branch}"],
            reporter=self.reporter,
            cwd=str(self.root),
            env=env,
            stream=True,
        )
