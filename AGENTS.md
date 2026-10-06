# Agent Notes

For survey-job LiDAR tile lookup/copy from the office ortho drive, read `notes/LIDAR_WORKFLOW.md`. It documents mounted paths, Pierce County parcel queries, tile naming, and verification.

If the user asks to download wallpapers, use these preferences:

- Resolution and ratio must be exactly 3840x2160 (4K, 16:9).
- Prefer scenic, cozy, nature-forward wallpapers.
- Avoid people/characters.
- Animals are welcome.
- Keep results SFW.
- Prefer static image formats (`.jpg`, `.jpeg`, `.png`, `.webp`) over animated formats.
- Favor forests, lakes, rivers, mountains, waterfalls, mist, snow, coastlines, and sunsets.
- Japanese countryside or anime-adjacent scenery is good when it is character-free.
- Save new batches with distinct prefixes (for example `wh4_`, `wh5_`) to avoid collisions.
- Skip duplicates against existing `wh*` files.
- Validate image dimensions after download and remove anything not exactly 3840x2160.

# Rebuilds

When rebuilding, use the rehome command if available.

# Configuration Files

- Keep application configuration beside its owning Nix module whenever practical.
- Deploy editable configuration with Home Manager out-of-store symlinks, using `config.lib.file.mkOutOfStoreSymlink`, rather than store-backed `source = ./path` links or embedded file contents.
- Prefer linking an application configuration directory when the application atomically replaces files; otherwise it may replace an individual symlink instead of updating its repository target.
- Use store-backed files only when immutability and rebuild-controlled changes are explicitly desired.
- Rationale: configuration edits and application-written settings should update this repository immediately, remain writable, work after a program reload without a Home Manager rebuild, and persist across computers through Git.
