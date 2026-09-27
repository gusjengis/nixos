# Architecture

This repository is the complete NixOS and Home Manager configuration for eight
machines. Its canonical checkout is `/etc/nixos`, owned and updated by
`gusjengis`. Machines should be reproducible from this repository plus the
private secrets repository; manually installed software is considered a bug.

## Layout

```text
flake.nix                 inputs, pins, and all flake outputs
system/
  hosts/default.nix       roster discovery; machines are the directories beside it
  hosts/<host>/           meta, hardware report, disk layout, NixOS configuration
  modules/                shared NixOS modules
  install/                the installer, and the data it derives its questions from
home/
  default.nix             shared Home Manager configuration
  hosts/<host>/           per-machine Home Manager settings
  features/               user features, including config, scripts, and units
  packages/               repository-built Home Manager packages
  policy/                 Home Manager package policy
```

System and Home Manager package sets remain independently pinned. `nixpkgs`
drives Home Manager; `nixpkgs-system` drives NixOS. This prevents structural
work from implicitly upgrading the operating system.

## Machine Identity

A machine's roster key is its NixOS hostname and its Tailscale node name at
once, so `hostname` selects its flake output. `rehome` and `rebuild` perform
that lookup and also accept an explicit host name, which matters during
recovery when the runtime hostname is not yet correct:

```bash
rehome t480s
rebuild t480s
```

The roster is discovered rather than listed. Every directory under
`system/hosts/` containing a `meta.nix` is a machine, and that file holds the
architecture, the description, and the services worth naming. Adding a machine
is creating a directory, which is what the installer does; no shared file is
edited, so two machines enrolled independently never conflict.

## Outputs

```text
homeConfigurations.<host>    Home Manager for gusjengis on every machine
nixosConfigurations.<host>   NixOS for each system-managed machine
roleCatalogs.<host>          Installable modules and their values for that host
packages.<system>.install    The installer
packages.x86_64-linux.install-iso  Bootable minimal installer image
apps.<system>.install        `nix run .#install`
checks.<system>              Installer build, installer lint, catalog consistency
```

Home Manager imports `home/features`, then `home/hosts/<host>`. Host files set
role switches such as `desktopEnv.enable`, `dev.enable`, `laptop.enable`,
`gaming.enable`, `gameDev.enable`, `bambu.enable`, and `windowsVm.enable`.

System evaluation is pure. Public SSH keys are committed to `system/keys/` and
read at evaluation time. A missing key must not silently produce a remote system
without authorized access.

## Commands

| Command | Action |
| --- | --- |
| `rehome` | Activate this machine's Home Manager output from `/etc/nixos` |
| `rebuild` | Activate this machine's NixOS output from `/etc/nixos` |
| `sync-repos` | Sync repositories selected by this machine's feature roles |
| `update` | Fast-forward `/etc/nixos`, sync repositories, rebuild, then rehome |
| `refresh-hardware` | Re-probe this machine's hardware and overwrite its `facter.json` |

`update` uses a deployment revision marker so failed deployments retry.
It also shares a lock with Home Manager activation, preventing activation from
starting another activation through the user update service.

## Hardware Detection

Each host's `system/hosts/<host>/facter.json` is a committed snapshot from
`nixos-facter`, not something generated during evaluation. `system/modules/hardware/facter-policy.nix`
reads that snapshot at eval time to set `lib.mkDefault` values (GPU vendor,
microcode, Bluetooth, fingerprint reader, laptop battery support, and so on),
so it reacts immediately to policy changes but has no way to know the
snapshot itself is stale.

**Nothing regenerates this automatically.** A rebuild only re-evaluates
whatever report is already committed; it cannot probe live hardware, both
because Nix evaluation is pure and because the probe needs root. After any
hardware change (new GPU, added/removed drive, dock/undock, new USB
peripheral you want detected), run `refresh-hardware [host]` yourself, review
the diff it prints, then `rebuild`.

The updater never pulls a dirty `/etc/nixos` checkout. Application-written
configuration therefore remains visible for review instead of being overwritten.

Home Manager is standalone and never evaluates a NixOS configuration, so it
cannot read `repo.hardware.detected`. It reads the same committed report
directly through `system/install/lib/facter.nix`, which is also what the
installer uses. That shared helper is why `laptop.enable` has one definition
rather than three.

Portable hardware is detected from the SMBIOS chassis type, not from
`hardware.system.form_factor`. Facter reports `form_factor` as `laptop` on
every machine in this fleet, the desktops included, so it cannot distinguish
anything.

## Installation

`nix build .#install-iso` builds the live installer image. Boot it and run
`sudo install` to install a new machine end to end. See
`INSTALL.md` for using it; this is how it fits together.

