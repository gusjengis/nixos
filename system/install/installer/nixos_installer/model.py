"""The decisions an installation is made of.

The installer is a list of decisions with a default, a flag, and a place in the
interface. Keeping them in one dataclass rather than threading arguments
through the pipeline is what lets the interactive and non-interactive paths be
the same code: the interface produces one of these, the argument parser
produces one of these, and the pipeline cannot tell which it was given.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

# Linux hostnames, restricted further to what is also a usable Nix attribute
# name and a usable Tailscale node name: the roster key is all three at once.
HOSTNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

STAGES = ("host", "disk", "modules", "accounts", "secrets", "review")


class AnswerError(ValueError):
    """An answer cannot be used, with a message meant for the person installing."""


@dataclass(frozen=True)
class Role:
    """One installable module, as discovered from the evaluated option tree."""

    id: str
    name: str
    scope: str
    value: bool
    derived: bool
    category: str
    summary: str
    declared_in: tuple[str, ...] = ()

    @property
    def flag(self) -> str:
        return f"--{self.id}"

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> Role:
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            scope=str(raw["scope"]),
            value=bool(raw["value"]),
            derived=bool(raw["derived"]),
            category=str(raw["category"]),
            summary=str(raw["summary"]),
            declared_in=tuple(str(path) for path in raw.get("declaredIn", ())),
        )


@dataclass(frozen=True)
class Category:
    """A group of roles, shown as a toggleable header with the roles nested."""

    id: str
    label: str
    description: str

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> Category:
        return cls(
            id=str(raw["id"]),
            label=str(raw["label"]),
            description=str(raw["description"]),
        )


@dataclass(frozen=True)
class Catalog:
    """Everything the installer knows about what can be turned on.

    Derived entirely from the evaluated NixOS and Home Manager option trees;
    see system/install/catalog.nix. Nothing in here is written by hand, which
    is why it cannot describe a module that no longer exists.
    """

    host: str
    system: str
    roles: tuple[Role, ...]
    derived_roles: tuple[Role, ...]
    categories: tuple[Category, ...]

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> Catalog:
        return cls(
            host=str(raw["host"]),
            system=str(raw["system"]),
            roles=tuple(Role.from_json(role) for role in raw["roles"]),  # type: ignore[union-attr]
            derived_roles=tuple(
                Role.from_json(role)
                for role in raw["derivedRoles"]  # type: ignore[union-attr]
            ),
            categories=tuple(
                Category.from_json(category)
                for category in raw["categories"]  # type: ignore[union-attr]
            ),
        )

    @property
    def defaults(self) -> dict[str, bool]:
        return {role.id: role.value for role in self.roles}

    def by_id(self, role_id: str) -> Role | None:
        for role in self.roles:
            if role.id == role_id:
                return role
        return None

    def roles_in(self, category_id: str) -> tuple[Role, ...]:
        return tuple(role for role in self.roles if role.category == category_id)

    def grouped(self) -> list[tuple[Category, tuple[Role, ...]]]:
        """Categories with their roles, in display order, skipping empty ones."""

        groups = []
        for category in self.categories:
            roles = self.roles_in(category.id)
            if roles:
                groups.append((category, roles))
        return groups


@dataclass(frozen=True)
class Disk:
    """A block device the installation could be written to."""

    path: str
    size_bytes: int
    model: str
    transport: str
    removable: bool
    partitions: tuple[str, ...] = ()
    mounted: bool = False

    @property
    def size_human(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "K", "M", "G", "T", "P"):
            if size < 1024 or unit == "P":
                if unit == "B":
                    return f"{int(size)}B"
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}P"

    @property
    def label(self) -> str:
        bits = [self.path, self.size_human]
        if self.model:
            bits.append(self.model)
        if self.transport:
            bits.append(self.transport)
        if self.removable:
            bits.append("removable")
        return "  ".join(bits)


@dataclass
class Answers:
    """Every decision, resolved.

    `modules` holds only the roles that were answered explicitly. A role absent
    from it takes the catalog's default, so an unspecified role is genuinely
    unspecified rather than defaulted twice in two different places.
    """

    host: str | None = None
    disk: str | None = None
    layout: str = "plain"
    modules: dict[str, bool] = field(default_factory=dict)
    groups: dict[str, bool] = field(default_factory=dict)
    user_password: str | None = None
    root_password: str | None = None
    same_password: bool = True
    github_token: str | None = None
    description: str = ""
    push: bool = True
    assume_yes: bool = False

    def with_defaults(self, catalog: Catalog) -> dict[str, bool]:
        """Final role selections.

        Applied in the order defaults, then group toggles, then individual
        roles, so a single role can always dissent from the group it is in.
        """

        selections = catalog.defaults
        for group_id, enabled in self.groups.items():
            for role in catalog.roles_in(group_id):
                selections[role.id] = enabled
        for role_id, enabled in self.modules.items():
            selections[role_id] = enabled
        return selections

    def effective_root_password(self) -> str | None:
        if self.same_password:
            return self.user_password
        return self.root_password

    def secrets(self) -> list[str]:
        """Values that must never be printed."""

        values = [self.user_password, self.root_password, self.github_token]
        return [value for value in values if value]

    def merged(self, **changes: object) -> Answers:
        return replace(self, **changes)  # type: ignore[arg-type]


def validate_hostname(host: str | None) -> str:
    if not host:
        raise AnswerError("a host name is required")
    if not HOSTNAME_PATTERN.match(host):
        raise AnswerError(
            f"{host!r} is not usable as a host name. "
            "It is the roster key, the NixOS hostname and the Tailscale node "
            "name at once, so it must be lowercase letters, digits and "
            "dashes, starting with a letter or digit."
        )
    return host


def missing_answers(answers: Answers, *, known_hosts: Iterable[str] = ()) -> list[str]:
    """What still has to be decided before an installation can start.

    Used to refuse a non-interactive run early, naming every missing answer at
    once rather than failing on the first one after the disk has been wiped.
    """

    del known_hosts

    missing = []
    if not answers.host:
        missing.append("--host")
    if not answers.disk:
        missing.append("--disk")
    if not answers.user_password:
        missing.append("--password")
    if not answers.same_password and not answers.root_password:
        missing.append("--root-password")
    if not answers.github_token:
        missing.append("--github-token")
    return missing
