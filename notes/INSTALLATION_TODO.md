# Installation Simplification

This file is the durable handoff for making this repository install a new
machine with minimal external help. Update it whenever installation work lands.

## Goal

From a NixOS installer ISO, connect networking and run:

```bash
nix --extra-experimental-features 'nix-command flakes' \
  run github:gusjengis/nixos#install
```

The installer should interactively select a host and feature roles, partition
the selected disk, capture hardware facts, install NixOS, clone this repository
to `/etc/nixos`, and arrange one-time Home Manager and secrets setup after the
first boot. Normal rebuilds must never prompt.

Nix evaluation cannot prompt. Interactive selection therefore belongs in a
flake-provided script; selected values become normal tracked Nix host files.

## Completed

### Phase 0: Pure evaluation

Completed in commit `0806d0e`.

- Public SSH key moved to `system/keys/shared_ed25519.pub`.
- System users read the key from this repository, not the secrets checkout.
- `--impure` removed from `rebuild` and the `nd` alias.
- All eight NixOS configurations now evaluate purely.

### Phase 1: Stable host identity

Completed in the working tree on 2026-09-17 and deployed to all eight hosts.

- `networking.hostName` is the roster key on every host.
- Tailscale applies `--hostname=<roster key>` both to authenticated nodes and
  fresh registrations.
- `rebuild` and `rehome` select the flake output from `hostname`.
- Machine IDs and `/etc/machine-id` lookup were removed from the roster and
  commands.
- Verified live identity for `pc`, `alpha`, `omega`, `legion`, `mac`, `t480s`,
  `t470`, and `zombie`: OS hostname, Tailscale HostName, and MagicDNS label all
  match the roster key.
- NixOS and Home Manager changes were activated on all eight hosts.

Mac pure evaluation needed one prerequisite. Asahi peripheral firmware is now
addressed as a fixed-output file instead of discovered impurely under `/boot`.
Before building Mac on a fresh installation, seed its store with:

```bash
sudo nix-store --add-fixed sha256 /boot/vendorfw/firmware.cpio
```

Expected firmware hash:

```text
sha256-GZ/dZgjZHgRxGf9XJjXX/JFVcRYN/+Z+FcwrEkvsH2A=
```

## Next Work

### 1. Finish Phase 1 verification

- [ ] Commit Phase 1 changes and this roadmap.
- [ ] Reboot each host naturally and confirm `hostname` still equals its roster
  key. Runtime hostnames and `/etc/hostname` already match; persistence has not
  yet been tested through a reboot.
- [ ] Confirm `rebuild` and `rehome` select the correct output without an
  explicit host on at least one desktop, one headless host, and Mac.
- [ ] Revisit host selection after installer work lands. Commands currently
  embed the Home Manager configuration's roster key, which avoids stale
  runtime hostnames but means an incorrectly bootstrapped Home Manager profile
  preserves the wrong identity. Decide whether installed systems should return
  to selecting from `hostname`, and document how the installer seeds the first
  NixOS and Home Manager selections without circular discovery.
- [x] Remove temporary `/tmp/nixos-phase1` trees from remote hosts.

### 2. Phase 2: NixOS Facter

- [x] Generate `system/hosts/<host>/facter.json` on all eight hosts:

  ```bash
  sudo nix run nixpkgs#nixos-facter -- -o facter.json
  ```

- [x] Set `hardware.facter.reportPath` per host. Facter support is already in
  the pinned nixpkgs; no extra flake input is needed.
- [x] Keep each `hardware-configuration.nix` initially. Compared evaluated
  initrd modules, CPU microcode, graphics, networking, and platform values
  before deleting generated declarations.
- [x] Add a shared hardware policy module using facter data and `lib.mkDefault`.
  Detect at least NVIDIA/AMD graphics, CPU vendor, laptop battery, Bluetooth,
  fingerprint reader, and virtualization support.
- [x] Preserve host overrides. Alpha's GTX 1080 uses the legacy NVIDIA 580
  package and cannot use a naive generic NVIDIA default.
- [x] Verify every host evaluates; build each architecture on a matching host.

Completed in the working tree on 2026-09-17.

