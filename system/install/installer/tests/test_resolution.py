"""Tests for the parts that decide what gets installed.

Deliberately limited to the pure logic: flag parsing, precedence between
category and module flags, the refusal to start a non-interactive run with
answers missing, and the Nix that gets generated. Those are the parts where a
mistake is silent. Partitioning and installation are not unit-testable in any
useful sense and are covered by --dry-run instead.
"""

from __future__ import annotations

import argparse

import pytest

from nixos_installer import cli, nixsrc
from nixos_installer.model import (
    AnswerError,
    Answers,
    Catalog,
    missing_answers,
    validate_hostname,
)

CATALOG_JSON = {
    "host": "new-machine",
    "system": "x86_64-linux",
    "description": "",
    "roles": [
        {
            "id": "hyprland",
            "name": "hyprland.enable",
            "scope": "system",
            "value": True,
            "derived": False,
            "category": "desktop",
            "summary": "The Hyprland compositor.",
            "declaredIn": ["system/modules/desktop_env/hyprland.nix"],
        },
        {
            "id": "desktop",
            "name": "desktopEnv.enable",
            "scope": "home",
            "value": True,
            "derived": False,
            "category": "desktop",
            "summary": "Desktop applications.",
            "declaredIn": ["home"],
        },
        {
            "id": "gaming",
            "name": "gaming.enable",
            "scope": "home",
            "value": False,
            "derived": False,
            "category": "gaming",
            "summary": "Steam.",
            "declaredIn": ["home/features/gaming"],
        },
        {
            "id": "tailscale",
            "name": "tailscale.enable",
            "scope": "system",
            "value": True,
            "derived": False,
            "category": "core",
            "summary": "Join the tailnet.",
            "declaredIn": ["system/modules/software/tailscale.nix"],
        },
    ],
    "derivedRoles": [
        {
            "id": "nvidia",
            "name": "nvidia.enable",
            "scope": "system",
            "value": False,
            "derived": True,
            "category": "other",
            "summary": "NVIDIA drivers.",
            "declaredIn": ["system/modules/hardware/gpu_drivers.nix"],
        }
    ],
    "categories": [
        {"id": "core", "label": "Core", "description": "Fleet membership."},
        {"id": "desktop", "label": "Desktop", "description": "Graphical session."},
        {"id": "gaming", "label": "Gaming", "description": "Steam and friends."},
    ],
}


@pytest.fixture
def catalog() -> Catalog:
    return Catalog.from_json(CATALOG_JSON)


def parse(catalog: Catalog, argv: list[str]) -> Answers:
    namespace = cli.catalog_parser(catalog).parse_args(argv)
    return cli.answers_from(namespace, catalog)


class TestDefaults:
    def test_nothing_specified_takes_configuration_defaults(self, catalog):
        answers = parse(catalog, [])
        assert answers.with_defaults(catalog) == {
            "hyprland": True,
            "desktop": True,
            "gaming": False,
            "tailscale": True,
        }

    def test_unspecified_module_is_absent_rather_than_false(self, catalog):
        answers = parse(catalog, ["--gaming=true"])
        assert answers.modules == {"gaming": True}

    def test_derived_roles_are_not_flags(self, catalog):
        with pytest.raises(SystemExit):
            cli.catalog_parser(catalog).parse_args(["--nvidia=true"])


class TestPrecedence:
    def test_group_flag_sets_every_member(self, catalog):
        answers = parse(catalog, ["--group-desktop=false"])
        selections = answers.with_defaults(catalog)
        assert selections["hyprland"] is False
        assert selections["desktop"] is False
        assert selections["tailscale"] is True

    def test_module_flag_overrides_its_group(self, catalog):
        answers = parse(catalog, ["--group-desktop=false", "--hyprland=true"])
        selections = answers.with_defaults(catalog)
        assert selections["hyprland"] is True
        assert selections["desktop"] is False

    def test_bare_flag_means_true(self, catalog):
        answers = parse(catalog, ["--gaming"])
        assert answers.with_defaults(catalog)["gaming"] is True