The ISO module at `system/install/iso.nix` adds the installer and a Tailscale
daemon with in-memory state. No credentials are embedded. Before partitioning,
the installer clones secrets into a temporary private directory, joins the
tailnet, verifies Omega's pinned SSH key and cache, and applies remote-only Nix
settings to both the system and Home Manager builds. Failed access aborts before
erasing the disk; cleanup logs out the temporary identity and deletes the keys.

The installer does not know what modules exist. `system/install/catalog.nix`
walks the evaluated NixOS and Home Manager option trees and keeps boolean
`*.enable` options that are declared inside this repository and outside
`system/hosts/` and `home/hosts/`. The first filter removes the roughly sixteen
thousand upstream options; the second removes machine-specific modules, which
is why `immich.enable` is alpha's business and never a question asked of some
other machine.

The value reported for each module is the *effective* value for the host being
installed, not the option's declared default. For a new machine that is what
the shared modules default to. For a machine already on the roster it is that
machine's current configuration, which is how reinstalling one offers its own
settings back without a special case.

`system/install/roles.nix` holds only what the module system has nowhere to
put: categories, short flag names, and summaries written for someone choosing
at install time. All of it is checked against the discovered modules, so an
entry naming an option that no longer exists fails evaluation rather than
quietly describing something gone. `nix flake check` evaluates every host's
catalog, so that check runs without installing anything.

New machines are partitioned by Disko from a named layout in
`system/install/lib/layouts.nix`, and have no generated
`hardware-configuration.nix`: Disko supplies `fileSystems` and Facter supplies
the kernel and initrd modules. The machines that predate the installer keep
theirs, and their `disk.nix` files stay `disko.enableConfig = false`,
describing a layout that already exists rather than one to create.

Home Manager is built and activated before the installer reboots. The installer
uses `nixos-enter`, a temporary daemon for the target store, and the prebuilt
activation package so the first tty1 login already sees the complete shell and
starts Hyprland. It then synchronizes the repositories selected by the Home
Manager configuration and records the deployed revision, preventing the first
user-session update from rebuilding an environment that is already active.
`system/modules/software/first-boot.nix` is only an interrupted-install recovery
path; successful activation removes the marker that enables it.

## Editable Configuration

Editable application configuration uses
`config.lib.file.mkOutOfStoreSymlink`. Links under the user's home resolve into
`/etc/nixos/home/features`, allowing edits and application-written settings to
land directly in the repository without rebuilding. Applications that replace
files atomically receive a directory link instead of individual file links.

Store-backed files are reserved for configuration intended to be immutable.
Scripts required by systemd units are packaged with `writeShellApplication` and
explicit runtime dependencies.

The checkout remains Gus-owned. Granting another user write access would also
let that user modify Nix later evaluated by root.

Flakes omit untracked files. Stage new modules and assets before evaluating or
activating them. Home Manager also refuses to replace unmanaged real files or
dangling links at managed destinations.

## Secrets

Secrets live in the private repository at `~/.config/secrets`. Runtime shell
code reads them directly; Nix must not read secret values because evaluated
inputs become world-readable store objects. The fleet public SSH key is the
only deliberate evaluation-time exception.

## Build Farm