- All eight reports were captured on their owning hosts.
- Facter now supplies each structured host platform. The redundant generated
  string `nixpkgs.hostPlatform` declarations were removed because current
  nixpkgs rejects mixing the two representations.
- Generated filesystem and explicit boot declarations remain in place.
- Shared policy detects NVIDIA/AMD graphics, Intel/AMD CPU, laptop form factor,
  Bluetooth, Synaptics fingerprint readers, and VMX/SVM support. Defaults enable
  matching GPU, microcode, Bluetooth, fingerprint, and power support.
- Evaluated initrd modules, kernel modules, microcode, video drivers,
  NetworkManager, and platform values were reviewed for every host.
- All seven x86 closures built on `pc`; the aarch64 Mac closure built on `mac`.
- Alpha still resolves `nvidia-x11-580.178.04`. Mac keeps its explicit Asahi
  hardware configuration because its Facter report lacks Apple GPU details.
- Added `refresh-hardware`, a Home Manager command that re-probes hardware and
  overwrites the committed `facter.json`. Nothing runs this automatically;
  see `ARCHITECTURE.md`'s Hardware Detection section for why and when to run
  it by hand.

Stop condition: facter supplies hardware detection, existing behavior is
preserved, and no host-specific generated hardware declaration is removed
without an evaluated replacement.

### 3. Phase 3: Disko

- [x] Add `nix-community/disko` as a flake input and NixOS module.
- [x] Capture `lsblk --json` and `sfdisk --dump` from every host before writing
  disk configuration.
- [x] Write `system/hosts/<host>/disk.nix` for existing hosts with
  `disko.enableConfig = false`. These files document exact recovery layouts but
  must not change current `fileSystems` values.
- [x] Prove each existing host's system derivation is unchanged before and
  after adding its disabled Disko description.
- [x] Enable Disko ownership only for new installations initially.
- [x] Exclude Mac/Asahi from generic destructive partitioning. It needs a
  separate flow coordinated with the Asahi installer.
- [x] Treat multi-disk systems carefully. `pc` has five disks; only `nvme1n1`
  contains NixOS. Windows and data disks must never enter a destructive Disko
  layout.

Completed 2026-09-18. Live inventory was collected from all eight hosts before
writing sector-exact layouts. Every existing host keeps
`disko.enableConfig = false`; all eight system derivation paths were identical
before and after integration. Disko scripts build for every x86 host; the Mac
script evaluates but cannot be built on an x86 machine. Its file records the
mixed APFS/Asahi map for recovery only and is not a generic install target.

Stop condition: installer can declaratively partition a new x86 host, while
adding Disko changes no existing host's boot or filesystem configuration.

### 4. Phase 4: Installer flake app

- [x] Derive the role catalog from the evaluated NixOS and Home Manager option
      trees rather than declaring it. `system/install/catalog.nix` walks both
      trees and keeps boolean `*.enable` options declared inside this
      repository and outside `system/hosts/` and `home/hosts/`, which is what
      excludes machine-specific modules such as `immich.enable` without
      listing them anywhere.
- [x] Assert consistency instead of parsing source text. Metadata naming an
      option that no longer exists, two roles claiming one flag name, or a role
      in an unknown category all fail evaluation. `nix flake check` evaluates
      every host's catalog, so the check runs without an installation.
- [x] Export the catalog as JSON through `roleCatalogs.<host>`.
- [x] Add `apps.<system>.install`. It is a Python program, not a shell script:
      `system/install/installer`, packaged by `system/install/package.nix` with
      Disko, nixos-install-tools, nixos-facter, util-linux, git, openssh, nix
      and shadow pinned onto its PATH.
- [x] Replace the old native multi-select with a Textual interface whose tabs
      are the decisions: host, disk, modules, accounts, secrets, review.
      Categories are toggleable headers with their modules nested underneath.
- [x] Make every decision available as a flag, so a batch of machines needs no
      interface at all. Modules are `--<module>=true|false`, categories are
      `--group-<id>=true|false`, and `--list-modules` prints both.
- [x] Reinstall an existing roster host by evaluating that host's catalog,
      which reports its current selections as the defaults. No special case:
      it is the same code path a new machine takes.
