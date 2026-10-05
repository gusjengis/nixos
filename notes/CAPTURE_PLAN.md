# Capture Channels Plan

Goal: be able to store a thought anywhere, at any time, with as little effort as possible.
Every channel ends up as a raw note in `Raw/` of the Obsidian vault, in one shared format.

## Current State

| Channel | Path | Source value |
| --- | --- | --- |
| Desktop dictation | `CTRL + code:202` -> Handy (local Parakeet) -> `Capture.qml` -> `capture-note` | `desktop-dictation` |
| Supernote notebook | UltraBridge on alpha -> `capture-process.py` (Ollama `qwen3.8:27b` OCR on omega) -> outbox -> `capture-import.py` on pc | `supernote` |
| Typing (phone/desktop) | Obsidian + Templater `Templates/Raw Note.md` | `phone-typed` / `desktop-typed` |

Relevant files:

- Vault `Templates/Raw Note.md`: the only definition of the raw note format
- `home/features/applications/obsidian/raw-note.mjs`: executes the template headless (`capture-note` CLI)
- `home/features/applications/obsidian/default.nix`: `capture-note` wrapper, headless `ob sync` service, Supernote import timer
- `home/features/desktop/quickshell/config/Capture.qml`: dictation popup
- `system/hosts/alpha/capture-process.py`: Supernote OCR; writes body-only `capture.md` + `capture.json` (`created`) per outbox batch
- `home/features/applications/obsidian/capture-import.py`: turns outbox batches into raw notes via `capture-note`
- `system/hosts/alpha/parakeet_asr.nix`: Parakeet TDT 0.6b v3 on `alpha:8765` (GTX 970, no auth)

Remaining problem: Parakeet on alpha has no authentication.

## Target Architecture

```text
phone APK (Quick Tap / wake word / tile / widget / share) ──┐
phone APK in car (wake word, phone mic or car mic)        ──┤
future home device (ESP32 wake word box)                  ──┼─> alpha capture service (tailnet only)
                                                            │     ├─ audio -> /data/Capture/audio/
                                                            │     ├─ Parakeet transcription (alpha:8765, localhost)
                                                            │     └─ render Templates/Raw Note.md -> vault on alpha
desktop dictation (capture-note)                          ──┤                                  │
Supernote pipeline                                        ──┘                                  v
Obsidian (phone/desktop) typing with Templater template ───────────────────────> Obsidian Sync -> all devices
```

## Raw Note Format (canonical)

`Templates/Raw Note.md` in the vault is the single, authoritative definition (the vault is not in git; Obsidian Sync carries it to every device). It is real Templater code, and every channel executes it:

- In Obsidian (typed notes): Templater runs it (folder template on `Raw/`, command "Templater: Create Raw Note").
- In scripts: `capture-note` (`raw-note.mjs`) runs it headless with Node and Templater's own parser, `@silentvoid13/rusty_engine` 0.4.0 (byte-identical to the WASM bundled in Templater 2.18.1), plus moment. No Obsidian, no GUI. Scripts supply only facts; the template decides name, location, frontmatter and body layout.

Current template decides:

- Filename `Raw/YYYY-MM-DD-HHmmss.md`, `-2`, `-3`, ... on collision.
- `created`: local ISO time with offset.
- `day`: `"[[MM-DD-YYYY]]"` link to the daily note (strict midnight, capture time), so raw notes hang off their day in the graph. The template creates the daily note from `Templates/Log Template` via `tp.file.create_new` if missing; daily folder/format are duplicated from `.obsidian/daily-notes.json`. Daily notes are never edited by captures.
- `status: inbox`.
- `source`: `tp.capture.source` when headless, else `phone-typed` / `desktop-typed`.
- Body: captured text at `tp.file.cursor()`.

Known sources: `desktop-typed`, `desktop-dictation`, `phone-typed`, `phone-dictation`, `phone-wake`, `car`, `supernote`, `home`.

### Headless runner contract (`raw-note.mjs`)

