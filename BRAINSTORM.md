# Configuration Brainstorm

Repository-wide review of NixOS, Home Manager, host modules, services, deployment tooling, and QuickShell. Recommendations favor narrow, testable changes over broad rewrites.

## Executive Summary

This repository already has strong foundations: centralized host construction, clear system/home separation, pinned flake inputs, editable out-of-store application configuration, host-specific service modules, and an unusually capable QuickShell desktop. Main opportunity is not adding more software immediately. It is tightening trust boundaries, making host roles explicit, adding recovery guarantees, and turning existing conventions into automated checks.

Recommended order:

1. Close critical trust-boundary problems: root-sourced files, writable `/` SMB export, autologin, passwordless sudo, and Wi-Fi credentials in process arguments.
2. Implement tested offsite backups before adding more stateful services.
3. Restrict network services by interface and host role; document intentional public exposure.
4. Fix repo-sync failure reporting and destructive destination recovery.
5. Add flake checks for every host, formatting, linting, Python tests, and selected integration tests.
6. Refine QuickShell reliability and accessibility before expanding its feature set.
7. Introduce explicit host roles and derive both NixOS and Home Manager defaults from them.

## What Is Working Well

- Host inventory is centralized in `system/hosts/default.nix`, giving the fleet one obvious roster.
- NixOS and Home Manager concerns are separated while still composed from one flake.
- Editable application configuration uses Home Manager out-of-store symlinks where live updates matter.
- Stateful server applications have local host modules instead of one giant configuration.
- QuickShell separates QML presentation from Python command bridges and instantiates shared services once for multiple screens.
- Remote application launch validates host and desktop-entry inputs before constructing commands.
- Usage credential files use private directories, locks, atomic replacement, and explicit modes.
- Wallpaper state and generated colors are atomically replaced.
- Existing Python tests provide a useful base, especially around remote apps and usage handling.

## Security And Trust Boundaries

### Immediate fixes

#### Stop sourcing user-writable files as root

`system/modules/software/tailscale.nix`, `system/hosts/t470/joshs_mass.nix`, and `system/hosts/t470/zone_configurator.nix` source files under `/home/gusjengis` from root services. Credential files then become executable shell code. A compromised user process or accidental edit can execute arbitrary commands as root.

Better pattern:

- Use systemd `EnvironmentFile=` only for strict `KEY=value` data.
- Prefer `LoadCredential=` for service secrets.
- Move secret material to root-owned runtime paths populated by sops-nix or agenix.
- Keep service commands static and pass credentials through files or file descriptors.

#### Replace whole-root writable SMB export

`system/hosts/pc/windows-vm.nix` exports `path = "/"` writable and forces operations to the main user. A compromised Windows guest can modify personal files, secrets, and this Nix repository. Future privileged rebuilds can turn those modifications into root execution.

Export a dedicated directory, read-only by default. Add separate narrow writable shares only where required. Consider virtiofs for local VM file exchange, with explicit paths and ownership.

#### Remove fleet-wide console autologin and unrestricted passwordless sudo

`system/modules/default.nix` combines getty autologin with passwordless wheel sudo. Physical access becomes immediate root access, especially risky on laptops.

Use normal login and authenticated sudo. If automation needs privilege, grant passwordless access only to exact commands through a dedicated group or polkit rule.

#### Harden SSH explicitly

Set stable policy rather than inheriting upstream defaults:

```nix
services.openssh.settings = {
  PasswordAuthentication = false;
  KbdInteractiveAuthentication = false;
  PermitRootLogin = "no";
  X11Forwarding = false;
};
```

Add host-specific `AllowUsers`. Make missing authorized-key files an evaluation failure instead of silently omitting keys in `system/modules/users.nix` and `system/hosts/alpha/configuration.nix`.

#### Narrow agent filesystem access

`home/features/agents/opencode/opencode.json` broadly allows external reads under `/` and home. Add explicit deny rules before broad allows for SSH keys, secret stores, browser profiles, authentication files, service databases, and `/run/credentials`.

### Network exposure

- Bind Parakeet ASR to localhost or `tailscale0`, add authentication, cap body size/concurrency, and set systemd memory limits.
- Restrict NFS exports to known tailnet nodes or ACL tags instead of all `100.64.0.0/10`.
- Open Home Assistant, Matter, Music Assistant, Zone Configurator, KDE Connect, and streaming ports only on trusted interfaces and relevant hosts.
- Reconcile active Tailscale Funnels with `server_roadmap.md`, which says nothing should be public.
- Add one generated exposure inventory listing listener, host, interface, authentication, public/tailnet/LAN scope, and data sensitivity.

## Reliability And Recovery

### Backups are highest-value missing feature

