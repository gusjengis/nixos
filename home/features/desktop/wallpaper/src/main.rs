// wallpaperctl: fast CLI for the wallpaper picker's hot path.
//
// Design notes (see /etc/nixos conversation history for the full story):
// - Palette lookup is cache-only. This binary never shells out to matugen;
//   it reads the "palette" field cached in metadata.json by
//   generate-palettes.py. A cache miss just leaves colors.json untouched
//   (prints a hint to stderr) instead of blocking the wallpaper swap.
// - Wallpaper is applied via `hyprctl hyprpaper wallpaper mon,path,fit`,
//   talking to the hyprpaper daemon (started on demand if its IPC socket
//   isn't present yet). hyprpaper's protocol has no transition/fade concept,
//   so every switch is a hard cut - that's intentional, not a bug.
// - wallpapers() is scanned once per invocation and threaded through, unlike
//   the old Python version which rescanned the ~900-file directory twice.

use std::collections::HashSet;
use std::env;
use std::fs;
use std::io;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use rand::seq::SliceRandom;
use rand::thread_rng;
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

struct Paths {
    wallpaper_dir: PathBuf,
    metadata_file: PathBuf,
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

fn randomized_order(paths: &Paths, available: &[PathBuf]) -> Vec<PathBuf> {
    let stored: Option<Vec<PathBuf>> = fs::read_to_string(&paths.order_file)
        .ok()
        .and_then(|text| serde_json::from_str::<Vec<String>>(&text).ok())
        .map(|list| list.into_iter().map(PathBuf::from).collect());

    if let Some(ordered) = &stored {
        let ordered_set: HashSet<&PathBuf> = ordered.iter().collect();
        let available_set: HashSet<&PathBuf> = available.iter().collect();
        if ordered.len() == available.len() && ordered_set == available_set {
            return ordered.clone();
        }
    }

    let mut shuffled = available.to_vec();
    shuffled.shuffle(&mut thread_rng());
    let _ = save_order(paths, &shuffled);
    shuffled
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

fn hyprpaper_socket_path() -> Option<PathBuf> {
    let runtime_dir = env::var("XDG_RUNTIME_DIR").ok()?;
    let instance = env::var("HYPRLAND_INSTANCE_SIGNATURE").ok()?;
    Some(PathBuf::from(runtime_dir).join("hypr").join(instance).join(".hyprpaper.sock"))
}

/// Existence alone isn't enough: a hyprpaper that died without cleaning up
/// leaves a stale socket *file* behind, which still passes `.exists()` but
/// refuses connections. Only a real connect attempt tells the truth.
fn socket_alive(socket: &Path) -> bool {
    std::os::unix::net::UnixStream::connect(socket).is_ok()
}

fn ensure_daemon() -> Result<(), String> {
    let socket = hyprpaper_socket_path().ok_or("cannot locate hyprpaper socket (not running under Hyprland?)")?;
    if socket_alive(&socket) {
        return Ok(());
    }

    Command::new("hyprpaper")
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
/// Never invokes matugen - that is generate-palettes.py's job, run manually.
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

fn set_wallpaper(paths: &Paths, available: &[PathBuf], raw_path: &str, persist: bool) -> Result<PathBuf, String> {
    let requested = fs::canonicalize(raw_path).map_err(|e| format!("{raw_path}: {e}"))?;
    if !available.contains(&requested) {
        return Err(format!(
            "wallpaper is not a supported image under {}: {}",
            paths.wallpaper_dir.display(),
            requested.display()
        ));
    }

    ensure_daemon()?;

    let arg = format!(",{},cover", requested.display());
    let status = Command::new("hyprctl")
        .args(["hyprpaper", "wallpaper", &arg])
        .status()
        .map_err(|e| format!("failed to run hyprctl: {e}"))?;
    if !status.success() {
        return Err(format!("hyprctl hyprpaper wallpaper failed for {}", requested.display()));
    }

    let filename = requested
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default();
    let colors = cached_palette(paths, filename);
    if colors.is_none() {
        eprintln!(
            "wallpaperctl: no cached palette for {filename}; run wallpaper-generate-palettes to backfill it"
        );
    }

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

fn print_catalog(paths: &Paths, available: &[PathBuf], active: Option<&PathBuf>) {
    #[derive(Serialize)]
    struct Entry {
        name: String,
        file: String,
        path: String,
        extension: String,
    }
    #[derive(Serialize)]
    struct Catalog {
        current: String,
        #[serde(rename = "metadataFile")]
        metadata_file: String,
        wallpapers: Vec<Entry>,
    }

    let entries: Vec<Entry> = available
        .iter()
        .map(|p| Entry {
            name: p
                .file_stem()
                .and_then(|n| n.to_str())
                .unwrap_or_default()
                .to_string(),
            file: p
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or_default()
                .to_string(),
            path: p.to_string_lossy().to_string(),
            extension: p
                .extension()
                .and_then(|n| n.to_str())
                .unwrap_or_default()
                .to_ascii_uppercase(),
        })
        .collect();

    let catalog = Catalog {
        current: active.map(|p| p.to_string_lossy().to_string()).unwrap_or_default(),
        metadata_file: if paths.metadata_file.is_file() {
            paths.metadata_file.to_string_lossy().to_string()
        } else {
            String::new()
        },
        wallpapers: entries,
    };

    println!("{}", serde_json::to_string(&catalog).unwrap());
}

fn usage_and_exit() -> ! {
    eprintln!("usage: wallpaperctl {{catalog|current|set PATH|preview PATH|random|next|restore}}");
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
    let active = current(&paths, &available);

    let command = args.get(1).map(String::as_str).unwrap_or("");

    match command {
        "catalog" => print_catalog(&paths, &available, active.as_ref()),
        "current" => println!("{}", active.map(|p| p.to_string_lossy().to_string()).unwrap_or_default()),
        "set" if args.len() == 3 => match set_wallpaper(&paths, &available, &args[2], true) {
            Ok(path) => println!("{}", path.display()),
            Err(e) => fail(&e),
        },
        "preview" if args.len() == 3 => match set_wallpaper(&paths, &available, &args[2], false) {
            Ok(path) => println!("{}", path.display()),
            Err(e) => fail(&e),
        },
        "random" | "next" => {
            if let Some(target) = choose_next(&available, active.as_ref()) {
                match set_wallpaper(&paths, &available, &target.to_string_lossy(), true) {
                    Ok(path) => println!("{}", path.display()),
                    Err(e) => fail(&e),
                }
            }
        }
        "restore" => {
            let target = active.clone().or_else(|| choose_next(&available, None));
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
