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

- [ ] Add `nix-community/disko` as a flake input and NixOS module.
- [ ] Capture `lsblk --json` and `sfdisk --dump` from every host before writing
  disk configuration.
- [ ] Write `system/hosts/<host>/disk.nix` for existing hosts with
  `disko.enableConfig = false`. These files document exact recovery layouts but
  must not change current `fileSystems` values.
- [ ] Prove each existing host's system derivation is unchanged before and
  after adding its disabled Disko description.
- [ ] Enable Disko ownership only for new installations initially.
- [ ] Exclude Mac/Asahi from generic destructive partitioning. It needs a
  separate flow coordinated with the Asahi installer.
- [ ] Treat multi-disk systems carefully. `pc` has five disks; only `nvme0n1`
  contains NixOS. Windows and data disks must never enter a destructive Disko
  layout.

Stop condition: installer can declaratively partition a new x86 host, while
adding Disko changes no existing host's boot or filesystem configuration.

### 4. Phase 4: Installer flake app

- [ ] Add an explicit role catalog in Nix: option name, description, group,
  default, and whether it belongs to NixOS or Home Manager.
- [ ] Assert catalog options exist. Do not revive the old script's fragile awk
  parsing of `mkEnableOption` source text.
- [ ] Export catalog JSON for the installer TUI.
- [ ] Add `apps.<system>.install` using `writeShellApplication` with pinned
  runtime dependencies: Git, Disko, NixOS Facter, jq, util-linux, and required
  terminal tools.
- [ ] Preserve interactive multi-select and useful previews from the old
  installer's native TUI, but keep installation policy in Nix data.
- [ ] Support new-host enrollment and reinstalling an existing roster host.
- [ ] Ask for explicit destructive disk confirmation including device model,
  size, and current partitions.
- [ ] Generate and stage the roster entry, system host module, home host module,
  Disko config, and facter report. Flakes ignore untracked Git files.
- [ ] Run Disko, then `nixos-install --flake path:/mnt/etc/nixos#<host>`.
- [ ] Install the repository at `/mnt/etc/nixos`, owned by `gusjengis` but not
  writable by unrelated users because root later evaluates it.
- [ ] Add `apps.<system>.enroll` for an already-running NixOS machine without
  repartitioning.
- [ ] Handle user password setup explicitly; do not ship a reusable initial
  password or password hash.
- [ ] Detect whether Secure Boot, disk encryption, swap, hibernation, or dual
  boot need installer questions before choosing defaults.

Stop condition: a stock NixOS ISO can install a new x86 machine using only the
single `nix run github:gusjengis/nixos#install` entry point after networking.

### 5. Phase 5: First boot

- [ ] Keep Home Manager standalone so its nixpkgs pin and fast user-only
  iteration remain independent from NixOS.
- [ ] Add a root or user oneshot guarded by a persistent completion marker such
  as `/var/lib/nixos-config/first-boot-complete`.
- [ ] Transfer GitHub/secrets bootstrap credentials without placing them in the
  Nix store or repository. Use mode `0600`; delete bootstrap credentials after
  successful use.
- [ ] Clone `~/.config/secrets`, then run Home Manager for the selected host.
- [ ] Run repository synchronization only after secrets and GitHub
  authentication are ready.
- [ ] Write the completion marker only after all required steps succeed, so a
  failed first boot retries safely.
- [ ] Ensure normal rebuilds and logins never display installer questions.

Stop condition: first boot reaches the configured desktop or headless state
without manual Home Manager commands, and later boots do not repeat setup.

### 6. Phase 6: Cleanup and documentation

- [ ] Archive `gusjengis/nix-install-script`; replace its README with a pointer
  to this repository.
- [ ] Remove `nix-install-script` from
  `home/features/repo-sync/repos/dev.list`.
- [ ] Add `INSTALL.md` containing only the supported ISO flow, recovery flow,
  Mac/Asahi exception, and rollback instructions.
- [ ] Update `ARCHITECTURE.md` after installer and first-boot behavior exist.
- [ ] Test the documented process in a disposable VM before using physical
  hardware.

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

1. Read this file and `ARCHITECTURE.md`.
2. Inspect `git status` and recent commits; Phase 1 may still be uncommitted.
3. Verify all eight nodes are reachable with `tailscale status` before fleet
   changes.
4. Continue with Phase 2, preserving each stop condition.
5. Update this file as tasks complete or new blockers appear.