RAID and synced Git repositories do not protect application data, databases, secrets, or accidental deletion. Implement:

- Encrypted restic or Borg backups to an offsite target.
- Local filesystem snapshots for fast recovery.
- PostgreSQL-consistent dumps for Nextcloud and Immich.
- Separate policies for irreplaceable data, reproducible media, and caches.
- Retention, failure alerts, and a quarterly restore drill.
- A documented bootstrap path for recovering secrets and rebuilding a host from scratch.

Expose backup age and last restore-test date in monitoring, not only service success.

### Fix repo-sync semantics

`home/features/repo-sync/scripts/sync-repos.sh` records child failures but exits successfully, preventing `update.sh` from entering its failure path. Return nonzero after aggregation. Configure retry behavior in systemd rather than lying about success.

`clone-repo.sh` can recursively delete a non-Git destination based on repository basename. Safer behavior:

1. Validate destination is below an approved root.
2. Reject empty names, `.`, and `..`.
3. Rename conflicts to a timestamped quarantine directory.
4. Never use `sudo rm -rf` for automatic recovery.
5. Report manual resolution steps.

### Make deployments promotable

Current automatic pull-to-rebuild path converts remote Git updates into privileged deployment. Add a small promotion boundary:

- Fetch automatically, but deploy only revisions passing checks.
- Require signed commits or tags for unattended deployment.
- Persist last attempted, last successful, and rollback revisions.
- Send deployment output to journald and expose failure status.
- Keep one command for explicit promotion and one for rollback.

### Service lifecycle cleanup

- Add `ExecStop` cleanup for Nextcloud and UltraBridge Tailscale Serve/Funnel state, matching Immich.
- Replace recursive Immich `chown -R` at every start with one-time migration or tmpfiles ownership.
- Rotate remote-app logs and battery history rather than rewriting or accumulating indefinitely.
- Add health checks for data mounts, databases, containers, Tailscale routes, and public endpoints.

## Architecture And Maintainability

### Model capabilities as roles

Shared defaults currently pull workstation behavior into servers and headless hosts. Define composable roles such as:

- `base`: users, SSH, Nix policy, time, logging.
- `desktop`: graphics, audio, portals, GVFS, UDisks, fonts.
- `laptop`: power management, battery history, Wi-Fi, suspend policy.
- `server`: hardened SSH, monitoring, backups, no GUI closure.
- `containerHost`: Docker/Podman and storage policy.
- `gaming`: Steam, Wine, controllers, streaming.
- `office`: office mounts and site-specific network behavior.
- `developer`: compilers, editors, agents, language toolchains.

Store role sets beside host metadata in `system/hosts/default.nix`. Pass them to both NixOS and Home Manager, preserving narrow host overrides. This removes repeated booleans and makes fleet intent visible in one table.

### Reduce unconditional Home Manager closure size

Gate Chromium, Thunar, LibreOffice, Wine, agents, and other large packages by role. Headless hosts should not inherit desktop applications merely because they share one user profile.

### Centralize identity without over-generalizing

Username, home path, UID/GID, repository root, and time zone occur in several modules. Add a small fleet/user record passed through `specialArgs`; derive paths and ownership from it. Avoid building a generic multi-user framework unless a second real user requires it.

### Simplify imports and defaults

- Import hardware configuration either in `flake.nix` or each host, not both.
- Default office network drives to disabled and enable them on office clients.
- Remove global `allowBroken`; scope insecure package exceptions to exact features with reason and review date.
- Make kernel policy host/role-specific rather than globally pinning 6.12 forever.
- Mark source-only flake inputs `flake = false` and use `follows` where compatibility permits.
- Pin mutable OCI images by digest and automate reviewed updates.

## Reproducibility And Testing

Add `formatter` and `checks` outputs to `flake.nix`:

- Evaluate every NixOS and Home Manager host.
- Run `nixfmt --check`, statix, and deadnix.
- Run ShellCheck over maintained scripts.
- Run Ruff and Python unit tests.
- Verify generated configuration paths and required public keys exist.
- Add NixOS VM tests for missing credentials, absent `/data`, SSH policy, and service startup ordering.

Pin Parakeet ASR into a reproducible OCI image instead of installing apt and live Git dependencies at runtime. Publish it to a trusted registry/cache and reference an immutable digest.

Add scheduled dependency review rather than broad mutable tags such as `stable` and `latest`. Renovate can open digest-update changes without deploying them automatically.

## Operations And Observability

- Configure automatic Nix garbage collection and store optimization with a retention policy.
- Add a binary cache such as Attic for custom Hyprland and large fleet closures.
- Persist deployment status: host, revision, duration, result, and rollback target.
- Alert on stale backups, failed timers, degraded arrays/filesystems, expiring certificates, low disk space, and unexpectedly public listeners.
- Build a small fleet dashboard from systemd/Prometheus data rather than inventing service-specific status files.
- Add `nixos-rebuild dry-activate` or equivalent checks before switching.
- Generate architecture and exposure tables from host metadata to prevent documentation drift.

