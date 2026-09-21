// wallpaperctl: fast CLI for the wallpaper picker's hot path.
//
// Design notes (see /etc/nixos conversation history for the full story):
// - Palette lookup is cache-only. This binary never shells out to matugen;
//   it reads the "palette" field cached in metadata.json by
//   generate-palettes.py, which lives in the Wallpapers repo itself and is
//   run by its scheduled GitHub Actions job. A cache miss just leaves
//   colors.json untouched (prints a hint to stderr) instead of blocking the
//   wallpaper swap.
// - Wallpaper is applied via `hyprctl hyprpaper wallpaper mon,path,fit`,
//   talking to the hyprpaper daemon (started on demand if its IPC socket
//   isn't present yet). hyprpaper's protocol has no transition/fade concept,
//   so every switch is a hard cut - that's intentional, not a bug.
// - wallpapers() is scanned once per invocation and threaded through, unlike
//   the old Python version which rescanned the ~900-file directory twice.

use std::collections::{BTreeMap, HashSet};
use std::env;
use std::fs;
use std::io;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use rand::seq::SliceRandom;
use rand::thread_rng;
use rand::Rng;
use serde::{Deserialize, Serialize};

const EXTENSIONS: &[&str] = &["avif", "gif", "jpeg", "jpg", "png", "webp"];

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Palette {
    background: String,
    surface: String,
    #[serde(rename = "surfaceHover")]
    surface_hover: String,
    text: String,
    muted: String,
    accent: String,
    #[serde(rename = "accentStrong")]
    accent_strong: String,
    warning: String,
    danger: String,
    border: String,
}

#[derive(Debug, Deserialize)]
struct HyprlandInstance {
    instance: String,
    wl_socket: String,
}

struct Paths {
    wallpaper_dir: PathBuf,
    metadata_file: PathBuf,
    curation_file: PathBuf,
    current_file: PathBuf,
    order_file: PathBuf,
    colors_file: PathBuf,
}

impl Paths {
    fn new() -> Self {
        let home = PathBuf::from(env::var("HOME").expect("HOME must be set"));
        let state_home = env::var("XDG_STATE_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home.join(".local/state"));
        let wallpaper_dir = home.join("Wallpapers");
        let state_dir = state_home.join("wallpaper");
        Paths {
            metadata_file: wallpaper_dir.join("metadata.json"),
            curation_file: wallpaper_dir.join("curation.json"),
            current_file: state_dir.join("current"),
            order_file: state_dir.join("order.json"),
            colors_file: state_dir.join("colors.json"),
            wallpaper_dir,
        }
    }
}

fn has_wallpaper_extension(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| EXTENSIONS.contains(&ext.to_ascii_lowercase().as_str()))
        .unwrap_or(false)
}

fn walk_dir(dir: &Path, out: &mut Vec<PathBuf>) -> io::Result<()> {
    let entries = match fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(_) => return Ok(()), // matches Python's "not a dir -> []" leniency
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let file_type = match entry.file_type() {
            Ok(ft) => ft,
            Err(_) => continue,
        };
        if file_type.is_dir() {
            walk_dir(&path, out)?;
        } else if file_type.is_file() {
            let name_hidden = path
                .file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with('.'))
                .unwrap_or(true);
            if !name_hidden && has_wallpaper_extension(&path) {
                out.push(path);
            }
        }
    }
    Ok(())
}

/// All wallpapers under WALLPAPER_DIR, canonicalized and sorted. Scanned once
/// per invocation and passed around explicitly - the old Python version
/// scanned this twice per call (~45ms wasted on a 900-file library).
fn wallpapers(paths: &Paths) -> Vec<PathBuf> {
    let mut found = Vec::new();
    let _ = walk_dir(&paths.wallpaper_dir, &mut found);
    let mut resolved: Vec<PathBuf> = found
        .into_iter()
        .filter_map(|p| fs::canonicalize(&p).ok())
        .collect();
    resolved.sort();
    resolved.dedup();
    resolved
}

fn write_atomic(path: &Path, contents: &str) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, contents)?;
    fs::rename(&tmp, path)?;
    Ok(())
}