- CLI: `capture-note [--source S] [--created ISO] [--vault DIR] [--name-token T] [--attach SRC=NAME ...] [--attach-dir DIR] [TEXT|stdin]`; prints the note path. Empty text writes nothing.
- `tp.capture = { source, text, created, headless: true }`; undefined in Obsidian, so templates use `tp.capture?.…`.
- Clock frozen at `--created` (`moment.now`), so `tp.date.*` describes the capture time. Plain `new Date()` is not frozen.
- Supported `tp`: `tp.date.*`, `tp.file` (`title`, `path`, `folder`, `exists`, `move`, `rename`, `cursor`, `find_tfile` (vault paths), `create_new` (explicit folder required; renders and writes immediately, `name 1` on collision like Obsidian), `content` = "", `tags` = [], `creation_date`, `last_modified_date`), `tp.config`, `tp.frontmatter` = {}, `tp.obsidian` (`Platform` = desktop, `moment`, `normalizePath`), global `moment`. Anything else (`tp.system`, `tp.web`, `tp.app`, `tp.user`, `tp.hooks`, ...) throws, so the capture fails rather than writing a wrong note. Guard such code with `tp.capture`.
- Rendering starts at `Raw/Untitled.md`; `tp.file.move`/`rename` set the final path.
- `--name-token`: replaced with the final note name in the output and attachment names (Supernote page images). Attachments are copied before the note appears.
- Atomic, no-clobber write (dotfile in vault root + `link()`); if another capture took the name, the template is rendered again.
- Difference from Obsidian: Templater re-serializes frontmatter through Obsidian's YAML stringifier after rendering; the runner writes the rendered text verbatim.
- Templater quirk: on file creation it executes `<% %>` tags found in any new non-empty note, so dictating literal `<%` would be interpreted when Obsidian opens the vault.

## Normalization (omega)

Raw notes are the durable record; everything downstream must be rebuildable from them. The first processing stage turns each `Raw/<stamp>.md` into `Normalized/<stamp>.md`.