- [x] Confirm destruction with device, model, size, and current partitions.
- [x] Generate the roster entry, host module, home module, Disko
      configuration, and Facter report. Evaluated over `path:` rather than
      `git+file:`, which is what makes the untracked scaffold visible.
- [x] Run Disko, then `nixos-install --flake path:<workspace>#<host>`.
- [x] Install the repository at `/etc/nixos`, owned by `gusjengis` and not
      group- or world-writable.
- [x] Take passwords for both accounts, with a checkbox for using one for
      both. Set through `chpasswd` on stdin inside `nixos-enter`; no hash is
      ever written to a tracked file.
- [x] Decide the remaining hardware questions: no encryption, no Secure Boot,
      no hibernation. See "Deliberately out of scope" below.
- [x] Fix `laptop.enable` to follow detected hardware rather than an answer.
      It reads the SMBIOS chassis type through `system/install/lib/facter.nix`.
- [x] Verify the GitHub token against the secrets repository (`git
      ls-remote`) rather than only checking it is non-empty. Checked live in
      the TUI (a "Check" button, and on Enter), with a "Show token" checkbox
      since the field is hidden by default; checked again in `preflight()`
      right before the disk is touched, so a token nobody checked, or that
      changed after it was, still gets caught. Also closed a real bug found
      while building this: any credential helper already configured wherever
      the installer runs (a cached `gh` login, a keychain helper) was
      answering git's auth prompt before the supplied token ever got a
      chance, which made a wrong token look accepted. `git_credentials()` now
      disables other credential helpers for everything it authenticates.
- [x] Reboot automatically once installation finishes, with a ten-second
      warning to pull removable installation media first. `--reboot=false`
      keeps the old manual-reboot behaviour for scripted runs.
- [ ] Install a real machine from a real ISO.

Dropped: `apps.<system>.enroll`. Adopting an already-installed machine is not
a case that has come up, and the installer is smaller without it.

Stop condition: a stock NixOS ISO can install a new x86 machine using only the
single `nix run github:gusjengis/nixos#install` entry point after networking.

### 5. Phase 5: First boot

Mostly absorbed into Phase 4. Secrets arrive during installation rather than
through a credential handoff, so there is nothing to transfer and no bootstrap
credential to delete afterwards.

- [x] Keep Home Manager standalone.
- [x] Clone `~/.config/secrets` during installation, using the GitHub token the
      installer was given. One token is enough for a finished machine: the
      checkout carries the personal access token the shell exports, the SSH
      keys, the SMB credentials, and the Tailscale auth key that
      `tailscale-autoconnect.service` reads, so the machine joins the tailnet
      by itself.
- [x] Build the Home Manager closure into the new system's store during
      installation, so first boot activates rather than compiles.
- [x] Activate on first boot through `system/modules/software/first-boot.nix`,
      conditioned on `/var/lib/nixos-install/pending-home-manager`. The unit is
      inert on every machine that was not just installed, and a failure leaves
      the marker in place so the next boot retries.
- [x] Normal rebuilds and logins never show installer questions: there is no
      enable option and nothing runs without the marker.
- [ ] Confirm on real hardware that first boot reaches the desktop.

Stop condition: first boot reaches the configured desktop or headless state
without manual Home Manager commands, and later boots do not repeat setup.

### 6. Phase 6: Cleanup and documentation

- [ ] Archive `gusjengis/nix-install-script`; replace its README with a pointer
      to this repository. Needs doing on GitHub, not here.
- [x] Remove `nix-install-script` from
      `home/features/repo-sync/repos/dev.list`.
- [x] Add `notes/INSTALL.md` containing the supported ISO flow, the
      non-interactive flow, reinstalling an existing host, the Mac/Asahi
      exception, and what to do when a step fails.
- [x] Update `ARCHITECTURE.md`. Its machine-identity section still described
      the machine-id lookup that Phase 1 removed; that is corrected, and the
      installer and first-boot behaviour are documented.
- [ ] Test the documented process in a disposable VM before using physical
      hardware.

## Deliberately Out Of Scope

