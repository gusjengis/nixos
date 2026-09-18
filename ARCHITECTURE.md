# Architecture

This repository is the complete NixOS and Home Manager configuration for eight
machines. Its canonical checkout is `/etc/nixos`, owned and updated by
`gusjengis`. Machines should be reproducible from this repository plus the
private secrets repository; manually installed software is considered a bug.

## Layout

```text
flake.nix                 inputs, pins, and all flake outputs
system/
  hosts/default.nix       machine roster and machine-id mapping
  hosts/<host>/           NixOS and hardware configuration per machine
  modules/                shared NixOS modules
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

Each roster key is the machine's NixOS hostname and Tailscale node name.
`rehome` and `rebuild` use that hostname to select the flake output and also
accept an explicit host name for fresh installations:

```bash
rehome t480s
rebuild t480s
```

## Outputs

```text
homeConfigurations.<host>    Home Manager for gusjengis on all eight machines
nixosConfigurations.<host>   NixOS for each system-managed machine
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

`update` uses a deployment revision marker so failed deployments retry.
It also shares a lock with Home Manager activation, preventing activation from
starting another activation through the user update service.

The updater never pulls a dirty `/etc/nixos` checkout. Application-written
configuration therefore remains visible for review instead of being overwritten.

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