- Files: `system/hosts/omega/notes.nix` (headless `ob sync` + `note-normalize` system units, run as the user since omega has no login session), `system/hosts/omega/note-normalize.py`.
- Model: the resident `qwen3.8:27b` on omega's Ollama, `think: false`, temperature 0. Supernote notes are sent with their page images, which are authoritative for indentation and strike-through.
- Output: Markdown lists (thoughts as bullets, details nested, tabs for indentation), spelling/grammar/punctuation fixed, misheard or misread words corrected, `~~strike~~` kept, no embeds. Frontmatter: `created`, `day`, `source`, `raw` (link), `normalized_at`, `normalizer` (model / prompt version), `raw_hash`, and `review: true` when under 80% of the raw words survive in order.
- Raw gets exactly one added property, `normalized: "[[Normalized/<stamp>]]"`. Links are full paths because both folders hold the same file names.
- Triggered by a systemd path unit watching `Raw/` and `Raw/Images/`; runs rescan until a pass finds nothing (changes during a run are dropped by systemd). A 5-minute timer catches edits whose quiet period expired. New notes are normalized at once (typed notes still being written wait). A raw note whose hash (excluding `normalized`) differs from `raw_hash` was edited and is redone after 10 quiet minutes. Normalized notes are generated output and are overwritten.
- Handwritten notes are normalized one page per call (page text + that page's image), then joined into one note. Blank pages (no OCR text) are skipped; the OCR and the normalizer both drop replies that only describe an empty page.
- The pipeline never deletes. `note-delete --latest | <stem>` (desktops) removes a raw note, its page images and its generated notes after confirmation; `note-delete --orphans` lists generated notes whose raw note is gone and deletes them on confirmation. Sync carries deletions everywhere.
- Manual: `note-normalize [--dry-run] [--force] [stem ...]` on omega. Bump `VERSION` in the script when the prompt changes; `--force` regenerates.

## Chunks

Each chunk is independently shippable. Check items off as they are done.

### Chunk 1: Template + shared renderer (done 2026-10-01)

- [x] Create `Templates/Raw Note.md` in the vault.
- [x] Templater: folder template `Raw/` -> `Templates/Raw Note.md`; command "Templater: Create Raw Note" (files the note into `Raw/<stamp>.md`).
- [ ] On the phone: confirm Templater settings synced (or set the same folder template + template hotkey), `source` resolves to `phone-typed`, and add "Templater: Create Raw Note" to the mobile toolbar or pull-down quick action.
- [x] `capture-note` executes the template headless (`raw-note.mjs`, rusty_engine); `capture-note.sh` and the interim `raw_note.py` removed.
- [x] Backfilled existing notes: `dictation` -> `desktop-dictation`, offset added to `created`, frontmatter added to the phone note.

### Chunk 2: Supernote alignment (done 2026-10-01)

- [x] `capture-process.py` writes body-only `capture.md` + `capture.json`; `capture-import.py` calls `capture-note --source supernote` with page images as attachments (legacy frontmatter batches still accepted).
- [x] Naming is `YYYY-MM-DD-HHMMSS.md` from the archive mtime; images `Raw/Images/<stamp>-page-NN.png`. Sha only in outbox dirs. Existing `Capture-<sha>` notes and images renamed.
- [ ] Verify with a real capture from the tablet.

### Chunk 3: alpha capture service

- [ ] Headless Obsidian Sync on alpha (`ob sync --continuous`), with credentials in alpha secrets, so captures land without pc being on.
- [ ] Bind Parakeet to localhost (or the tailnet interface only).
- [ ] Benchmark Parakeet on the GTX 970: latency for a 10 s, 30 s and 2 min clip, and VRAM. Maxwell (sm_52) support in the current CUDA 12 PyTorch image must be confirmed. Fall back to CPU or omega if it's too slow or unsupported. Speed matters little because the clips are archived anyway.
- [ ] Small HTTP service (Python, stdlib or FastAPI), exposed via Tailscale Serve, tailnet only:
  - `POST /capture/text` with `{text, source}`
  - `POST /capture/audio` multipart with `audio`, `source`, and an optional client `created` timestamp (offline queue).
  - Bearer token from secrets.
  - `GET /health`
- [ ] Audio: store at `/data/Capture/audio/<stamp>.<ext>` first, then write the note with `transcription: pending`, then transcribe and fill in the body.
- [ ] Retry timer for `pending` / `failed` notes. Writing the note before transcribing means a capture is never lost.
- [ ] Idempotency: the client sends a UUID, and the server ignores duplicates (needed for offline retries).
- [ ] `curl` test script in this repo.

### Chunk 4: Android APK (separate repo, MVP)

Kotlin, minimal dependencies, built reproducibly with a Nix flake (androidenv). Install via ADB first, maybe Obtainium + GitHub releases later.

- [ ] Launching the app starts recording immediately. Stop with a tap or on silence. Upload, show a toast, close.
- [ ] Offline queue with WorkManager and retry with backoff. Audio is kept until the server acknowledges it.
- [ ] Quick Settings tile, home screen widget, lock screen access if possible.
- [ ] Share target: text shared from any app becomes a raw note with `source: phone-share`.
- [ ] Settings: server URL and token.
- [ ] Pixel 10 Pro XL: Settings -> System -> Gestures -> Quick Tap -> Open app -> Capture. The camera power-button double-press stays as is.
- [ ] Add a short `notes/CAPTURE_APK.md` here pointing at the repo, server contract, and install steps.

### Chunk 5: Wake word on phone (also covers the car)

- [ ] Foreground service (`foregroundServiceType="microphone"`, persistent notification) running a wake word engine:
  - **openWakeWord**: open source, custom words trainable for free, ONNX/TFLite on Android.
  - **Porcupine (Picovoice)**: very good Android SDK and easy custom words, but needs a free-tier account and access key.
  - Pick one after testing battery use and false triggers.
- [ ] After the wake word: record until silence (VAD, for example Silero VAD), then go through the same upload path with `source: phone-wake`.
- [ ] Toggle: always on, only while charging, or only in the car (detect the Android Auto connection or a car Bluetooth device -> `source: car`).
- [ ] Audio feedback (beeps) on start and stop, since there is no screen in use when driving.
- [ ] Car notes:
  - Using the phone directly instead of an Android Auto app avoids AA's app restrictions.
  - Android gives the mic to one app at a time. Google Assistant hotword, calls and AA voice can take it away, so the service must handle being silenced and recover.
  - When AA is connected, the phone may route input to the car mic over Bluetooth. Test which mic actually picks up voice and how it does with road noise.
  - Android 14+ forbids starting a microphone foreground service from the background. Start it from the UI, a tile or boot, and keep it running.

### Chunk 6: Home device (later)

- [ ] ESP32-S3 box (or a Pi Zero 2 W with a mic HAT) with an on-device wake word (microWakeWord / openWakeWord), a button and an LED.
- [ ] Posts to the same `/capture/audio` with `source: home`.
- [ ] Reference hardware: Home Assistant Voice PE, ESP32-S3-BOX-3, ReSpeaker Lite.

## Open Questions

- Wake word phrase. It should be 3+ syllables and uncommon in speech.
- Should `phone-typed` captures go through the APK too, or is Obsidian + template enough? Current answer: both exist, Obsidian is the main path.
- Audio retention: keep forever or prune after transcription is confirmed?