fn save_order(paths: &Paths, available: &[PathBuf]) -> io::Result<()> {
    let list: Vec<String> = available
        .iter()
        .map(|p| p.to_string_lossy().to_string())
        .collect();
    let json = serde_json::to_string(&list).unwrap();
    write_atomic(&paths.order_file, &json)
}

/// The persisted random order, reconciled against what is actually on disk.
///
/// This used to reshuffle the whole library whenever the file count changed.
/// With wallpapers arriving daily from the fetcher that discarded the cycle
/// order every single day, and hiding one wallpaper did the same. Instead the
/// stored order is kept: vanished files are dropped, and new ones are spliced
/// in at random positions so they surface soon without moving anything else.
fn randomized_order(paths: &Paths, available: &[PathBuf]) -> Vec<PathBuf> {
    let stored: Option<Vec<PathBuf>> = fs::read_to_string(&paths.order_file)
        .ok()
        .and_then(|text| serde_json::from_str::<Vec<String>>(&text).ok())
        .map(|list| list.into_iter().map(PathBuf::from).collect());

    let available_set: HashSet<&PathBuf> = available.iter().collect();

    let Some(stored) = stored else {
        let mut shuffled = available.to_vec();
        shuffled.shuffle(&mut thread_rng());
        let _ = save_order(paths, &shuffled);
        return shuffled;
    };

    let stored_len = stored.len();
    let mut seen: HashSet<PathBuf> = HashSet::new();
    let mut ordered: Vec<PathBuf> = Vec::with_capacity(available.len());
    for path in stored {
        if available_set.contains(&path) && seen.insert(path.clone()) {
            ordered.push(path);
        }
    }

    let mut added: Vec<PathBuf> = available
        .iter()
        .filter(|path| !seen.contains(*path))
        .cloned()
        .collect();

    if added.is_empty() && ordered.len() == stored_len {
        return ordered;
    }

    let mut rng = thread_rng();
    added.shuffle(&mut rng);
    for path in added {
        let position = rng.gen_range(0..=ordered.len());
        ordered.insert(position, path);
    }

    let _ = save_order(paths, &ordered);
    ordered
}

/// Wallpapers the user has hidden with Ctrl+D in the picker.
///
/// Deliberately a separate file from metadata.json, which is 8 MB and is
/// rewritten by the scheduled fetcher. Keeping curation here means the only
/// writer is this machine and the only writer of metadata.json is the
/// fetcher, so the two never produce a merge conflict against each other.
#[derive(Debug, Default, Serialize, Deserialize)]
struct Curation {
    #[serde(default = "curation_version")]
    version: u32,
    #[serde(default)]
    hidden: BTreeMap<String, HiddenEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct HiddenEntry {
    at: String,
}

fn curation_version() -> u32 {
    1
}

fn load_curation(paths: &Paths) -> Curation {
    fs::read_to_string(&paths.curation_file)
        .ok()
        .and_then(|text| serde_json::from_str::<Curation>(&text).ok())
        .unwrap_or_else(|| Curation {
            version: curation_version(),
            hidden: BTreeMap::new(),
        })
}

fn save_curation(paths: &Paths, curation: &Curation) -> io::Result<()> {
    let json = serde_json::to_string_pretty(curation).unwrap();
    write_atomic(&paths.curation_file, &format!("{json}\n"))
}

fn file_name_of(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_string()
}

/// ISO-8601 UTC without pulling in a date crate for one timestamp.
fn timestamp_now() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let days = seconds.div_euclid(86_400);
    let time = seconds.rem_euclid(86_400);
    // Civil-from-days (Howard Hinnant's algorithm), epoch shifted to 0000-03-01.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = era * 400 + yoe + if month <= 2 { 1 } else { 0 };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        year,
        month,
        day,
        time / 3600,
        (time % 3600) / 60,
        time % 60
    )
}