## Useful New Programs And Services

Candidates with clear fit:

- `sops-nix` or `agenix`: declarative secret delivery with proper ownership.
- `restic` plus `resticprofile`: encrypted backup policy and retention.
- `prometheus-node-exporter` and `smartctl_exporter`: fleet/storage telemetry.
- `healthchecks` or a self-hosted equivalent: timer and backup dead-man monitoring.
- `attic`: shared Nix binary cache.
- `nix-index-database`: fast command-not-found and package lookup.
- `nh`: clearer rebuild output and generation management, if `rehome` does not already cover this role.
- `nvd`: generation closure diffs before activation.
- Renovate: flake input and OCI digest update proposals.
- `sbctl`: Secure Boot enrollment for suitable machines, after recovery keys and rollback are tested.
- `systemd-creds`: service-local runtime credentials even before full secret-management migration.

## QuickShell Deep Dive

QuickShell deserves focused refinement. It already behaves like a custom desktop product, not a decorative bar. Preserve that advantage by improving correctness, keyboard use, responsiveness, and shared interaction rules before adding many more widgets.

### Immediate correctness and privacy fixes

#### Keep Wi-Fi passwords out of argv

Password flow currently crosses `Wifi.qml`, `SystemControlsService.qml`, and `system-controls.py` as a process argument before Python forwards it to `nmcli` stdin. Process arguments can be inspected by other processes under common conditions.

Send the password directly over stdin to a managed process, through a private pipe, or implement a NetworkManager secret agent. Never include it in `Process.command`.

#### Serialize wallpaper preview and apply

`WallpaperPicker.qml` launches detached previews and final apply without cancellation or generation checks. An old `matugen` preview can finish after final selection and overwrite colors or wallpaper.

Use one managed preview job with a monotonically increasing generation token. Cancel or ignore stale completions. Cache generated palettes by wallpaper path, modification time, and desired scheme. Final apply invalidates all preview generations.

#### Match expected cancel behavior

Change wallpaper picker keys:

- `Escape`: restore original and close.
- `Return` or `Space`: apply and close.
- `R`: random choice.
- Display filename, position, and concise key hints.

#### Follow focused monitor

Wallpaper picker resolves focused Hyprland monitor before opening; launcher does not. Apply the same screen selection in every launcher `open()` call.

#### Normalize open Wi-Fi state

Normalize empty security values and `--` in Python into explicit `secured: false`. QML should not infer security from arbitrary non-empty strings.

### Responsive layout

Current bar independently anchors left, center, and right areas. Ten numbered workspaces plus special workspaces can collide with clock and status controls.

Add measured adaptive behavior:

1. Preserve active and occupied workspaces.
2. Hide empty workspaces under width pressure.
3. Put special workspaces into an overflow chip.
4. Collapse low-priority status modules into one control-center button.
5. Center clock within remaining space, not absolute screen center.
6. Define compact, normal, and wide breakpoints.

Clamp all popups to screen work area and scroll content internally. Test laptop, portrait, scaled, and mixed-DPI monitors.

### Accessibility and interaction contract

Most controls use `Rectangle` plus `MouseArea`; shared buttons and sliders disable focus. Introduce one consistent contract:

- Tab focus and visible focus rings.
- Enter/Space activation and arrow adjustment.
- `Accessible.role`, `name`, `description`, `checked`, and value metadata.
- Tooltips for icon-only actions.
- Minimum 40-44 px hit region, even when visible bar element is smaller.
- Confirmation for forget/remove actions.
- Shared reduced-motion setting.
- Minimum body-text size around 12-13 px at normal scale.

### Theme improvements

Current generated colors target opaque surfaces, then QuickShell applies substantial transparency over arbitrary wallpaper content. Effective text contrast becomes unpredictable.

Suggested theme policy:

- Keep bar subtly translucent.
- Keep popups and launcher 88-96% opaque.
- Clamp generated colors to safe tonal ranges.
- Use one explicit UI family, such as Iosevka Aile or Inter, rather than environment-dependent `sans-serif`.
- Reserve monospace for numbers, shortcuts, hostnames, and telemetry.
- Add high-contrast and reduced-transparency options.
- Reuse compositor border width/radius in launcher as existing popups do.
- Pair Nerd Font glyphs with labels or tooltips.

### Performance and architecture