class TestBooleans:
    @pytest.mark.parametrize("word", ["true", "yes", "on", "1", "TRUE"])
    def test_truthy(self, word):
        assert cli.parse_bool(word) is True

    @pytest.mark.parametrize("word", ["false", "no", "off", "0", "False"])
    def test_falsey(self, word):
        assert cli.parse_bool(word) is False

    def test_rejects_anything_else(self):
        with pytest.raises(argparse.ArgumentTypeError):
            cli.parse_bool("maybe")


class TestHostNames:
    @pytest.mark.parametrize("name", ["pc", "t480s", "new-machine", "a1"])
    def test_accepted(self, name):
        assert validate_hostname(name) == name

    @pytest.mark.parametrize(
        "name", ["", "-leading", "Upper", "has_underscore", "x" * 70]
    )
    def test_rejected(self, name):
        with pytest.raises(AnswerError):
            validate_hostname(name)


class TestNonInteractiveGuard:
    def test_lists_everything_missing_at_once(self):
        missing = missing_answers(Answers())
        assert missing == ["--host", "--disk", "--password", "--github-token"]

    def test_separate_root_password_is_required_when_not_shared(self):
        answers = Answers(
            host="x",
            disk="/dev/sda",
            user_password="a",
            same_password=False,
            github_token="t",
        )
        assert missing_answers(answers) == ["--root-password"]

    def test_complete_answers_are_accepted(self):
        answers = Answers(
            host="x",
            disk="/dev/sda",
            user_password="a",
            github_token="t",
        )
        assert missing_answers(answers) == []


class TestPasswords:
    def test_shared_password_applies_to_root(self):
        answers = Answers(user_password="secret", same_password=True)
        assert answers.effective_root_password() == "secret"

    def test_separate_password_is_used_when_asked_for(self):
        answers = Answers(
            user_password="secret", root_password="other", same_password=False
        )
        assert answers.effective_root_password() == "other"

    def test_secrets_are_collected_for_redaction(self):
        answers = Answers(user_password="a", root_password="b", github_token="c")
        assert set(answers.secrets()) == {"a", "b", "c"}


class TestGeneratedNix:
    def test_strings_are_escaped(self):
        assert nixsrc.nix_string('a"b') == '"a\\"b"'
        assert nixsrc.nix_string("${x}") == '"\\${x}"'

    def test_system_configuration_only_carries_system_roles(self, catalog):
        rendered = nixsrc.render_system_configuration(
            "shed",
            catalog,
            {"hyprland": False, "desktop": True, "tailscale": True, "gaming": False},
            "25.11",
        )
        assert "hyprland.enable = false;" in rendered
        assert "tailscale.enable = true;" in rendered
        assert "desktopEnv.enable" not in rendered
        assert 'system.stateVersion = "25.11";' in rendered

    def test_home_configuration_only_carries_home_roles(self, catalog):
        rendered = nixsrc.render_home_configuration(
            "shed",
            catalog,
            {"hyprland": False, "desktop": True, "tailscale": True, "gaming": False},
        )
        assert "desktopEnv.enable = true;" in rendered
        assert "gaming.enable = false;" in rendered
        assert "hyprland.enable" not in rendered

    def test_laptop_is_never_written(self, catalog):
        rendered = nixsrc.render_home_configuration(
            "shed", catalog, {"desktop": True, "gaming": False}
        )
        assert "laptop.enable" not in rendered

    def test_disk_uses_the_named_layout(self):
        rendered = nixsrc.render_disk("shed", "/dev/nvme0n1", "plain")
        assert 'device = "/dev/nvme0n1";' in rendered
        assert 'layout = "plain";' in rendered


class TestDiskLabels:
    def test_size_is_human_readable(self):
        from nixos_installer.model import Disk

        disk = Disk(
            path="/dev/sda",
            size_bytes=512_110_190_592,
            model="Samsung SSD",
            transport="sata",
            removable=False,
        )
        assert "476.9G" in disk.label
        assert "/dev/sda" in disk.label
        assert "Samsung SSD" in disk.label