fn toggle_hidden(paths: &Paths, scanned: &[PathBuf], raw_path: &str) -> Result<(bool, String), String> {
    let requested = fs::canonicalize(raw_path).map_err(|e| format!("{raw_path}: {e}"))?;
    // Validated against every scanned wallpaper rather than the cycling list,
    // so an already-hidden wallpaper can still be un-hidden.
    if !scanned.contains(&requested) {
        return Err(format!(
            "wallpaper is not a supported image under {}: {}",
            paths.wallpaper_dir.display(),
            requested.display()
        ));
    }

    let name = file_name_of(&requested);
    let mut curation = load_curation(paths);
    let hidden = if curation.hidden.remove(&name).is_some() {
        false
    } else {
        curation.hidden.insert(name.clone(), HiddenEntry { at: timestamp_now() });
        true
    };
    save_curation(paths, &curation).map_err(|e| e.to_string())?;
    Ok((hidden, name))
}

fn current(paths: &Paths, available: &[PathBuf]) -> Option<PathBuf> {
    let text = fs::read_to_string(&paths.current_file).ok()?;
    let candidate = PathBuf::from(text.trim());
    if available.contains(&candidate) {
        Some(candidate)
    } else {
        None
    }
}

fn active_hyprland_instance() -> Result<String, String> {
    let output = Command::new("hyprctl")
        .args(["instances", "-j"])
        .output()
        .map_err(|e| format!("failed to list Hyprland instances: {e}"))?;
    if !output.status.success() {
        return Err("failed to list Hyprland instances".to_string());
    }

    let instances: Vec<HyprlandInstance> =
        serde_json::from_slice(&output.stdout).map_err(|e| format!("invalid Hyprland instance list: {e}"))?;
    let wayland_display = env::var("WAYLAND_DISPLAY").ok();
    instances
        .iter()
        .find(|instance| wayland_display.as_deref() == Some(instance.wl_socket.as_str()))
        .or_else(|| (instances.len() == 1).then(|| &instances[0]))
        .map(|instance| instance.instance.clone())
        .ok_or_else(|| "cannot identify the active Hyprland instance".to_string())
}

fn hyprpaper_socket_path(instance: &str) -> Result<PathBuf, String> {
    let runtime_dir = env::var("XDG_RUNTIME_DIR").map_err(|_| "XDG_RUNTIME_DIR is not set")?;
    Ok(PathBuf::from(runtime_dir).join("hypr").join(instance).join(".hyprpaper.sock"))
}

/// Existence alone isn't enough: a hyprpaper that died without cleaning up
/// leaves a stale socket *file* behind, which still passes `.exists()` but
/// refuses connections. Only a real connect attempt tells the truth.
fn socket_alive(socket: &Path) -> bool {
    std::os::unix::net::UnixStream::connect(socket).is_ok()
}

fn ensure_daemon(instance: &str) -> Result<(), String> {
    let socket = hyprpaper_socket_path(instance)?;
    if socket_alive(&socket) {
        return Ok(());
    }

    Command::new("hyprpaper")
        .env("HYPRLAND_INSTANCE_SIGNATURE", instance)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn()
        .map_err(|e| format!("failed to start hyprpaper: {e}"))?;

    for _ in 0..40 {
        std::thread::sleep(Duration::from_millis(50));
        if socket_alive(&socket) {
            return Ok(());
        }
    }
    Err("hyprpaper did not become ready".to_string())
}

/// Cache-only palette lookup: reads metadata.json's entries[filename].palette.
/// Never invokes matugen - that is generate-palettes.py's job, run by the
/// Wallpapers repo's scheduled job.
fn cached_palette(paths: &Paths, filename: &str) -> Option<Palette> {
    let text = fs::read_to_string(&paths.metadata_file).ok()?;
    let root: serde_json::Value = serde_json::from_str(&text).ok()?;
    let palette_value = root.get("entries")?.get(filename)?.get("palette")?.clone();
    serde_json::from_value(palette_value).ok()
}

fn write_colors(paths: &Paths, colors: &Palette) -> io::Result<()> {
    let json = serde_json::to_string(colors).unwrap();
    write_atomic(&paths.colors_file, &json)
}

fn write_state(paths: &Paths, path: &Path, colors: Option<&Palette>) -> io::Result<()> {
    if let Some(colors) = colors {
        write_colors(paths, colors)?;
    }
    write_atomic(&paths.current_file, &format!("{}\n", path.display()))
}

