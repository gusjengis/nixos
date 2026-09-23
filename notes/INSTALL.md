# Installing a machine

One command, from a stock NixOS ISO, start to finish. When it is done, reboot
and the machine is on the tailnet with the desktop up and the repositories
cloned. There is no second step to remember.

## What you need

- A NixOS installer ISO, any recent one. The graphical and minimal images both
  work; nothing from the ISO's own installer is used.
- A network connection.
- A GitHub personal access token with `repo` scope. This is the only credential
  the installer needs, and it is what makes the machine finish itself: it
  clones the private secrets checkout, which carries the SSH keys, the SMB
  credentials, the API keys, and the Tailscale auth key.
- UEFI firmware. The shared configuration installs GRUB in EFI mode, and the
  installer refuses to start on a machine booted in legacy/CSM mode rather than
  producing something that will not boot.

## Interactive

Boot the ISO, connect to the network with `nmtui`, then:

```bash
sudo nix --extra-experimental-features 'nix-command flakes' \
  run github:gusjengis/nixos#install
```

Six tabs, in the order the decisions are made:

| Tab | Decision |
| --- | --- |
| Host | The roster key. Also the NixOS hostname and the Tailscale node name. |
| Disk | Which whole disk to erase. Shows model, size, and current partitions. |
| Modules | What to turn on, grouped into toggleable categories. |
| Accounts | Passwords for `gusjengis` and root, or one for both. |
| Secrets | The GitHub token, and whether to push the new machine's files. |
| Review | Everything at once, then Install. |

Every module starts at whatever the configuration already defaults to, so an
untouched Modules tab installs a sensible machine. A category header turns
everything under it on or off at once; the modules stay individually
toggleable underneath.

Nothing about hardware is asked. Graphics, CPU microcode, Bluetooth, the
fingerprint reader, and whether the machine is a laptop are all read from the
Facter probe the installer runs.

## Non-interactive

Supply every answer and add `--yes`. The interface never opens. This is the
shape to use for several machines in a row.

```bash
sudo nix --extra-experimental-features 'nix-command flakes' \
  run github:gusjengis/nixos#install -- \
  --host t490 \
  --disk /dev/nvme0n1 \
  --password 'the-password' \
  --github-token ghp_xxxxxxxx \
  --yes
```

A headless machine, with the whole desktop category off:

```bash
  --host shed --disk /dev/sda --password '...' --github-token ghp_... \
  --group-desktop=false --group-printing=false --yes
```

Individual modules override their category, whichever order the flags appear
in:

```bash
  --group-development=false --vms=true
```

To see every module, its flag, its category and its default:

```bash
nix run github:gusjengis/nixos#install -- --list-modules
```

`--yes` refuses to start when an answer is missing, naming all of them at once,
rather than erasing a disk and then discovering it has no password to set.

## What it does

1. Shallow-clones this repository to `/tmp/nixos-install`.
2. Probes the hardware with `nixos-facter`.
3. Writes the new machine's files and evaluates them, which is where the module
   list and its defaults come from.
4. Asks, or takes the answers from flags.
5. Partitions the disk with Disko and installs NixOS.
6. Places the repository at `/etc/nixos`, owned by `gusjengis`.
7. Clones the secrets checkout into the new home directory.
8. Builds the Home Manager closure into the new system's store.
9. Sets both passwords.
10. Commits the new machine's files and pushes them.

Home Manager is *activated* on the first boot rather than during installation,
by `nixos-first-boot.service`. Its closure is already built by then, so this is
a matter of linking a profile, not compiling a desktop. The unit is conditioned
on `/var/lib/nixos-install/pending-home-manager` and does nothing on any machine
that was not just installed. If it fails, the marker stays and the next boot
tries again.

## Reinstalling a machine that already exists

Give an existing roster key:

```bash
  --host t480s --disk /dev/nvme0n1 ...
```

Its catalog is evaluated instead of a new machine's, so every module defaults
to what that machine currently runs. Anything not changed stays as it was.

Note that a machine installed before the installer existed carries a generated
`hardware-configuration.nix`. Reinstalling removes it, because Disko then owns
the filesystems and two definitions of the root filesystem is a conflict.

## Rehearsing

`--dry-run` resolves every decision, writes the machine's files, prints them,
and touches no disk. It does not need root if you also accept that hardware
detection will report nothing:

```bash
nix run github:gusjengis/nixos#install -- \
  --dry-run --yes --host test --disk /dev/sda \
  --password x --github-token y
```

`--source /etc/nixos` installs from a checkout on disk instead of cloning,
which is how to test a change to the installer before pushing it.

## Apple Silicon

Not supported by this flow. `mac` needs the Asahi installer to partition
around macOS first, and its `disk.nix` records that layout for recovery rather
than as something to create. Install it by hand.

## If something goes wrong

Nothing is touched before the disk confirmation. After it, the machine is
being installed and the failure is recoverable by running the installer again:
every step either completes or leaves the disk in a state the next run will
repartition anyway.

Two failures are deliberately not fatal, because the machine is already
installed and working by the time they can happen:

- The Home Manager pre-build. First boot builds it instead, which needs a
  network connection then.
- The push. The commit is in `/etc/nixos`; push it later.

A warning about a missing `TAILSCALE_AUTH_KEY` matters on a headless machine:
it means nothing will join the tailnet and there will be no way in.