Omega builds for the fleet and serves its own store back as a signed binary
cache. `system/hosts/omega/nix_build_farm_server.nix` owns server settings;
`system/modules/software/nix_build_farm_client.nix` owns shared client settings.
Every machine except Omega defaults to `nixBuildFarm.client.enable`.

Clients reach it over MagicDNS at `omega.tail29bd65.ts.net`. Builds go over SSH
as a dedicated `nixremote` account, authenticated with the existing fleet key
and listed in Omega's `trusted-users`. Substitution goes over plain HTTP to
Harmonia on port 5000, opened on `tailscale0` only; the transport is WireGuard
rather than TLS, and every path is still verified against the committed
`omega-1` public key, so an unauthenticated cache on the tailnet is safe to
trust. Omega emulates `aarch64-linux` through binfmt and QEMU, which is what
lets it build for the Asahi laptop.

`cache.nixos.org` stays authoritative for upstream packages. Harmonia reports
priority 50 against upstream's 40, and Nix sorts substituters by that number, so
the private cache is only asked for paths upstream does not have.
`builders-use-substitutes` is on, so Omega fetches a build's dependencies itself
instead of receiving them over a domestic uplink.

Build parallelism is four jobs of six cores, which saturates Omega's 24 threads
and leaves each job around 8 GB of its 32 GB. Retention is continuous rather
than scheduled: the daemon collects when free space falls under 50 GiB, up to
200 GiB free, so artifacts survive until the disk is actually wanted. A monthly
sweep drops profile generations older than 30 days, which is what stops old
generations from pinning closures the pressure collection may not touch. That
sweep also collects, so cache artifacts live until the next sweep or the next
squeeze, whichever comes first.

When Omega is unreachable, an uncached derivation builds locally and an upstream
path still comes from `cache.nixos.org`. Two settings make that true rather than
aspirational. `fallback = true` is load-bearing: Nix's default is to treat an
unreachable substituter as a fatal error, and the private cache is consulted
exactly for the paths that need building, so without it every uncached build on
every client fails the moment Omega is off. `ConnectTimeout 5` for Omega in
`ssh_config` bounds the wait for a builder whose packets are black-holed rather
than refused, which was otherwise the kernel's full TCP timeout. Measured cost
of a build while Omega is down, with both in place, is about twenty seconds of
retries once per command; without them it was a hard failure and two minutes
forty of stalling respectively. Nothing about the local store or configuration
is damaged either way, and no generation is affected.

Omega's private signing key lives at `/var/lib/nix-cache/cache-priv-key.pem`,
outside the store and outside this repository. `nix-cache-key.service` generates
one if the file is missing and then refuses to let Harmonia start unless it
matches `nixBuildFarm.publicKey`, printing the mismatch. A reinstalled Omega
therefore fails loudly instead of serving paths no client will accept; restore
the key from `~/.config/secrets/nix-cache/` or adopt the printed public key and
rebuild the clients.

## Updates And Rollback

Automatic updates rebuild NixOS first and activate Home Manager only after the
system succeeds. Deployment revision advances only after both succeed.

Previous NixOS generations remain available from the boot menu. Previous Home
Manager generations can be activated with:

```bash
home-manager generations
/nix/store/<previous-home-manager-generation>/activate
```

## Adding Configuration

Add a machine to `system/hosts/default.nix`, create its NixOS files under
`system/hosts/<host>`, and create its Home Manager settings under
`home/hosts/<host>`.

Add Home Manager features under `home/features/<family>/<name>` and import them
from the family module. Keep each feature's declarations, scripts, units,
configuration, and assets together.

Add shared NixOS modules under `system/modules/<area>` and import them from
`system/modules/default.nix`. New enable options should default to behavior that
preserves existing hosts.

## Pending Fleet Work

Dragonflylane remains in its separate `nixos-dragonflylane` repository. It is
already on the tailnet, but SSH access must be established before its NixOS and
Home Manager configuration can be folded into this repository as a ninth host.