fn resolve_wallpaper(paths: &Paths, available: &[PathBuf], raw_path: &str) -> Result<PathBuf, String> {
    let requested = fs::canonicalize(raw_path).map_err(|e| format!("{raw_path}: {e}"))?;
    if !available.contains(&requested) {
        return Err(format!(
            "wallpaper is not a supported image under {}: {}",
            paths.wallpaper_dir.display(),
            requested.display()
        ));
    }
    Ok(requested)
}

fn palette_for(paths: &Paths, requested: &Path) -> Option<Palette> {
    let filename = file_name_of(requested);
    let colors = cached_palette(paths, &filename);
    if colors.is_none() {
        eprintln!(
            "wallpaperctl: no cached palette for {filename}; the Wallpapers repo's scheduled job backfills these, or run generate-palettes.py there by hand"
        );
    }
    colors
}

/// Records a wallpaper as the active one without touching hyprpaper. The picker
/// previews by setting the real wallpaper, so closing it on an image that is
/// already displayed only needs the state write; re-issuing the hyprctl call
/// would make the close visibly flash.
fn commit_wallpaper(paths: &Paths, available: &[PathBuf], raw_path: &str) -> Result<PathBuf, String> {
    let requested = resolve_wallpaper(paths, available, raw_path)?;
    let colors = palette_for(paths, &requested);
    write_state(paths, &requested, colors.as_ref()).map_err(|e| e.to_string())?;
    Ok(requested)
}

fn set_wallpaper(paths: &Paths, available: &[PathBuf], raw_path: &str, persist: bool) -> Result<PathBuf, String> {
    let requested = resolve_wallpaper(paths, available, raw_path)?;
    let instance = active_hyprland_instance()?;

    ensure_daemon(&instance)?;

    let arg = format!(",{},cover", requested.display());
    let status = Command::new("hyprctl")
        .env("HYPRLAND_INSTANCE_SIGNATURE", &instance)
        .args(["hyprpaper", "wallpaper", &arg])
        .status()
        .map_err(|e| format!("failed to run hyprctl: {e}"))?;
    if !status.success() {
        return Err(format!("hyprctl hyprpaper wallpaper failed for {}", requested.display()));
    }

    let colors = palette_for(paths, &requested);

    if persist {
        write_state(paths, &requested, colors.as_ref()).map_err(|e| e.to_string())?;
    } else if let Some(colors) = &colors {
        write_colors(paths, colors).map_err(|e| e.to_string())?;
    }

    Ok(requested)
}

fn choose_next(available: &[PathBuf], active: Option<&PathBuf>) -> Option<PathBuf> {
    if available.is_empty() {
        return None;
    }
    let index = active
        .and_then(|a| available.iter().position(|p| p == a))
        .map(|i| (i + 1) % available.len())
        .unwrap_or(0);
    Some(available[index].clone())
}

fn choose_previous(available: &[PathBuf], active: Option<&PathBuf>) -> Option<PathBuf> {
    if available.is_empty() {
        return None;
    }
    let index = active
        .and_then(|a| available.iter().position(|p| p == a))
        .map(|i| (i + available.len() - 1) % available.len())
        .unwrap_or(available.len() - 1);
    Some(available[index].clone())
}

fn print_catalog(
    paths: &Paths,
    available: &[PathBuf],
    active: Option<&PathBuf>,
    curation: &Curation,
) {
    #[derive(Serialize)]
    struct Entry {
        name: String,
        file: String,
        path: String,
        extension: String,
        hidden: bool,
    }
    #[derive(Serialize)]
    struct Catalog {
        current: String,
        #[serde(rename = "metadataFile")]
        metadata_file: String,
        #[serde(rename = "curationFile")]
        curation_file: String,
        wallpapers: Vec<Entry>,
    }

    // Hidden wallpapers stay in the catalog, flagged, so the picker can offer
    // an "is:hidden" view to un-hide them. Only the cycling commands drop them.
    let entries: Vec<Entry> = available
        .iter()
        .map(|p| {
            let file = file_name_of(p);
            Entry {
                name: p
                    .file_stem()
                    .and_then(|n| n.to_str())
                    .unwrap_or_default()
                    .to_string(),
                hidden: curation.hidden.contains_key(&file),
                file,
                path: p.to_string_lossy().to_string(),
                extension: p
                    .extension()
                    .and_then(|n| n.to_str())
                    .unwrap_or_default()
                    .to_ascii_uppercase(),
            }
        })
        .collect();

    let catalog = Catalog {
        current: active.map(|p| p.to_string_lossy().to_string()).unwrap_or_default(),
        metadata_file: if paths.metadata_file.is_file() {
            paths.metadata_file.to_string_lossy().to_string()
        } else {
            String::new()
        },
        // Always reported, even before the file exists: the picker watches it
        // so the first Ctrl+D is picked up without reopening the picker.
        curation_file: paths.curation_file.to_string_lossy().to_string(),
        wallpapers: entries,
    };

    println!("{}", serde_json::to_string(&catalog).unwrap());
}