- Consolidate three permanent launcher instances into one launcher with a mode property.
- Poll Wi-Fi/Bluetooth while relevant popup is open; use D-Bus events for background state when practical.
- Avoid serial `bluetoothctl info` calls for every known device every 15 seconds.
- Load Hyprland appearance at startup and on config reload rather than three processes every 10 seconds.
- Give Wi-Fi, Bluetooth, and brightness independent action channels instead of one global busy process.
- Extract only genuinely repeated popup frame/header/error/row primitives; avoid a speculative UI framework.
- Document why some Python scripts are mutable repository paths while `remote-apps.py` is copied into a store derivation.

### Launcher improvements

For an empty query, frequency and recency should lead. For a non-empty query, exact/prefix/fuzzy match should lead, with usage as tie-breaker. Merge apps, projects, actions, and web into one scored model while retaining subtle type labels.

Useful providers:

- Active Hyprland keybindings and help.
- Calculator and unit conversion.
- Clipboard history with sensitive-item exclusion.
- Window and workspace switching.
- Quick toggles and system actions.
- SSH/remote application launch with host health.
- Recent files and projects.
- URL encoding, UUIDs, timestamps, and small text transforms.

### New QuickShell functions

- Unified control center for sound, brightness, Wi-Fi, Bluetooth, media, DND, battery, and power profile.
- Media capsule with player selection, album art, seek, and output-device action.
- Privacy indicators for microphone, camera, screen sharing, and remote Waypipe sessions.
- Agenda view combining month, next events, weather, and travel time.
- Notification grouping, per-app mute, DND schedules, and temporary snooze.
- Remote-host panel showing reachability, latency, generation compatibility, running remote apps, and disconnect action.
- Wallpaper favorites, search, history, per-monitor assignment, palette preview, and lock-screen synchronization.
- Adaptive profiles for laptop, desktop, gaming, presentation, and remote sessions.
- Power menu with explicit lock, suspend, reboot, shutdown, and inhibition state.

### QuickShell concept directions

Three 3840x2160 concept images are stored in repository root as editable SVGs and rendered PNGs.

#### Aurora Command Deck

Image: `quickshell-concept-aurora.svg`

Evolutionary direction. Retains top bar and translucent atmosphere while improving structure. Adaptive workspaces sit left, media and clock center, privacy/status right. Centered command deck merges apps, projects, commands, and web. Unified control center replaces disconnected popups. Cool blue and mint accents sit on high-opacity navy surfaces.

Best if current design should mature without changing its basic spatial model.

#### Obsidian Operations Rail

Image: `quickshell-concept-obsidian.svg`

Dense operator direction. A left rail replaces top bar and keeps screen center clear. Panels expand from rail for remote hosts, network devices, event history, and system telemetry. Strong fit for ultrawide, multi-monitor, server-management, and remote-app workflows.

Best if information density and fleet operations matter more than conventional desktop appearance.

#### Kanso Paper Lantern

Image: `quickshell-concept-kanso.svg`

Calm editorial direction. Replaces continuous bar with three floating islands and uses a paper-like launcher sheet, named workspace tabs, labeled controls, serif headings, moss/indigo/persimmon accents, and generous whitespace.

Best if desktop should feel quieter, warmer, and more distinctive.

## Practical Roadmap

### Week 1: close dangerous gaps

- Remove writable root SMB share.
- Stop root shell-sourcing credentials.
- Remove autologin and global passwordless sudo.
- Harden SSH and network bindings.
- Remove Wi-Fi password from QuickShell process arguments.
- Fix repo-sync exit status and destructive clone recovery.

### Weeks 2-3: recovery and checks

- Deploy encrypted backups and perform first restore drill.
- Add all-host flake evaluation, format, lint, and Python checks.
- Pin mutable containers and Parakeet dependencies.
- Add persistent deployment and backup status.

### Weeks 4-5: QuickShell quality pass

- Fix wallpaper races and focused-monitor launcher placement.
- Add keyboard/focus/accessibility behavior.
- Implement responsive bar overflow and popup clamping.
- Improve search ranking and reduce polling.
- Establish contrast-safe theme and reduced-motion policy.

### Later: deliberate expansion

- Derive configuration from explicit host roles.
- Add unified QuickShell control center, media, privacy, DND, and command help.
- Add cache, monitoring, and generated fleet/exposure documentation.
- Choose one visual concept and prototype it behind a configuration flag before replacing current shell.

## Review Notes

Review was static except for the dedicated QuickShell audit, which also reported 44 passing Python tests, 3 GI-dependent skips, and successful evaluation of `homeConfigurations.pc.activationPackage.drvPath`. Standalone `qmllint` lacked QuickShell/Qt import metadata, so unresolved-import output was not treated as evidence of QML defects.

Working tree contains an unrelated modification in `home/features/agents/opencode/state/model.json`; this report and concept assets do not alter it.
