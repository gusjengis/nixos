"""Command-line surface.

Every decision is a flag, so a batch of machines can be installed without the
interface ever opening. The module flags are not written out here: they are
generated from the catalog, which is generated from the option trees, so
`--help` lists exactly the modules this configuration actually has and shows
the default each one would take.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from .model import Answers, Catalog

TRUE_WORDS = {"true", "yes", "on", "1", "y"}
FALSE_WORDS = {"false", "no", "off", "0", "n"}

# Set by the package wrapper, so the installer defaults to the repository it
# was itself built from rather than to a literal duplicated in two languages.
DEFAULT_REPO = os.environ.get(
    "NIXOS_INSTALL_REPO", "https://github.com/gusjengis/nixos.git"
)


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in TRUE_WORDS:
        return True
    if lowered in FALSE_WORDS:
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def base_parser(*, add_help: bool = True) -> argparse.ArgumentParser:
    """Flags that do not depend on the catalog.

    Parsed first, because finding out what the module flags even are requires
    a checkout, which requires these.
    """

    parser = argparse.ArgumentParser(
        prog="install",
        add_help=add_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Install this NixOS configuration onto this machine.\n\n"
            "Run with no arguments for an interactive installation. Supply\n"
            "every required answer plus --yes to run without any interface,\n"
            "which is what installing several machines in a row wants."
        ),
        epilog=(
            "Modules:\n"
            "  Every module in the configuration also has a flag, of the form\n"
            "  --<module>=true|false. They are not listed here because they are\n"
            "  read out of the configuration rather than written down in the\n"
            "  installer, which means listing them needs a checkout. Run\n"
            "  --list-modules to see them, with the default each one takes.\n"
            "\n"
            "Examples:\n"
            "  install\n"
            "      Interactive. Every decision is a tab.\n\n"
            "  install --host t490 --disk /dev/nvme0n1 \\\n"
            "          --password 'hunter2' --github-token ghp_xxx --yes\n"
            "      Non-interactive, taking the configuration's own defaults\n"
            "      for every module.\n\n"
            "  install --host shed --disk /dev/sda --password 'hunter2' \\\n"
            "          --github-token ghp_xxx --group-desktop=false --yes\n"
            "      A headless machine: the whole desktop category off.\n\n"
            "  install --list-modules\n"
            "      Show every module flag, its default, and its category."
        ),
    )

    machine = parser.add_argument_group("machine")
    machine.add_argument(
        "--host",
        metavar="NAME",
        help=(
            "Roster key for this machine. Also becomes its NixOS hostname and "
            "its Tailscale node name. An existing roster key reinstalls that "
            "machine and offers back the modules it currently runs."
        ),
    )
    machine.add_argument(
        "--description",
        default="",
        metavar="TEXT",
        help="One line about the machine, recorded in its roster entry.",
    )

    disk = parser.add_argument_group("disk")
    disk.add_argument(
        "--disk",
        metavar="DEVICE",
        help="Whole disk to install onto. Everything on it is destroyed.",
    )
    disk.add_argument(
        "--layout",
        default="plain",
        metavar="NAME",
        help=(
            "Partition layout. 'plain' is GPT, an EFI system partition, and "
            "ext4 for the rest, which is what the fleet runs. (default: plain)"
        ),
    )
    disk.add_argument(
        "--show-removable",
        action="store_true",
        help="Include removable disks when choosing. Off by default so the "
        "installer's own USB stick is not an option.",
    )

    accounts = parser.add_argument_group("accounts")
    accounts.add_argument(
        "--password",
        metavar="TEXT",
        help="Password for gusjengis. Also used for root unless "
        "--root-password is given.",
    )
    accounts.add_argument(
        "--root-password",
        metavar="TEXT",
        help="Separate root password. Defaults to the same as --password.",
    )

    secrets = parser.add_argument_group("secrets")
    secrets.add_argument(
        "--github-token",
        metavar="TOKEN",
        help=(
            "GitHub personal access token with `repo` scope. Used to clone the "
            "private secrets checkout, which carries the SSH keys, the SMB "
            "credentials and the Tailscale auth key, and to push this "
            "machine's new configuration."
        ),
    )
    secrets.add_argument(
        "--push",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="BOOL",
        help="Commit and push the new machine's files when done. (default: true)",
    )

    source = parser.add_argument_group("source")
    source.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        metavar="URL",
        help=f"Configuration repository to install from. (default: {DEFAULT_REPO})",
    )
    source.add_argument(
        "--branch",
        default="main",
        metavar="NAME",
        help="Branch to install from. (default: main)",
    )
    source.add_argument(
        "--source",
        metavar="PATH",
        help=(
            "Install from a checkout that is already on disk instead of "
            "cloning. For testing changes to the installer itself."
        ),
    )
    source.add_argument(
        "--work-dir",
        default="/tmp/nixos-install",
        metavar="PATH",
        help="Where to put the working checkout. (default: /tmp/nixos-install)",
    )

    behaviour = parser.add_argument_group("behaviour")
    behaviour.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Do not open the interface and do not ask for confirmation before "
            "destroying the disk. Requires --host, --disk, --password and "
            "--github-token; the installation refuses to start, naming what is "
            "missing, rather than stopping halfway to ask."
        ),
    )
    behaviour.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Resolve every decision, write the host's files, and show them, "
            "without touching any disk."
        ),
    )
    behaviour.add_argument(
        "--prebuild-home",
        type=parse_bool,
        nargs="?",
        const=True,
        default=True,
        metavar="BOOL",
        help=(
            "Build the Home Manager closure during installation so the first "
            "boot only has to activate it. (default: true)"
        ),
    )
    behaviour.add_argument(
        "--list-modules",
        action="store_true",
        help="Print every module, its flag, category and default, then exit.",
    )
    behaviour.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Echo every command the installer runs.",
    )

    return parser


def catalog_parser(catalog: Catalog) -> argparse.ArgumentParser:
    """The full parser, including one flag per module and per category.

    Built from the catalog rather than declared, which is what keeps `--help`
    honest when a module is added or renamed.
    """

    parser = base_parser()

    groups = parser.add_argument_group(
        "categories",
        description=(
            "Set every module in a category at once. Applied before the "
            "individual module flags, so one module can still differ from its "
            "category."
        ),
    )
    for category, roles in catalog.grouped():
        members = ", ".join(role.id for role in roles)
        groups.add_argument(
            f"--group-{category.id}",
            type=parse_bool,
            nargs="?",
            const=True,
            metavar="BOOL",
            dest=f"group_{category.id.replace('-', '_')}",
            help=f"{category.description} ({members})",
        )

    modules = parser.add_argument_group(
        "modules",
        description=(
            "Each module defaults to what this configuration already defaults "
            "to; an omitted flag is genuinely unspecified rather than forced "
            "off. Values: true or false."
        ),
    )
    for category, roles in catalog.grouped():
        for role in roles:
            default = "on" if role.value else "off"
            modules.add_argument(
                role.flag,
                type=parse_bool,
                nargs="?",
                const=True,
                metavar="BOOL",
                dest=f"module_{role.id.replace('-', '_')}",
                help=f"[{category.label}, default {default}] {role.summary}",
            )

    return parser


def answers_from(namespace: argparse.Namespace, catalog: Catalog) -> Answers:
    """Collect parsed flags into the decision set.

    Only flags that were actually given become entries; anything untouched is
    left out so the catalog's default applies later.
    """

    modules: dict[str, bool] = {}
    for role in catalog.roles:
        value = getattr(namespace, f"module_{role.id.replace('-', '_')}", None)
        if value is not None:
            modules[role.id] = value

    groups: dict[str, bool] = {}
    for category in catalog.categories:
        value = getattr(namespace, f"group_{category.id.replace('-', '_')}", None)
        if value is not None:
            groups[category.id] = value

    return Answers(
        host=namespace.host,
        disk=namespace.disk,
        layout=namespace.layout,
        modules=modules,
        groups=groups,
        user_password=namespace.password,
        root_password=namespace.root_password,
        same_password=namespace.root_password is None,
        github_token=namespace.github_token,
        description=namespace.description,
        push=namespace.push,
        assume_yes=namespace.yes,
    )


def format_module_list(catalog: Catalog) -> str:
    """The `--list-modules` table."""

    lines = [f"Modules available for {catalog.host} ({catalog.system}):", ""]
    width = max((len(role.id) for role in catalog.roles), default=10) + 2

    for category, roles in catalog.grouped():
        lines.append(f"{category.label}  (--group-{category.id}=BOOL)")
        for role in roles:
            default = "true " if role.value else "false"
            lines.append(
                f"  --{role.id.ljust(width)} {default}  {role.scope:<6} {role.summary}"
            )
        lines.append("")

    if catalog.derived_roles:
        lines.append("Detected from hardware, never asked:")
        for role in catalog.derived_roles:
            value = "true" if role.value else "false"
            lines.append(f"  {role.name.ljust(width + 2)} {value}")
        lines.append("")

    return "\n".join(lines)


def wants_help(argv: Sequence[str]) -> bool:
    return any(argument in ("-h", "--help") for argument in argv)


def print_base_help() -> None:
    """Help without a checkout.

    `--help` has to work instantly, offline, and before anything has been
    cloned, so it cannot include the module flags: those come from evaluating
    the configuration. The epilog says so and points at --list-modules.
    """

    base_parser().print_help()


def parse_known(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """First pass: enough to find the checkout and build the real parser."""

    parser = base_parser(add_help=False)
    namespace, _ = parser.parse_known_args(argv)
    return namespace
