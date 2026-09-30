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
// - Cycling follows the sun: see sun.rs and phase_pool below.

mod sun;

use std::collections::{BTreeMap, HashMap, HashSet};
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

use sun::{Phase, PHASES};

const EXTENSIONS: &[&str] = &["avif", "gif", "jpeg", "jpg", "png", "webp"];
// Assumed when the wallpaper can't be sampled (unreadable file, no `magick` on
// PATH). Dark, matching the palette's own dark-mode-only default, so the bar
// fails toward its historical always-white-content behaviour.
const DEFAULT_BAR_LUMINANCE: f64 = 0.08;

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

/// What actually gets written to colors.json: the cached matugen palette (used
/// by popups and other surfaces that sit on their own opaque-ish backing) plus
/// `barLuminance`, which the bar's floating content - text and icons with no
/// backing of their own - uses to decide between light and dark content and
/// how strong a scrim it needs, the same problem macOS's auto menu bar solves.
/// Kept as its own struct rather than folded into Palette: Palette also
/// doubles as metadata.json's cache schema, and barLuminance is never cached
/// there since it comes from a live pixel sample, not matugen.
#[derive(Debug, Clone, Serialize)]
struct ColorsFile {
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
    #[serde(rename = "barLuminance")]
    bar_luminance: f64,
}

impl ColorsFile {
    fn new(palette: &Palette, bar_luminance: f64) -> Self {
        ColorsFile {
            background: palette.background.clone(),
            surface: palette.surface.clone(),
            surface_hover: palette.surface_hover.clone(),
            text: palette.text.clone(),
            muted: palette.muted.clone(),
            accent: palette.accent.clone(),
            accent_strong: palette.accent_strong.clone(),
            warning: palette.warning.clone(),
            danger: palette.danger.clone(),
            border: palette.border.clone(),
            bar_luminance,
        }
    }
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
    location_file: PathBuf,
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
            location_file: state_dir.join("location.json"),
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

/// Wallpapers the user has hidden with Ctrl+D in the picker, and phase labels
/// they corrected with Ctrl+T.
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
    /// Replaces the model's phases in metadata.json for that file. Lives here,
    /// not in metadata.json, so the fetcher's relabelling can never undo it.
    #[serde(default, rename = "sunOverrides", skip_serializing_if = "BTreeMap::is_empty")]
    sun_overrides: BTreeMap<String, SunOverride>,
    /// Anything a newer wallpaperctl wrote that this one does not know about,
    /// carried through untouched. Every machine rewrites this file, so an
    /// older build dropping unknown keys would silently erase another
    /// machine's curation.
    #[serde(flatten)]
    extra: serde_json::Map<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SunOverride {
    phases: Vec<String>,
    at: String,
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
            ..Curation::default()
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

/// Phases per file name as classify-sun.py labelled them in metadata.json.
/// Deserialised into a narrow struct so the rest of the 10 MB file is skipped
/// rather than built into a tree.
fn model_phases(paths: &Paths) -> HashMap<String, Vec<Phase>> {
    #[derive(Deserialize)]
    struct Root {
        #[serde(default)]
        entries: HashMap<String, Entry>,
    }
    #[derive(Deserialize)]
    struct Entry {
        #[serde(default)]
        sun: Option<Label>,
    }
    #[derive(Deserialize)]
    struct Label {
        #[serde(default)]
        phases: Vec<String>,
    }

    let Some(root) = fs::read_to_string(&paths.metadata_file)
        .ok()
        .and_then(|text| serde_json::from_str::<Root>(&text).ok())
    else {
        return HashMap::new();
    };
    root.entries
        .into_iter()
        .filter_map(|(name, entry)| {
            let phases = parse_phases(&entry.sun?.phases);
            (!phases.is_empty()).then_some((name, phases))
        })
        .collect()
}

fn parse_phases(names: &[String]) -> Vec<Phase> {
    let mut phases: Vec<Phase> = names.iter().filter_map(|name| Phase::parse(name)).collect();
    phases.sort();
    phases.dedup();
    phases
}

/// The phases each wallpaper is shown in: the user's Ctrl+T correction if
/// there is one, otherwise the model's label. Unlabelled files are absent.
fn effective_phases(model: &HashMap<String, Vec<Phase>>, curation: &Curation) -> HashMap<String, Vec<Phase>> {
    let mut phases = model.clone();
    for (name, correction) in &curation.sun_overrides {
        let parsed = parse_phases(&correction.phases);
        if !parsed.is_empty() {
            phases.insert(name.clone(), parsed);
        }
    }
    phases
}

/// Where the sun calculation is done from.
///
/// wallpaper-locate writes location.json from geoclue. Without it (geoclue
/// never answered, or the helper has not run yet on a fresh machine) the
/// coordinate baked into the wrapper by Nix stands in. Tens of kilometres of
/// error move sunrise by seconds, so a stale or coarse fix is harmless.
fn location(paths: &Paths) -> Option<(f64, f64, &'static str)> {
    #[derive(Deserialize)]
    struct Stored {
        latitude: f64,
        longitude: f64,
    }
    if let Some(stored) = fs::read_to_string(&paths.location_file)
        .ok()
        .and_then(|text| serde_json::from_str::<Stored>(&text).ok())
    {
        return Some((stored.latitude, stored.longitude, "geoclue"));
    }
    let fallback = env::var("WALLPAPER_FALLBACK_LOCATION").ok()?;
    let (lat, lon) = fallback.split_once(',')?;
    Some((lat.trim().parse().ok()?, lon.trim().parse().ok()?, "fallback"))
}

/// The current phase of the day, or None when no location is known at all,
/// which turns phase filtering off rather than guessing.
fn current_phase(paths: &Paths) -> Option<(Phase, f64, &'static str)> {
    let (latitude, longitude, source) = location(paths)?;
    // Overridable so the filter can be exercised at any hour.
    let now = env::var("WALLPAPER_NOW")
        .ok()
        .and_then(|value| value.parse::<i64>().ok())
        .unwrap_or_else(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs() as i64)
                .unwrap_or(0)
        });
    let elevation = sun::elevation(latitude, longitude, now);
    Some((Phase::from_elevation(elevation), elevation, source))
}

