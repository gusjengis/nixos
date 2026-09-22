# alpha server roadmap

Context dump from the initial server setup session (Jul 2026), so future work can
pick up where we left off.

## The machine ("alpha")

- i7-6700K (4c/8t), 32 GB RAM, GTX 1080 8GB (nvidia legacy_580 driver, CUDA works)
- 1 TB NVMe (ext4, `/`) — ~845 GB free, use for scratch/media/VMs/CI, replaceable data
- 2x 500 GB SATA SSD, btrfs RAID1 at `/data` (~465 GB usable, zstd, monthly scrub
  already enabled in alpha's `/etc/nixos/configuration.nix`) — use for anything
  that must survive a disk failure
- Blu-ray burner (WH16NS40) — usable for ripping discs (MakeMKV) or optical backups
- Tailscale hostname `alpha`, FQDN `alpha.tail29bd65.ts.net`
- Docker + libvirt available; tailnet-only exposure policy (nothing public)

## Done so far

### software/data_drive.nix — shared network drive
- alpha exports `/data` over NFSv4.1/4.2, tailnet only (2049 open on tailscale0 only)
- `all_squash,anonuid=1000,anongid=100`: every write from every machine lands as
  gusjengis:users — single-owner cloud drive semantics
- every other machine automounts `alpha:/data` at `/data` by default
  (`dataDrive.client.enable` defaults on; hard mount + automount + nofail)

### software/nextcloud.nix — web UI for the drive
- Nextcloud 33, native module; state/db/secrets on the mirror in `/data/.services`
- whole drive exposed as a `/data` folder via files_external, sharing enabled
- nextcloud sees the drive through a bindfs view at `/mnt/nextcloud-data`
  (maps gusjengis<->nextcloud so both web and NFS writes stay compatible);
  `.services` is masked with an empty tmpfs inside that view
- admin login: `gusjengis`, password: `sudo cat /data/.services/secrets/nextcloud_admin_pass`
- postgres datadir lives on `/data/.services/postgres` — future services (Immich)
  should reuse this postgres instance so their DBs are on the mirror too

### home-manager side
- thunar bookmark for `/data` ensured on all machines (programs/file_explorer.nix)

## Loose ends

- [ ] **Tailscale serve approval**: HTTPS for Nextcloud is blocked on a one-time
      tailnet admin approval. Visit
      https://login.tailscale.com/f/serve?node=nFrxzKJ87421CNTRL — the
      `tailscale-serve-nextcloud` service retries and will come up on its own
      afterward, serving https://alpha.tail29bd65.ts.net. Until then HTTP
      (`http://alpha/`) works on the tailnet.
- [ ] Other machines get the NFS client + bookmark on their next update/rebuild;
      verified on pc only so far.
- [ ] Consider a `/data` directory convention doc: `shared/` exists; `photos/`
      (Immich) and `.services/` (app state) planned.

## Future phases (agreed direction, not yet built)

### Immich (photos) — on the mirror
- native `services.immich` module; data under `/data/photos` or `/data/.services/immich`
- point it at the existing postgres on `/data/.services/postgres`
- machine-learning with CUDA on the GTX 1080 (smart search, faces)
- mobile app auto-backup replaces Google Photos; tailnet-only

### Jellyfin (media) — on the NVMe
- native module; media library on NVMe (replaceable), metadata on `/data/.services`
- GTX 1080 NVENC for transcodes (better than the 6700K's QuickSync)
- rip discs with MakeMKV via the Blu-ray drive

### Voice/AI stack (Alexa replacement, feeds Home Assistant on t470)
- `services.ollama` with CUDA — 8 GB VRAM fits ~7-8B models quantized
- wyoming-faster-whisper (GPU) for STT + wyoming-piper for TTS;
  HA voice pipeline on t470 points at these over the tailnet
- bigger custom project later: openclaw-style agent harness bridging the LLM,
  Home Assistant, and the tailnet
- transcription quality was the driver for using the 1080 here

### CI for work (Unity Android builds)
- project lives on GitHub -> self-hosted GitHub Actions runner module
- build caches + workspaces on NVMe (huge, replaceable)
- open questions: Unity version/license activation on a headless runner,
  Android SDK/NDK provisioning, whether to containerize the runner

### Backups (RAID is not backup)
- offsite: restic -> Backblaze B2 for `/data` (cheap, encrypted)
- btrfs snapshots (btrbk/snapper) on `/data` for oops-recovery;
  scrub already runs monthly
- optionally: other machines back up TO `/data` (restic/borg server)

### Maybe later
- tailnet-wide status dashboard (Beszel/Glance/Homepage) — user leaning toward
  running it elsewhere, agents on each machine
- AdGuard Home DNS for the LAN
- game servers (RAM is plentiful)

## Conventions / how to work on this repo

- one module per service in `software/`, `<name>.enable = lib.mkEnableOption`,
  import + `lib.mkDefault` default in `default.nix`, enable per host under
  `system/hosts/<host>/configuration.nix`
- rebuild with `rebuild`; activate Home Manager with `rehome`
- declarative only; secrets live outside the repo (e.g. `/data/.services/secrets`,
  generated on first run by oneshot units)
- anything stateful that matters goes under `/data/.services` with
  `RequiresMountsFor=/data` on its units
- commit + push here, other machines pull + rebuild via the update-on-boot flow
