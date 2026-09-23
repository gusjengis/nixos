"""Tests for the interface.

Run headlessly through Textual's own test harness, so these check the parts
that are easy to get wrong and impossible to notice: that a category header
really does drive the modules under it, that the header follows when a module
is changed on its own, that the shared-password checkbox actually removes the
second field, and that only *touched* modules are reported as answered.

That last one is what keeps the interface and the command line consistent: an
untouched module has to stay unanswered so it can still follow a default that
changes when the host name does.
"""

from __future__ import annotations

import asyncio

import pytest

from nixos_installer.model import Answers, Catalog, Disk
from nixos_installer.tui import InstallerApp

from .test_resolution import CATALOG_JSON


@pytest.fixture
def catalog() -> Catalog:
    return Catalog.from_json(CATALOG_JSON)


@pytest.fixture
def disks() -> list[Disk]:
    return [
        Disk(
            path="/dev/nvme0n1",
            size_bytes=512_110_190_592,
            model="Samsung SSD 970",
            transport="nvme",
            removable=False,
            partitions=("/dev/nvme0n1p1 (512M)", "/dev/nvme0n1p2 (476G)"),
        ),
        Disk(
            path="/dev/sda",
            size_bytes=1_000_204_886_016,
            model="WDC WD10",
            transport="sata",
            removable=False,
        ),
    ]


def drive(app: InstallerApp, body):
    """Run an async interaction against the app, headlessly."""

    async def main():
        async with app.run_test() as pilot:
            return await body(pilot)

    return asyncio.run(main())


def make_app(catalog, disks, initial=None) -> InstallerApp:
    return InstallerApp(
        catalog=catalog,
        disks=disks,
        initial=initial or Answers(),
        known_hosts=["pc", "t480s"],
        portable=False,
    )


class TestCategoryToggles:
    def test_header_turns_every_module_under_it_off(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            from textual.widgets import Checkbox

            app.query_one("#cat-desktop", Checkbox).toggle()
            await pilot.pause()
            return (
                app.selections["hyprland"],
                app.selections["desktop"],
                app.selections["tailscale"],
            )

        hyprland, desktop, tailscale = drive(app, body)
        assert hyprland is False
        assert desktop is False
        # A different category is untouched.
        assert tailscale is True

    def test_header_reflects_its_modules(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            from textual.widgets import Checkbox

            # Both desktop modules start on, so the header starts on.
            assert app.query_one("#cat-desktop", Checkbox).value is True
            app.query_one("#role-hyprland", Checkbox).toggle()
            await pilot.pause()
            return app.query_one("#cat-desktop", Checkbox).value

        assert drive(app, body) is False

    def test_only_touched_modules_are_answered(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            from textual.widgets import Checkbox

            app.query_one("#role-gaming", Checkbox).toggle()
            await pilot.pause()
            return app._collect().modules

        assert drive(app, body) == {"gaming": True}


class TestPasswords:
    def test_second_field_is_hidden_when_shared(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            from textual.widgets import Input

            return app.query_one("#input-root-password", Input).display

        assert drive(app, body) is False

    def test_second_field_appears_when_not_shared(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            from textual.widgets import Checkbox, Input

            app.query_one("#same-password", Checkbox).toggle()
            await pilot.pause()
            return app.query_one("#input-root-password", Input).display

        assert drive(app, body) is True


class TestValidation:
    def test_install_is_refused_until_the_required_answers_exist(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            answers = app._collect()
            return [tab for tab, _ in app._problems(answers)]

        problems = drive(app, body)
        assert "tab-host" in problems
        assert "tab-accounts" in problems

    def test_complete_answers_have_no_problems(self, catalog, disks):
        app = make_app(
            catalog,
            disks,
            Answers(host="shed", user_password="secret", github_token="t"),
        )

        async def body(pilot):
            from textual.widgets import Input

            app.query_one("#input-host", Input).value = "shed"
            app.query_one("#input-password", Input).value = "secret"
            await pilot.pause()
            return app._problems(app._collect())

        assert drive(app, body) == []

    def test_existing_roster_host_is_called_out(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            from textual.widgets import Input, Static

            app.query_one("#input-host", Input).value = "t480s"
            await pilot.pause()
            return app.query_one("#host-note", Static).content

        note = str(drive(app, body))
        assert "already on the roster" in note


class TestMarkupIsNotEaten:
    """Text taken from the configuration is not Textual markup.

    Square brackets are markup by default, so a summary or a value containing
    them is silently swallowed. The review pane showed the disk layout as
    `[plain]` and rendered nothing at all until every dynamic Static was told
    not to parse markup.
    """

    def test_bracketed_values_survive_the_review_pane(self, catalog, disks):
        app = make_app(catalog, disks, Answers(host="shed", user_password="p"))

        async def body(pilot):
            from textual.widgets import Static, TabbedContent

            app.query_one("#stages", TabbedContent).active = "tab-review"
            await pilot.pause()
            return str(app.query_one("#review-summary", Static).content)

        assert "[plain]" in drive(app, body)

    def test_a_summary_containing_brackets_is_shown_whole(self, disks):
        raw = dict(CATALOG_JSON)
        raw["roles"] = [dict(role) for role in CATALOG_JSON["roles"]]
        raw["roles"][0] = dict(raw["roles"][0], summary="Compositor [experimental]")
        catalog = Catalog.from_json(raw)
        app = make_app(catalog, disks)

        async def body(pilot):
            from textual.widgets import Static

            summaries = app.query(".role-summary").results(Static)
            return [str(widget.content) for widget in summaries]

        assert "Compositor [experimental]" in drive(app, body)


class TestDiskSelection:
    def test_first_disk_is_preselected(self, catalog, disks):
        app = make_app(catalog, disks)

        async def body(pilot):
            return app._collect().disk

        assert drive(app, body) == "/dev/nvme0n1"

    def test_preselects_the_disk_given_on_the_command_line(self, catalog, disks):
        app = make_app(catalog, disks, Answers(disk="/dev/sda"))

        async def body(pilot):
            return app._collect().disk

        assert drive(app, body) == "/dev/sda"