/// Below this many candidates a phase's pool is widened, so a thin phase
/// repeats a little less instead of looping a handful of images.
const MIN_POOL: usize = 20;

/// Narrow the visible cycle to wallpapers labelled for the current phase.
///
/// Order is preserved, so this is the same persisted shuffle with gaps rather
/// than a separate playlist per phase. If too few match, neighbouring phases
/// are admitted one step at a time; unlabelled wallpapers are only used when
/// even that fails, which in practice means the library has not been labelled
/// yet and filtering should simply stay out of the way.
fn phase_pool(visible: &[PathBuf], phases: &HashMap<String, Vec<Phase>>, now: Phase) -> Vec<PathBuf> {
    for width in 0..PHASES.len() as i32 {
        let pool: Vec<PathBuf> = visible
            .iter()
            .filter(|path| {
                phases
                    .get(&file_name_of(path))
                    .is_some_and(|labels| labels.iter().any(|label| (label.rank() - now.rank()).abs() <= width))
            })
            .cloned()
            .collect();
        if pool.len() >= MIN_POOL {
            return pool;
        }
    }
    visible.to_vec()
}

/// Ctrl+T in the picker: replace a wallpaper's phases, or drop the correction
/// and fall back to the model's label with "reset".
fn set_phases(paths: &Paths, scanned: &[PathBuf], raw_path: &str, spec: &str) -> Result<String, String> {
    let requested = fs::canonicalize(raw_path).map_err(|e| format!("{raw_path}: {e}"))?;
    if !scanned.contains(&requested) {
        return Err(format!("not a wallpaper under {}: {}", paths.wallpaper_dir.display(), requested.display()));
    }
    let name = file_name_of(&requested);
    let mut curation = load_curation(paths);

    let result = if spec.trim() == "reset" {
        curation.sun_overrides.remove(&name);
        "reset".to_string()
    } else {
        let names: Vec<String> = spec.split(',').map(|part| part.trim().to_string()).filter(|p| !p.is_empty()).collect();
        if let Some(bad) = names.iter().find(|name| Phase::parse(name).is_none()) {
            return Err(format!("unknown phase {bad:?}; expected night, twilight, golden or day"));
        }
        let phases: Vec<String> = parse_phases(&names).into_iter().map(|p| p.name().to_string()).collect();
        if phases.is_empty() {
            return Err("at least one phase is required; use \"reset\" to return to the model's label".to_string());
        }
        let joined = phases.join(",");
        curation.sun_overrides.insert(name.clone(), SunOverride { phases, at: timestamp_now() });
        joined
    };
    save_curation(paths, &curation).map_err(|e| e.to_string())?;
    Ok(format!("{result} {name}"))
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

/// Relative luminance (WCAG, sRGB gamma-corrected) of a single RGB triple in
/// the 0..1 range, where 0 is black and 1 is white.
fn relative_luminance(r: f64, g: f64, b: f64) -> f64 {
    fn linearize(channel: f64) -> f64 {
        if channel <= 0.04045 {
            channel / 12.92
        } else {
            ((channel + 0.055) / 1.055).powf(2.4)
        }
    }
    0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)
}

