"""Entry point.

The order matters and is worth stating plainly, because it is the answer to
"why does it evaluate before it asks anything":

  1. Read the command line far enough to find the configuration.
  2. Clone it, probe the hardware, and list the disks.
  3. Scaffold the host being installed, so that it *can* be evaluated.
  4. Evaluate it, which produces the module list and the defaults.
  5. Resolve every decision, from flags or from the interface.
  6. Install.

Step 4 is why the module list is trustworthy: it is the configuration's own
answer to "what can be turned on and what is it set to", not a guess made by
reading source text.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from . import cli, probe
from .model import AnswerError, Answers, Catalog, missing_answers, validate_hostname
from .pipeline import Installer, PreflightError
from .proc import CommandError, Reporter, ensure_experimental_features
from .workspace import Workspace

# Used while the real host name is still unknown: the catalog has to be
# evaluated against *some* host, and for a machine that is not on the roster
# yet the defaults do not depend on which name it ends up with.
PROVISIONAL_HOST = "new-machine"

# A placeholder that is never written to a disk. Disko needs a device to
# evaluate, and the disk is not chosen until after the catalog exists.
PROVISIONAL_DEVICE = "/dev/null"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Every `nix`, `nixos-install`, and `disko` call this program makes is a
    # fresh process; none of them inherit flags typed on the `nix run` that
    # started the installer. Setting this before anything is cloned or
    # evaluated is what makes every one of those calls work unattended.
    ensure_experimental_features(os.environ)

    # Answered before anything is cloned or probed, so that asking what the
    # installer does never partitions, downloads, or requires root.
    if cli.wants_help(argv):
        cli.print_base_help()
        return 0

    preliminary = cli.parse_known(argv)
    reporter = Reporter(verbose=preliminary.verbose)

    try:
        return _run(argv, preliminary, reporter)
    except KeyboardInterrupt:
        reporter.warn("Interrupted. Nothing further was changed.")
        return 130
    except (AnswerError, PreflightError) as error:
        reporter.warn(str(error))
        return 2
    except CommandError as error:
        reporter.warn(str(error))
        if error.output:
            reporter.emit(error.output.rstrip())
        return 1
    except RuntimeError as error:
        reporter.warn(str(error))
        return 1


def _run(argv: list[str], preliminary, reporter: Reporter) -> int:
    workspace = _prepare_workspace(preliminary, reporter)
    known_hosts = workspace.known_hosts()

    system = _system_double()
    facter_path = Path(preliminary.work_dir).parent / "facter.json"
    report = _hardware_report(preliminary, facter_path, system, reporter)

    # The catalog is evaluated for the host being installed. Naming an existing
    # roster host therefore produces that machine's current module selections
    # rather than generic defaults, which is what makes reinstalling one offer
    # its own settings back without any special case.
    catalog_host = (
        preliminary.host
        if preliminary.host and preliminary.host in known_hosts
        else PROVISIONAL_HOST
    )

    workspace.scaffold(
        catalog_host,
        facter_report=facter_path,
        system=system,
        device=PROVISIONAL_DEVICE,
        layout=preliminary.layout,
        description=preliminary.description,
    )
    catalog = workspace.catalog(catalog_host)

    parser = cli.catalog_parser(catalog)
    namespace = parser.parse_args(argv)

    if namespace.list_modules:
        print(cli.format_module_list(catalog))
        return 0

    answers = cli.answers_from(namespace, catalog)

    disks = probe.list_disks(
        reporter=reporter, include_removable=namespace.show_removable
    )

    if namespace.yes:
        missing = missing_answers(answers)
        if missing:
            reporter.warn(
                "--yes was given, so nothing can be asked for, but these are "
                "missing: " + ", ".join(missing)
            )
            return 2
        validate_hostname(answers.host)
    else:
        answers = _ask(answers, catalog, disks, known_hosts, report, reporter)
        if answers is None:
            reporter.warn("Cancelled. Nothing was changed.")
            return 130

    # The interface may have named a host that is not the one the catalog was
    # evaluated for. Re-evaluate so the defaults, and the files written from
    # them, belong to the machine actually being installed.
    catalog = _retarget(
        workspace,
        answers,
        catalog,
        catalog_host,
        facter_path=facter_path,
        system=system,
        reporter=reporter,
    )

    selections = answers.with_defaults(catalog)
    state_version = workspace.state_version()
    workspace.write_selections(
        answers.host, catalog, selections, state_version=state_version
    )

    installer = Installer(
        workspace=workspace,
        answers=answers,
        catalog=catalog,
        reporter=reporter,
        facter_report=report,
        prebuild_home=namespace.prebuild_home,
    )

    reporter.step("Ready to install")
    for line in installer.summary().splitlines():
        reporter.info(line)

    if namespace.dry_run:
        reporter.step("Dry run; no disk was touched")
        _show_generated(workspace, answers.host, reporter)
        return 0

    if not namespace.yes and not _confirm_on_terminal(answers, reporter):
        reporter.warn("Cancelled. Nothing was changed.")
        return 130

    installer.run_all()
    return 0


def _hardware_report(
    preliminary, facter_path: Path, system: str, reporter: Reporter
) -> dict:
    """Get a Facter report, probing only when an installation needs one.

    Probing requires root. Asking the installer a question should not, so the
    read-only modes fall back to a report describing nothing rather than
    refusing to answer.
    """

    if preliminary.list_modules:
        facter_path.write_text(json.dumps(probe.synthetic_report(system)))
        return probe.synthetic_report(system)

    if preliminary.dry_run and facter_path.exists():
        reporter.info(f"Reusing the hardware report at {facter_path}")
        return probe.probe_existing(facter_path)

    if preliminary.dry_run and os.geteuid() != 0:
        reporter.warn(
            "Not running as root, so hardware was not probed. This dry run "
            "shows module defaults as if nothing were detected."
        )
        facter_path.write_text(json.dumps(probe.synthetic_report(system)))
        return probe.synthetic_report(system)

    return probe.probe_hardware(facter_path, reporter=reporter)


def _prepare_workspace(preliminary, reporter: Reporter) -> Workspace:
    if preliminary.source:
        reporter.step(f"Using the checkout at {preliminary.source}")
        source = Path(preliminary.source).resolve()
        destination = Path(preliminary.work_dir)
        if destination.exists():
            shutil.rmtree(destination)
        # Copied rather than used in place: the installer writes host files,
        # and doing that to someone's working tree is not its business.
        shutil.copytree(source, destination, symlinks=True)
        return Workspace.existing(destination, reporter=reporter)

    return Workspace.clone(
        Path(preliminary.work_dir),
        reporter=reporter,
        url=preliminary.repo,
        branch=preliminary.branch,
    )


def _retarget(
    workspace: Workspace,
    answers: Answers,
    catalog: Catalog,
    catalog_host: str,
    *,
    facter_path: Path,
    system: str,
    reporter: Reporter,
) -> Catalog:
    """Make the catalog belong to the host that was actually chosen."""

    assert answers.host

    if answers.host == catalog_host:
        return catalog

    if catalog_host == PROVISIONAL_HOST:
        _discard_provisional(workspace, reporter)

    workspace.scaffold(
        answers.host,
        facter_report=facter_path,
        system=system,
        device=answers.disk or PROVISIONAL_DEVICE,
        layout=answers.layout,
        description=answers.description,
    )
    return workspace.catalog(answers.host)


def _discard_provisional(workspace: Workspace, reporter: Reporter) -> None:
    """Remove the scaffold used only to get a catalog.

    It must not survive into the installed checkout: every directory under
    system/hosts that has a meta.nix is a machine on the roster.
    """

    for path in (
        workspace.host_dir(PROVISIONAL_HOST),
        workspace.home_dir(PROVISIONAL_HOST),
    ):
        if path.exists():
            shutil.rmtree(path)
    reporter.info(f"Discarded the provisional {PROVISIONAL_HOST} scaffold")


def _ask(
    answers: Answers,
    catalog: Catalog,
    disks,
    known_hosts: list[str],
    report: dict,
    reporter: Reporter,
) -> Answers | None:
    from .tui import run_tui

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AnswerError(
            "There is no terminal to ask questions on. Supply every answer on "
            "the command line and add --yes."
        )

    reporter.step("Opening the installer")
    result = run_tui(
        catalog,
        disks,
        answers,
        known_hosts,
        probe.is_portable(report),
    )
    if result.cancelled or result.answers is None:
        return None
    return result.answers


def _confirm_on_terminal(answers: Answers, reporter: Reporter) -> bool:
    """Confirm destruction once more, for runs that skipped the interface.

    The interface has its own confirmation; this covers the case where every
    answer came from flags but --yes was not given, which is the shape a
    half-scripted run takes.
    """

    reporter.warn(f"About to erase {answers.disk} completely.")
    try:
        reply = input(f"Type the host name ({answers.host}) to continue: ")
    except EOFError:
        return False
    return reply.strip() == answers.host


def _show_generated(workspace: Workspace, host: str, reporter: Reporter) -> None:
    for relative in (
        f"system/hosts/{host}/meta.nix",
        f"system/hosts/{host}/disk.nix",
        f"system/hosts/{host}/configuration.nix",
        f"home/hosts/{host}/default.nix",
    ):
        path = workspace.root / relative
        if not path.exists():
            continue
        reporter.step(relative)
        for line in path.read_text().splitlines():
            reporter.emit(f"    {line}")


def _system_double() -> str:
    machine = os.uname().machine
    if machine in ("x86_64", "amd64"):
        return "x86_64-linux"
    if machine in ("aarch64", "arm64"):
        return "aarch64-linux"
    raise AnswerError(f"unsupported architecture: {machine}")


if __name__ == "__main__":
    raise SystemExit(main())
