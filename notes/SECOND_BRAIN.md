# Second Brain: Overview

Capture thoughts from anywhere, clean them up, turn them into linked atomic
notes, and eventually resurface and act on them. This file is the map: what
exists, where it lives, and what runs where.

## Documents

| File | What it is |
|---|---|
| `notes/SECOND_BRAIN.md` | This overview |
| `notes/CAPTURE_PLAN.md` | Capture channels, raw note format, normalization, future channels (phone APK, wake word, car, home device) |
| `notes/DATA_MODEL.md` | Vault data model: folders, thought/entity/relation types, tags, note formats, ownership. Revise as it is used |
| `notes/EXTRACTION_PLAN.md` | How extraction, dedup, linking and semantic search work; build order |
| `notes/QUEST_TRACKING_PLAN.md` | Earlier plan for a task DAG / "active quests" view; relevant to resurfacing |

## Pipeline

```text
desktop dictation ─┐
Supernote tablet ──┼─> Raw/ ──normalize──> Normalized/ ──extract (next)──> Thoughts/ + Entities/
typed in Obsidian ─┘   (record of truth)   (omega)                         (omega, not built yet)
```

All stages meet in one Obsidian vault, synced by Obsidian Sync to every device,
including the headless ones that process it.

## The vault

- Path on every machine: `~/Documents/Obsidian/Notes` (remote vault ID
  `bcf1cb4f72f6417ec375921cbf767004`). Not in git; Obsidian Sync carries it.
- `Templates/Raw Note.md` (in the vault): the single definition of the raw note
  format, executed by Templater in Obsidian and headless by `capture-note`.
- Folders used by the pipeline: `Raw/`, `Raw/Images/`, `Normalized/`, and later
  `Thoughts/`, `Entities/`. Daily notes `00 Daily Notes/` are linked via `day:`.

## Repo files

Capture (desktop side), `home/features/applications/obsidian/`:

| File | Role |
|---|---|
| `default.nix` | Builds `capture-note` and `note-delete`, the headless `obsidian-sync` user service, the Supernote import timer (pc only) |
| `raw-note.mjs` | `capture-note`: renders the vault's raw note template headless and writes the note atomically |
| `capture-import.py` | Imports OCR'd Supernote batches from alpha's outbox into `Raw/` |
| `obsidian-sync.sh` | Logs in and runs `ob sync --continuous` (shared by desktops and omega) |
| `note-delete.py` | `note-delete`: explicit deletion of a raw note and everything generated from it |

Other capture pieces:

| File | Role |
|---|---|
| `home/features/desktop/quickshell/config/Capture.qml` | Dictation popup (CTRL + dictation key) that calls `capture-note` |
| `home/features/applications/handy/` | Handy, local speech-to-text used by the popup |
| `system/hosts/alpha/ultrabridge.nix` | UltraBridge Supernote sync server (+ capture archive patch), Funnel, OCR timer |
| `system/hosts/alpha/capture-process.py` | Renders `Capture.note` pages, OCRs them with Qwen on omega, writes the outbox |
| `system/hosts/alpha/patches/ultrabridge-capture.patch` | Archives every upload of the Capture notebook |
| `system/hosts/alpha/parakeet_asr.nix` | Parakeet ASR server on alpha (for the future phone/car channels) |

Processing, omega:

| File | Role |
|---|---|
| `system/hosts/omega/notes.nix` | omega's vault sync and the normalizer units |
| `system/hosts/omega/note-normalize.py` | `note-normalize`: Raw -> Normalized |
| `system/hosts/omega/configuration.nix` | Enables the pipeline; Qwen context; embedder choice |
| `system/modules/software/ollama.nix` | Ollama module: resident chat model, `ollama.embedders`, preload timers |

## What runs where

### pc (and other desktops)

| Unit | Kind | Does |
|---|---|---|
| `obsidian-sync.service` | user service | Keeps the vault synced without the app (desktops with the secret) |
| `supernote-capture-import.timer` | user timer, 2 min, pc only, needs `/data` | Outbox -> `Raw/` via `capture-note` |
| `capture-note`, `note-delete` | commands | Create a raw note; delete one and its derivatives |
| Handy + Quickshell popup | session apps | Desktop dictation |

pc is a user machine that is often off: nothing downstream depends on it except
the Supernote import (see `CAPTURE_PLAN.md`, chunk 3, for moving that).

### alpha (home server)

| Unit | Kind | Does |
|---|---|---|
| `ultrabridge.service` | service | Supernote sync server; archives Capture uploads to `/data/Supernote/.capture-backups/uploads/` |
| `tailscale-funnel-ultrabridge.service` | service | Public HTTPS for the tablet's sync |
| `supernote-capture-process.timer` | timer, 2 min | Render + OCR new archives into `/data/Supernote/.capture-backups/outbox/<sha>/` |
| `parakeet-asr.service` | service | Speech-to-text on `alpha:8765` (GTX 970), not yet used by a channel |

### omega (inference + processing)

| Unit | Kind | Does |
|---|---|---|
| `obsidian-sync.service` | system service as gusjengis | omega's own vault copy |
| `note-normalize.path` | path unit on `Raw/`, `Raw/Images/` | Starts normalization on any change |
| `note-normalize.timer` | 5 min after last run | Catches edits whose 10-minute quiet period expired |
| `note-normalize.service` | oneshot | Raw -> Normalized |
| `ollama.service` | service, tailnet `:11434` | Model server |
| `ollama-preload.service` / `.timer` | oneshot, every 15 min | Keeps `qwen3.8:27b` resident and warm |
| `ollama-embedders.service` / `.timer` | oneshot, every 15 min | Builds and keeps the Jina embedders resident |

Logs: `journalctl -u <unit>` on the host (`--user` for pc's user units).

## Models (all on omega's Ollama)

| Model | Where | Context | Used for |
|---|---|---|---|
| `qwen3.8:27b` | GPU | 48k | OCR (alpha calls it), normalization, extraction, OpenCode auto-router, wallpaper labels |
| `jina-v5-retrieval` | GPU | 4k | Search (user and Qwen) |
| `jina-v5-matching` | CPU | 4k | Dedup, link shortlists |

RTX 3090 Ti, ~0.9 GB VRAM headroom with all of the above resident.

## Data outside the vault

| Path | Host | What |
|---|---|---|
| `/data/Supernote/.capture-backups/uploads/` | alpha | Every uploaded `Capture.note`, by content hash |
| `/data/Supernote/.capture-backups/outbox/` | alpha (read by pc over `/data`) | OCR batches; `.imported` / `skipped` markers |
| `/var/lib/ollama/models` | omega | Model blobs |
| `~/.config/secrets/obsidian` | each syncing host | Obsidian login (secrets repo) |

## Commands

| Command | Where | Does |
|---|---|---|
| `capture-note [--source S] TEXT` | desktops | Create a raw note |
| `note-delete --latest \| <stem> \| --orphans` | desktops | Delete a raw note and its derivatives, or clean orphans (asks first) |
| `note-normalize [--dry-run] [--force] [stem ...]` | omega | Run or preview normalization |
| `ollama ps` | omega | Which models are loaded, GPU vs CPU |

## Status

- Done: desktop dictation, Supernote capture, typed capture, normalization.
- Next: extraction (`EXTRACTION_PLAN.md` build order, `DATA_MODEL.md` v1).
- Later: semantic search surfaces, resurfacing (digest, active quests), phone
  and car capture, agents that open PRs from notes.