/// Parses ImageMagick's `%[pixel:...]` output, e.g. "srgb(7.1%,8%,13.6%)" or
/// "srgb(114,133,158)" (percent vs. 0-255 depending on image depth/format).
fn parse_pixel_luminance(text: &str) -> Option<f64> {
    let start = text.find('(')?;
    let end = text.find(')')?;
    let mut channels = text[start + 1..end].split(',').map(str::trim);
    let mut channel = || -> Option<f64> {
        let raw = channels.next()?;
        if let Some(percent) = raw.strip_suffix('%') {
            percent.trim().parse::<f64>().ok().map(|v| v / 100.0)
        } else {
            raw.parse::<f64>().ok().map(|v| v / 255.0)
        }
    };
    let r = channel()?;
    let g = channel()?;
    let b = channel()?;
    Some(relative_luminance(r, g, b))
}

/// Samples the strip of the wallpaper that actually sits behind the bar - the
/// top of the image, "cover"-fit wallpapers keep that anchored to the top of
/// the screen - and averages it down to one pixel with ImageMagick. A
/// generous 10% strip (the bar itself is a couple of percent of a typical
/// screen's height) keeps this forgiving of monitors with a taller bar or a
/// slightly different aspect ratio than the wallpaper.
///
/// This is a live pixel sample, not a cache: unlike the matugen palette it
/// costs no backfill step and never misses, only fails if the file cannot be
/// decoded at all - the None case just leaves the previous barLuminance in
/// place, matching how a matugen cache miss leaves colors.json untouched.
fn sample_bar_luminance(path: &Path) -> Option<f64> {
    let output = Command::new("magick")
        .args([
            path.to_string_lossy().as_ref(),
            "-auto-orient",
            "-gravity",
            "North",
            "-crop",
            "100%x10%+0+0",
            "+repage",
            "-colorspace",
            "sRGB",
            "-resize",
            "1x1!",
            "-format",
            "%[pixel:p{0,0}]",
            "info:",
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    parse_pixel_luminance(&String::from_utf8_lossy(&output.stdout))
}

fn write_colors(paths: &Paths, colors: &Palette, bar_luminance: f64) -> io::Result<()> {
    let file = ColorsFile::new(colors, bar_luminance);
    let json = serde_json::to_string(&file).unwrap();
    write_atomic(&paths.colors_file, &json)
}

fn write_state(paths: &Paths, path: &Path, colors: Option<&Palette>, bar_luminance: f64) -> io::Result<()> {
    if let Some(colors) = colors {
        write_colors(paths, colors, bar_luminance)?;
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
    let bar_luminance = sample_bar_luminance(&requested).unwrap_or(DEFAULT_BAR_LUMINANCE);
    write_state(paths, &requested, colors.as_ref(), bar_luminance).map_err(|e| e.to_string())?;
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
    let bar_luminance = sample_bar_luminance(&requested).unwrap_or(DEFAULT_BAR_LUMINANCE);

    if persist {
        write_state(paths, &requested, colors.as_ref(), bar_luminance).map_err(|e| e.to_string())?;
    } else if let Some(colors) = &colors {
        write_colors(paths, colors, bar_luminance).map_err(|e| e.to_string())?;
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
    model: &HashMap<String, Vec<Phase>>,
    now: Option<Phase>,
) {
    #[derive(Serialize)]
    struct Entry {
        name: String,
        file: String,
        path: String,
        extension: String,
        hidden: bool,
        /// What cycling uses: the correction if any, else the model's.
        phases: Vec<&'static str>,
        #[serde(rename = "modelPhases")]
        model_phases: Vec<&'static str>,
        #[serde(rename = "phaseOverride")]
        phase_override: bool,
    }
    #[derive(Serialize)]
    struct Catalog {
        current: String,
        #[serde(rename = "metadataFile")]
        metadata_file: String,
        #[serde(rename = "curationFile")]
        curation_file: String,
        /// Phase of the day right now, empty when no location is known.
        #[serde(rename = "sunPhase")]
        sun_phase: &'static str,
        wallpapers: Vec<Entry>,
    }

    let names = |phases: Option<&Vec<Phase>>| -> Vec<&'static str> {
        phases.map(|list| list.iter().map(|p| p.name()).collect()).unwrap_or_default()
    };
    let effective = effective_phases(model, curation);

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
                phases: names(effective.get(&file)),
                model_phases: names(model.get(&file)),
                phase_override: curation.sun_overrides.contains_key(&file),
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
        sun_phase: now.map(Phase::name).unwrap_or(""),
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
        "usage: wallpaperctl {{catalog|current|set PATH|preview PATH|commit PATH|random|next|previous|restore|toggle-hidden PATH|set-phases PATH PHASE[,PHASE]|reset|phase}}"
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
    let command = args.get(1).map(String::as_str).unwrap_or("");

    // Two lists on purpose: `available` is every wallpaper in cycle order and
    // backs the catalog plus set/preview, while `cycling` drops what the user
    // hid, and what does not suit the time of day, so next/previous/random/
    // restore never land on either. Picking by hand ignores the sun.
    let visible: Vec<PathBuf> = available
        .iter()
        .filter(|path| !curation.hidden.contains_key(&file_name_of(path)))
        .cloned()
        .collect();
    let now = current_phase(&paths);
    // metadata.json is 10 MB; only parse it for commands that use the labels.
    let needs_labels = matches!(command, "catalog" | "random" | "next" | "previous" | "restore" | "phase");
    let model = if needs_labels { model_phases(&paths) } else { HashMap::new() };
    let cycling: Vec<PathBuf> = match now {
        Some((phase, _, _)) if needs_labels => phase_pool(&visible, &effective_phases(&model, &curation), phase),
        _ => visible.clone(),
    };
    let active = current(&paths, &available);

    match command {
        "catalog" => print_catalog(&paths, &available, active.as_ref(), &curation, &model, now.map(|(p, _, _)| p)),
        "phase" => match now {
            Some((phase, elevation, source)) => println!(
                "{} {:.1} {} {} of {} in cycle",
                phase.name(),
                elevation,
                source,
                cycling.len(),
                visible.len()
            ),
            None => println!("unknown (no location)"),
        },
        "set-phases" if args.len() == 4 => match set_phases(&paths, &scanned, &args[2], &args[3]) {
            Ok(result) => println!("{result}"),
            Err(e) => fail(&e),
        },
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
    fn parses_percent_pixel_output() {
        let luminance = parse_pixel_luminance("srgb(7.06668%,7.95562%,13.633%)").unwrap();
        assert!(luminance > 0.0 && luminance < 0.1, "{luminance}");
    }

    #[test]
    fn parses_integer_pixel_output() {
        let luminance = parse_pixel_luminance("srgb(255,255,255)").unwrap();
        assert!((luminance - 1.0).abs() < 1e-9, "{luminance}");
    }

    #[test]
    fn black_and_white_are_the_luminance_extremes() {
        assert!((relative_luminance(0.0, 0.0, 0.0)).abs() < 1e-9);
        assert!((relative_luminance(1.0, 1.0, 1.0) - 1.0).abs() < 1e-9);
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

    fn labelled(counts: &[(Phase, usize)]) -> (Vec<PathBuf>, HashMap<String, Vec<Phase>>) {
        let mut visible = Vec::new();
        let mut phases = HashMap::new();
        for (phase, count) in counts {
            for i in 0..*count {
                let name = format!("{}-{i}.jpg", phase.name());
                visible.push(PathBuf::from(format!("/w/{name}")));
                phases.insert(name, vec![*phase]);
            }
        }
        (visible, phases)
    }

    #[test]
    fn pool_keeps_only_the_current_phase_when_it_is_big_enough() {
        let (visible, phases) = labelled(&[(Phase::Night, 25), (Phase::Day, 40)]);
        let pool = phase_pool(&visible, &phases, Phase::Night);
        assert_eq!(pool.len(), 25);
        assert!(pool.iter().all(|p| p.to_string_lossy().contains("night")));
    }

    #[test]
    fn pool_widens_to_neighbours_when_a_phase_is_thin() {
        let (visible, phases) = labelled(&[(Phase::Night, 5), (Phase::Twilight, 18), (Phase::Day, 40)]);
        let pool = phase_pool(&visible, &phases, Phase::Night);
        // night + twilight = 23 is enough; day is two phases away and stays out.
        assert_eq!(pool.len(), 23);
    }

    #[test]
    fn pool_falls_back_to_everything_before_labelling() {
        let visible = paths(&["/w/a.jpg", "/w/b.jpg"]);
        assert_eq!(phase_pool(&visible, &HashMap::new(), Phase::Golden), visible);
    }

    #[test]
    fn pool_preserves_cycle_order() {
        let (mut visible, phases) = labelled(&[(Phase::Golden, 30)]);
        visible.reverse();
        assert_eq!(phase_pool(&visible, &phases, Phase::Golden), visible);
    }

    #[test]
    fn overrides_replace_model_phases() {
        let model = HashMap::from([("a.jpg".to_string(), vec![Phase::Day])]);
        let mut curation = Curation::default();
        curation.sun_overrides.insert(
            "a.jpg".to_string(),
            SunOverride { phases: vec!["night".into(), "twilight".into()], at: String::new() },
        );
        let effective = effective_phases(&model, &curation);
        assert_eq!(effective["a.jpg"], vec![Phase::Night, Phase::Twilight]);
    }

    #[test]
    fn curation_round_trips_fields_it_does_not_know() {
        let text = r#"{"version":1,"hidden":{},"futureThing":{"x":1}}"#;
        let curation: Curation = serde_json::from_str(text).unwrap();
        let written = serde_json::to_value(&curation).unwrap();
        assert_eq!(written["futureThing"]["x"], 1);
        // Empty overrides are omitted, so older files stay byte-for-byte stable.
        assert!(written.get("sunOverrides").is_none());
    }
}
