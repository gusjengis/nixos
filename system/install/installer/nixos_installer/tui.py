"""The terminal interface.

One tab per decision, in the order the decisions are actually made, because
mixing "which disk gets erased" into the same screen as "do I want Steam" is
how the wrong disk gets erased. Nothing here decides anything: it fills in the
same answer set the command line produces, and hands it back.

Modules record only what was *touched*. An untouched module stays absent from
the answers, so it keeps following the configuration's own default even if the
host name changes afterwards and a different default applies.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    TabbedContent,
    TabPane,
)

from .model import AnswerError, Answers, Catalog, Disk, validate_hostname
from .workspace import check_github_token


@dataclass
class TuiResult:
    answers: Answers | None
    cancelled: bool


class ConfirmScreen(ModalScreen[bool]):
    """Last stop before the disk is destroyed."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-box {
        width: 78;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-title {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }
    #confirm-detail {
        margin-bottom: 1;
    }
    #confirm-buttons {
        height: auto;
        align: right middle;
    }
    """

    def __init__(self, detail: str) -> None:
        super().__init__()
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static("This destroys everything on the disk", id="confirm-title")
            yield Static(self.detail, id="confirm-detail", markup=False)
            yield Static("There is no undo, and no confirmation after this one.")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", variant="default", id="confirm-cancel")
                yield Button("Erase and install", variant="error", id="confirm-ok")

    @on(Button.Pressed, "#confirm-ok")
    def _ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-cancel")
    def _cancel(self) -> None:
        self.dismiss(False)


class InstallerApp(App[TuiResult]):
    """Tabbed installer."""

    CSS = """
    Screen {
        layers: base;
    }
    TabPane {
        padding: 1 2;
    }
    .hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    .section {
        text-style: bold;
        margin-top: 1;
    }
    .field-label {
        margin-top: 1;
    }
    .warning {
        color: $warning;
        margin-top: 1;
    }
    .category {
        text-style: bold;
        margin-top: 1;
    }
    .role {
        margin-left: 4;
    }
    .role-summary {
        margin-left: 8;
        color: $text-muted;
    }
    #disk-detail {
        margin-top: 1;
    }
    #review-summary {
        border: round $primary;
        padding: 1 2;
        margin-bottom: 1;
    }
    #actions {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #errors {
        color: $error;
        margin-top: 1;
    }
    Input {
        width: 60;
    }
    #token-row {
        height: auto;
    }
    #token-row Input {
        width: 40;
    }
    #token-row Button {
        margin-left: 1;
        min-width: 10;
    }
    #token-status {
        margin-top: 1;
    }
    #token-status.ok {
        color: $success;
    }
    #token-status.bad {
        color: $error;
    }

    /* Toggles default to a bordered box each, which at twenty-odd modules is
       three lines of frame per answer and makes the list impossible to scan.
       Flattened to one line, with focus shown by colour instead. */
    Checkbox, RadioButton {
        border: none;
        height: 1;
        padding: 0;
        background: transparent;
    }
    Checkbox:focus, RadioButton:focus {
        color: $accent;
        text-style: bold;
    }
    RadioSet {
        border: none;
        padding: 0;
        height: auto;
        width: 100%;
        background: transparent;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit_cancelled", "Cancel"),
        ("f5", "install", "Install"),
    ]

    TITLE = "NixOS installer"

    def __init__(
        self,
        catalog: Catalog,
        disks: list[Disk],
        initial: Answers,
        known_hosts: list[str],
        portable: bool,
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.disks = disks
        self.initial = initial
        self.known_hosts = known_hosts
        self.portable = portable

        self.selections: dict[str, bool] = catalog.defaults
        self.selections.update(initial.with_defaults(catalog))
        self.touched: set[str] = set(initial.modules)
        self._suppress = False

        # None: not checked yet, or the token changed since the last check.
        # True/False: what the last check against GitHub found, for exactly
        # the token currently in the field.
        self.token_verified: bool | None = None

    # -- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="stages"):
            with TabPane("1. Host", id="tab-host"):
                yield from self._host_tab()
            with TabPane("2. Disk", id="tab-disk"):
                yield from self._disk_tab()
            with TabPane("3. Modules", id="tab-modules"):
                yield from self._modules_tab()
            with TabPane("4. Accounts", id="tab-accounts"):
                yield from self._accounts_tab()
            with TabPane("5. Secrets", id="tab-secrets"):
                yield from self._secrets_tab()
            with TabPane("6. Review", id="tab-review"):
                yield from self._review_tab()
        yield Footer()

    def _host_tab(self) -> ComposeResult:
        yield Static(
            "The host name is this machine's roster key: its NixOS hostname, "
            "its Tailscale node name, and the directory its configuration "
            "lives in are all this one word.",
            classes="hint",
        )
        yield Label("Host name", classes="field-label")
        yield Input(
            value=self.initial.host or "",
            placeholder="t490",
            id="input-host",
        )
        yield Static("", id="host-note", classes="warning", markup=False)
        yield Label("Description (optional)", classes="field-label")
        yield Input(
            value=self.initial.description,
            placeholder="ThinkPad T490 with the full desktop.",
            id="input-description",
        )
        yield Static(
            "Already on the roster: " + (", ".join(self.known_hosts) or "none"),
            classes="hint",
        )

    def _disk_tab(self) -> ComposeResult:
        yield Static(
            "The whole disk is repartitioned and erased. Nothing on it "
            "survives, and nothing else is touched.",
            classes="hint",
        )
        if not self.disks:
            yield Static(
                "No disks found. If the only disks present are removable, "
                "re-run with --show-removable.",
                classes="warning",
            )
            return

        with RadioSet(id="disk-set"):
            for index, disk in enumerate(self.disks):
                yield RadioButton(
                    disk.label,
                    value=(
                        disk.path == self.initial.disk
                        if self.initial.disk
                        else index == 0
                    ),
                    id=f"disk-{index}",
                )
        yield Static("", id="disk-detail", classes="hint", markup=False)

    def _modules_tab(self) -> ComposeResult:
        yield Static(
            "Every module starts at what this configuration already defaults "
            "to, so an untouched screen installs a sensible machine. A "
            "category header turns everything under it on or off at once.",
            classes="hint",
        )
        with VerticalScroll():
            for category, roles in self.catalog.grouped():
                yield Checkbox(
                    Content(f"{category.label} - {category.description}"),
                    value=all(self.selections[role.id] for role in roles),
                    id=f"cat-{category.id}",
                    classes="category",
                )
                for role in roles:
                    yield Checkbox(
                        Content(f"{role.id}  ({role.scope})"),
                        value=self.selections[role.id],
                        id=f"role-{role.id}",
                        classes="role",
                    )
                    yield Static(role.summary, classes="role-summary", markup=False)

        if self.catalog.derived_roles:
            detected = ", ".join(
                f"{role.name}={'on' if role.value else 'off'}"
                for role in self.catalog.derived_roles
            )
            yield Static(
                f"Detected from this machine's hardware, not asked: {detected}",
                classes="hint",
            )

    def _accounts_tab(self) -> ComposeResult:
        yield Static(
            "Passwords are set directly on the installed system. They are "
            "never written into the configuration, which is a public "
            "repository.",
            classes="hint",
        )
        yield Checkbox(
            "Use the same password for gusjengis and root",
            value=self.initial.same_password,
            id="same-password",
        )
        yield Label("Password", classes="field-label", id="label-password")
        yield Input(
            value=self.initial.user_password or "",
            password=True,
            id="input-password",
        )
        yield Label("Root password", classes="field-label", id="label-root-password")
        yield Input(
            value=self.initial.root_password or "",
            password=True,
            id="input-root-password",
        )
        yield Static(
            "sudo is passwordless for the wheel group on these machines, so "
            "the root password only matters for console login and recovery.",
            classes="hint",
        )

    def _secrets_tab(self) -> ComposeResult:
        yield Static(
            "One GitHub token finishes the machine. The installer uses it to "
            "clone the private secrets checkout, which carries the SSH keys, "
            "the SMB credentials, the API keys, and the Tailscale auth key "
            "this machine needs to join the tailnet by itself on first boot. "
            "The same token pushes the new machine's configuration.",
            classes="hint",
        )
        yield Static(
            "The token needs `repo` scope to read a private repository.",
            classes="hint",
        )
        yield Label("GitHub token", classes="field-label")
        with Horizontal(id="token-row"):
            yield Input(
                value=self.initial.github_token or "",
                password=True,
                placeholder="ghp_...",
                id="input-token",
            )
            yield Button("Check", id="check-token")
        yield Checkbox("Show token", value=False, id="show-token")
        yield Static("", id="token-status", classes="hint", markup=False)
        yield Checkbox(
            "Commit and push this machine's configuration when done",
            value=self.initial.push,
            id="input-push",
        )
        yield Static(
            "Without a token the machine still installs, but it comes up with "
            "no credentials and does not join the tailnet, which makes a "
            "headless machine unreachable.",
            classes="warning",
        )

    def _review_tab(self) -> ComposeResult:
        yield Static("", id="review-summary", markup=False)
        yield Static("", id="errors", markup=False)
        with Horizontal(id="actions"):
            yield Button("Cancel", variant="default", id="cancel")
            yield Button("Install", variant="primary", id="install")

    # -- behaviour --------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_password_fields()
        self._refresh_host_note()
        self._refresh_disk_detail()

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "tab-review":
            self._refresh_summary()

    @on(Input.Changed, "#input-host")
    def _host_changed(self) -> None:
        self._refresh_host_note()

    def _refresh_host_note(self) -> None:
        note = self.query_one("#host-note", Static)
        host = self.query_one("#input-host", Input).value.strip()
        if not host:
            note.update("")
            return
        if host in self.known_hosts:
            note.update(
                f"{host} is already on the roster. Installing will reinstall "
                "that machine and reuse the modules it currently runs for "
                "anything you do not change here."
            )
            return
        try:
            validate_hostname(host)
        except AnswerError as error:
            note.update(str(error))
            return
        note.update("")

    @on(RadioSet.Changed, "#disk-set")
    def _disk_changed(self) -> None:
        self._refresh_disk_detail()

    def _refresh_disk_detail(self) -> None:
        try:
            detail = self.query_one("#disk-detail", Static)
        except Exception:
            return
        disk = self._selected_disk()
        if disk is None:
            detail.update("")
            return
        lines = [f"{disk.path}: {disk.size_human} {disk.model}".rstrip()]
        if disk.partitions:
            lines.append("Partitions that will be destroyed:")
            lines.extend(f"  {part}" for part in disk.partitions)
        else:
            lines.append("No partitions found on it.")
        if disk.mounted:
            lines.append(
                "Something on this disk is mounted right now. Make sure it is "
                "not the system you are installing from."
            )
        detail.update("\n".join(lines))

    def _selected_disk(self) -> Disk | None:
        if not self.disks:
            return None
        try:
            radio_set = self.query_one("#disk-set", RadioSet)
        except Exception:
            return None
        index = radio_set.pressed_index
        if index is None or index < 0 or index >= len(self.disks):
            return None
        return self.disks[index]

    @on(Checkbox.Changed, "#same-password")
    def _same_password_changed(self) -> None:
        self._refresh_password_fields()

    def _refresh_password_fields(self) -> None:
        same = self.query_one("#same-password", Checkbox).value
        label = self.query_one("#label-root-password", Label)
        field = self.query_one("#input-root-password", Input)
        label.display = not same
        field.display = not same
        self.query_one("#label-password", Label).update(
            "Password (used for both accounts)" if same else "Password for gusjengis"
        )

    @on(Checkbox.Changed, "#show-token")
    def _show_token_changed(self, event: Checkbox.Changed) -> None:
        self.query_one("#input-token", Input).password = not event.value

    @on(Input.Changed, "#input-token")
    def _token_changed(self) -> None:
        # A result from before the token was edited is worse than no result:
        # it claims to be about text that is no longer in the field.
        self.token_verified = None
        status = self.query_one("#token-status", Static)
        status.update("")
        status.remove_class("ok", "bad")

    @on(Input.Submitted, "#input-token")
    def _token_submitted(self) -> None:
        self._start_token_check()

    @on(Button.Pressed, "#check-token")
    def _check_token_pressed(self) -> None:
        self._start_token_check()

    def _start_token_check(self) -> None:
        token = self.query_one("#input-token", Input).value
        status = self.query_one("#token-status", Static)
        status.remove_class("ok", "bad")
        if not token:
            status.update("No token to check.")
            self.token_verified = None
            return
        status.update("Checking token against GitHub...")
        self._check_token_worker(token)

    @work(thread=True, exclusive=True, group="token-check")
    def _check_token_worker(self, token: str) -> None:
        """Runs off the UI thread: this is a real network call.

        `check_github_token` is looked up on `self` rather than called as a
        bare name so a test can replace the whole worker with a synchronous
        stand-in and never touch a thread or the network.
        """

        ok, message = check_github_token(token)
        self.call_from_thread(self._apply_token_result, token, ok, message)

    def _apply_token_result(self, token: str, ok: bool, message: str) -> None:
        # Discard a result for a token that has since been edited away; the
        # field no longer matches what this result describes.
        if self.query_one("#input-token", Input).value != token:
            return
        self.token_verified = ok
        status = self.query_one("#token-status", Static)
        status.update(message)
        status.set_class(ok, "ok")
        status.set_class(not ok, "bad")

    @on(Checkbox.Changed)
    def _checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._suppress:
            return
        identifier = event.checkbox.id or ""

        if identifier.startswith("cat-"):
            category_id = identifier.removeprefix("cat-")
            self._set_category(category_id, event.value)
        elif identifier.startswith("role-"):
            role_id = identifier.removeprefix("role-")
            self.selections[role_id] = event.value
            self.touched.add(role_id)
            self._sync_category_of(role_id)

    def _set_category(self, category_id: str, value: bool) -> None:
        self._suppress = True
        try:
            for role in self.catalog.roles_in(category_id):
                self.selections[role.id] = value
                self.touched.add(role.id)
                self.query_one(f"#role-{role.id}", Checkbox).value = value
        finally:
            self._suppress = False

    def _sync_category_of(self, role_id: str) -> None:
        role = self.catalog.by_id(role_id)
        if role is None:
            return
        members = self.catalog.roles_in(role.category)
        if not members:
            return
        self._suppress = True
        try:
            box = self.query_one(f"#cat-{role.category}", Checkbox)
            box.value = all(self.selections[member.id] for member in members)
        finally:
            self._suppress = False

    # -- result -----------------------------------------------------------

    def _collect(self) -> Answers:
        disk = self._selected_disk()
        same = self.query_one("#same-password", Checkbox).value
        return Answers(
            host=self.query_one("#input-host", Input).value.strip() or None,
            disk=disk.path if disk else None,
            layout=self.initial.layout,
            modules={role_id: self.selections[role_id] for role_id in self.touched},
            groups={},
            user_password=self.query_one("#input-password", Input).value or None,
            root_password=(
                None if same else self.query_one("#input-root-password", Input).value
            )
            or None,
            same_password=same,
            github_token=self.query_one("#input-token", Input).value or None,
            description=self.query_one("#input-description", Input).value.strip(),
            push=self.query_one("#input-push", Checkbox).value,
            assume_yes=True,
        )

    def _problems(self, answers: Answers) -> list[tuple[str, str]]:
        """Blocking problems, each with the tab that fixes it."""

        problems: list[tuple[str, str]] = []
        try:
            validate_hostname(answers.host)
        except AnswerError as error:
            problems.append(("tab-host", str(error)))

        if not answers.disk:
            problems.append(("tab-disk", "Choose a disk to install onto."))

        if not answers.user_password:
            problems.append(("tab-accounts", "Set a password."))
        elif not answers.same_password and not answers.root_password:
            problems.append(
                ("tab-accounts", "Set a root password, or use the same one for both.")
            )

        return problems

    def _token_status_text(self, answers: Answers) -> str:
        if not answers.github_token:
            return "not given"
        if self.token_verified is True:
            return "given, verified"
        if self.token_verified is False:
            return "given, but rejected on the Secrets tab -- check it again"
        return "given, not checked (press Check on the Secrets tab)"

    def _refresh_summary(self) -> None:
        answers = self._collect()
        selections = answers.with_defaults(self.catalog)
        enabled = sorted(role for role, on in selections.items() if on)
        disabled = sorted(role for role, on in selections.items() if not on)

        lines = [
            f"Host       {answers.host or '(not set)'}",
            f"Disk       {answers.disk or '(not chosen)'}   [{answers.layout}]",
            f"Chassis    {'laptop' if self.portable else 'desktop'}  (detected)",
            f"Password   {'set' if answers.user_password else 'NOT SET'}"
            + ("  (same for root)" if answers.same_password else "  (root differs)"),
            f"Token      {self._token_status_text(answers)}",
            f"Push       {'yes' if answers.push else 'no'}",
            "",
            f"On         {', '.join(enabled) or 'nothing'}",
            f"Off        {', '.join(disabled) or 'nothing'}",
        ]
        self.query_one("#review-summary", Static).update("\n".join(lines))

        problems = self._problems(answers)
        self.query_one("#errors", Static).update(
            "\n".join(message for _, message in problems)
        )

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.exit(TuiResult(answers=None, cancelled=True))

    @on(Button.Pressed, "#install")
    def _install(self) -> None:
        self.action_install()

    def action_install(self) -> None:
        answers = self._collect()
        problems = self._problems(answers)
        if problems:
            tab, _ = problems[0]
            self.query_one("#stages", TabbedContent).active = tab
            self.query_one("#errors", Static).update(
                "\n".join(message for _, message in problems)
            )
            self.bell()
            return

        disk = self._selected_disk()
        detail = disk.label if disk else str(answers.disk)
        partitions = "\n".join(
            f"  {part}" for part in (disk.partitions if disk else ())
        )
        body = f"{detail}\n\n" + (partitions or "  (no partitions found)")

        def finish(confirmed: bool | None) -> None:
            if confirmed:
                self.exit(TuiResult(answers=answers, cancelled=False))

        self.push_screen(ConfirmScreen(body), finish)

    def action_quit_cancelled(self) -> None:
        self.exit(TuiResult(answers=None, cancelled=True))


def run_tui(
    catalog: Catalog,
    disks: list[Disk],
    initial: Answers,
    known_hosts: list[str],
    portable: bool,
) -> TuiResult:
    app = InstallerApp(catalog, disks, initial, known_hosts, portable)
    result = app.run()
    if result is None:
        return TuiResult(answers=None, cancelled=True)
    return result