/// Pick the next/previous wallpaper, skipping everything the user hid.
///
/// When the active wallpaper is itself hidden it is still present in the full
/// order, so the walk resumes from its slot there. Cycling over the visible
/// list alone would restart at index 0 the moment you hide what you are
/// looking at.
fn resolve_cycle_target(
    available: &[PathBuf],
    cycling: &[PathBuf],
    active: Option<&PathBuf>,
    forward: bool,
) -> Option<PathBuf> {
    if cycling.is_empty() {
        return None;
    }
    let Some(active) = active else {
        return if forward {
            choose_next(cycling, None)
        } else {
            choose_previous(cycling, None)
        };
    };
    if cycling.contains(active) {
        return if forward {
            choose_next(cycling, Some(active))
        } else {
            choose_previous(cycling, Some(active))
        };
    }

    let start = available.iter().position(|path| path == active)?;
    let visible: HashSet<&PathBuf> = cycling.iter().collect();
    let len = available.len();
    (1..=len).find_map(|offset| {
        let index = if forward {
            (start + offset) % len
        } else {
            (start + len - offset) % len
        };
        let candidate = &available[index];
        visible.contains(candidate).then(|| candidate.clone())
    })
}

fn usage_and_exit() -> ! {
    eprintln!(
        "usage: wallpaperctl {{catalog|current|set PATH|preview PATH|commit PATH|random|next|previous|restore|toggle-hidden PATH}}"
    );
    std::process::exit(2);
}