Decided while building Phase 4. Recorded because each one is cheap to add
later only if the reason it was skipped is written down.

### Disk encryption (LUKS)

Not wanted. It protects data at rest on stolen hardware, and costs a
passphrase prompt at every boot. That prompt is fatal for the headless
machines, which would hang at boot waiting for a keyboard that is not there.
TPM auto-unlock and initrd network unlock both exist and are both real
complexity for a threat this fleet does not have.

Worth knowing: this cannot be added to a machine afterwards without
reinstalling it. Adding it later means a new entry in
`system/install/lib/layouts.nix` and reinstalling the machines that want it.

### Hibernation

Wanted eventually, not now.

Hibernation writes RAM to swap and powers off completely, so a laptop can stay
closed for a week without draining. It is different from the suspend the lids
currently do, which keeps RAM powered.

It is impossible on this fleet as it stands: every machine uses
`zramSwap.enable`, which is compressed swap inside RAM, and there is no disk
swap anywhere. Hibernation needs a swap area at least the size of RAM plus
`boot.resumeDevice`.

To add it:

1. Add a `swap` layout to `system/install/lib/layouts.nix` with a swap
   partition sized to RAM, and set `boot.resumeDevice` from it.
2. Existing machines need repartitioning or a swap *file*, which also works
   but needs `boot.resumeOffset`.
3. Expect trouble on the NVIDIA machines (`pc`, `alpha`, `zombie`); resume
   with the proprietary driver has historically been unreliable.

The layout is behind a name specifically so this is an additive change.

### Secure Boot

Not wanted. It needs `lanzaboote` and enrolling custom keys into each
machine's firmware, and buys boot-chain integrity enforcement that nothing
here asks for.

## Known Problems

### The Git history is about 1.45 GiB

`git count-objects -vH` reports 1.45 GiB packed, against a working tree of
roughly 6 MB of real content. Something large is in the history, most likely
wallpapers from before they moved to the Wallpapers repository.

This is a tax on every installation and every `update`. The installer works
around it by cloning with `--depth 1` and only deepening when it has something
to push, but the underlying problem is still there.

Fixing it means `git filter-repo` over the history and a force-push, which
rewrites every commit hash and requires every machine in the fleet to re-clone.
It is worth doing as its own piece of work, not folded into something else.

## Design Decisions

- Home Manager remains standalone and runs automatically on first boot.
- New generic x86 installations use Disko; existing hosts migrate only with
  proof that layouts match.
- Hardware detection uses upstream nixpkgs Facter modules plus local policy.
- Host identity is the roster key, shared by NixOS hostname and Tailscale.
- Public SSH keys belong in this repository. Secret values remain in the
  private secrets repository and must never enter Nix evaluation.
- The installer runs from the NixOS ISO. Supporting arbitrary non-NixOS Linux
  installers is out of scope unless explicitly requested later.

## Resume Checklist

1. Read this file, `INSTALL.md`, and `ARCHITECTURE.md`.
2. Inspect `git status` and recent commits.
3. Verify all eight nodes are reachable with `tailscale status` before fleet
   changes.
4. What is left is testing: install a real machine from a real ISO, confirm
   first boot reaches the desktop, then archive the old install script
   repository on GitHub.
5. Update this file as tasks complete or new blockers appear.

## Verifying a change to the installer

```bash
# Everything that does not need hardware.
nix flake check

# Modules, their flags and their defaults, without root.
nix run .#install -- --list-modules --source /etc/nixos

# Resolve every decision and show the files that would be written.
nix run .#install -- --dry-run --yes --source /etc/nixos \
  --host test --disk /dev/sda --password x --github-token y

# Prove the generated machine is real.
nix build path:/tmp/nixos-install#nixosConfigurations.test.config.system.build.toplevel
```

When changing anything that touches the shared modules, take derivation paths
for all eight machines before and after and diff them. An unexplained change
there means a machine is about to be rebuilt for a reason nobody intended:

```bash
for h in pc alpha omega legion mac t480s t470 zombie; do
  printf '%s ' "$h"
  nix eval --raw ".#nixosConfigurations.$h.config.system.build.toplevel.drvPath"
  echo
done
```