fn fail(message: &str) -> ! {
    eprintln!("wallpaperctl: {message}");
    std::process::exit(1);
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let paths = Paths::new();
    let scanned = wallpapers(&paths);
    let available = randomized_order(&paths, &scanned);
    let curation = load_curation(&paths);
    // Two lists on purpose: `available` is every wallpaper in cycle order and
    // backs the catalog plus set/preview, while `cycling` drops what the user
    // hid so next/previous/random/restore can never land on it again.
    let cycling: Vec<PathBuf> = available
        .iter()
        .filter(|path| !curation.hidden.contains_key(&file_name_of(path)))
        .cloned()
        .collect();
    let active = current(&paths, &available);

    let command = args.get(1).map(String::as_str).unwrap_or("");

    match command {
        "catalog" => print_catalog(&paths, &available, active.as_ref(), &curation),
        "current" => println!("{}", active.map(|p| p.to_string_lossy().to_string()).unwrap_or_default()),
        "toggle-hidden" if args.len() == 3 => match toggle_hidden(&paths, &scanned, &args[2]) {
            Ok((hidden, name)) => println!("{} {}", if hidden { "hidden" } else { "visible" }, name),
            Err(e) => fail(&e),
        },
        "set" if args.len() == 3 => match set_wallpaper(&paths, &available, &args[2], true) {
            Ok(path) => println!("{}", path.display()),
            Err(e) => fail(&e),
        },
        "preview" if args.len() == 3 => match set_wallpaper(&paths, &available, &args[2], false) {
            Ok(path) => println!("{}", path.display()),
            Err(e) => fail(&e),
        },
        "commit" if args.len() == 3 => match commit_wallpaper(&paths, &available, &args[2]) {
            Ok(path) => println!("{}", path.display()),
            Err(e) => fail(&e),
        },
        "random" | "next" => {
            if let Some(target) = resolve_cycle_target(&available, &cycling, active.as_ref(), true) {
                match set_wallpaper(&paths, &available, &target.to_string_lossy(), true) {
                    Ok(path) => println!("{}", path.display()),
                    Err(e) => fail(&e),
                }
            }
        }
        "previous" => {
            if let Some(target) = resolve_cycle_target(&available, &cycling, active.as_ref(), false) {
                match set_wallpaper(&paths, &available, &target.to_string_lossy(), true) {
                    Ok(path) => println!("{}", path.display()),
                    Err(e) => fail(&e),
                }
            }
        }
        "restore" => {
            // A wallpaper hidden while it was active must not come back on the
            // next login, so fall through to the one that follows it.
            let target = match active.as_ref() {
                Some(path) if cycling.contains(path) => Some(path.clone()),
                Some(_) => resolve_cycle_target(&available, &cycling, active.as_ref(), true),
                None => choose_next(&cycling, None),
            };
            if let Some(target) = target {
                match set_wallpaper(&paths, &available, &target.to_string_lossy(), true) {
                    Ok(path) => println!("{}", path.display()),
                    Err(e) => fail(&e),
                }
            }
        }
        _ => usage_and_exit(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paths(names: &[&str]) -> Vec<PathBuf> {
        names.iter().map(PathBuf::from).collect()
    }

    #[test]
    fn cycles_forward_over_visible_wallpapers_only() {
        let available = paths(&["a", "b", "c", "d"]);
        let cycling = paths(&["a", "c", "d"]);
        let active = PathBuf::from("a");
        assert_eq!(
            resolve_cycle_target(&available, &cycling, Some(&active), true),
            Some(PathBuf::from("c"))
        );
    }

    #[test]
    fn cycles_backward_over_visible_wallpapers_only() {
        let available = paths(&["a", "b", "c", "d"]);
        let cycling = paths(&["a", "c", "d"]);
        let active = PathBuf::from("c");
        assert_eq!(
            resolve_cycle_target(&available, &cycling, Some(&active), false),
            Some(PathBuf::from("a"))
        );
    }

    #[test]
    fn resumes_from_the_slot_of_a_hidden_active_wallpaper() {
        // "b" was hidden while it was on screen. Cycling over the visible list
        // alone would restart at "a"; it must continue to "c" instead.
        let available = paths(&["a", "b", "c", "d"]);
        let cycling = paths(&["a", "c", "d"]);
        let active = PathBuf::from("b");
        assert_eq!(
            resolve_cycle_target(&available, &cycling, Some(&active), true),
            Some(PathBuf::from("c"))
        );
        assert_eq!(
            resolve_cycle_target(&available, &cycling, Some(&active), false),
            Some(PathBuf::from("a"))
        );
    }

    #[test]
    fn wraps_around_from_a_hidden_active_wallpaper_at_the_end() {
        let available = paths(&["a", "b", "c", "d"]);
        let cycling = paths(&["a", "b"]);
        let active = PathBuf::from("d");
        assert_eq!(
            resolve_cycle_target(&available, &cycling, Some(&active), true),
            Some(PathBuf::from("a"))
        );
        assert_eq!(
            resolve_cycle_target(&available, &cycling, Some(&active), false),
            Some(PathBuf::from("b"))
        );
    }

    #[test]
    fn returns_nothing_when_every_wallpaper_is_hidden() {
        let available = paths(&["a", "b"]);
        let active = PathBuf::from("a");
        assert_eq!(
            resolve_cycle_target(&available, &[], Some(&active), true),
            None
        );
    }

    #[test]
    fn timestamp_is_iso8601_utc() {
        let stamp = timestamp_now();
        assert_eq!(stamp.len(), 20, "{stamp}");
        assert!(stamp.ends_with('Z'), "{stamp}");
        assert_eq!(&stamp[4..5], "-");
        assert_eq!(&stamp[10..11], "T");
        let year: i32 = stamp[0..4].parse().unwrap();
        assert!(year >= 2024 && year < 2100, "{stamp}");
    }
}
