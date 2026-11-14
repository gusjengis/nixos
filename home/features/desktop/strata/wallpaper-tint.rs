// SPDX-License-Identifier: MIT
// Bridge the desktop's extracted Chameleon material into Finder's CSS colors.
use gtk::{gdk, gio, glib, prelude::*};
use serde::Deserialize;
use std::{cell::{Cell, RefCell}, rc::Rc, time::Duration};

thread_local! {
    static INSTALLED: Cell<bool> = const { Cell::new(false) };
}

#[derive(Deserialize)]
struct Colors {
    surface: [f64; 3],
    footer: [f64; 3],
}

#[derive(Deserialize)]
struct Client {
    pid: u32,
    title: String,
    width: i32,
    height: i32,
    #[serde(flatten)]
    colors: Colors,
}

#[derive(Deserialize)]
struct State {
    default: Colors,
    windows: Vec<Client>,
}

fn color(rgb: [f64; 3]) -> Option<String> {
    rgb.iter().all(|v| v.is_finite() && (0.0..=1.0).contains(v)).then(|| {
        format!("rgb({:.7}%, {:.7}%, {:.7}%)", rgb[0] * 100.0, rgb[1] * 100.0, rgb[2] * 100.0)
    })
}

fn stylesheet(state: &State) -> String {
    let mut css = String::new();
    for widget in gtk::Window::list_toplevels() {
        let Ok(window) = widget.downcast::<gtk::Window>() else { continue };
        let title = window.title().unwrap_or_default();
        let matches: Vec<_> = state.windows.iter()
            .filter(|client| client.pid == std::process::id() && client.title == title.as_str())
            .collect();
        let sized: Vec<_> = matches.iter().copied().filter(|client| {
            (client.width - window.width()).abs() <= 2 && (client.height - window.height()).abs() <= 2
        }).collect();
        // Wayland hides global window coordinates from clients. Match the
        // compositor's identity by process/title and, for duplicate titles,
        // surface size. An ambiguous match must not borrow another window's tint.
        let colors = if matches.len() == 1 { &matches[0].colors }
            else if sized.len() == 1 { &sized[0].colors }
            else { &state.default };
        let (Some(surface), Some(footer)) = (color(colors.surface), color(colors.footer)) else { continue };
        let class = format!("desktop-tint-{:x}", window.as_ptr() as usize);
        if !window.has_css_class(&class) {
            window.add_css_class(&class);
        }
        css.push_str(&format!("window.{class} {{ --finder-content: {surface}; --finder-footer: {footer}; }}\n"));
    }
    css
}

pub(super) fn install() {
    let Some(display) = gdk::Display::default() else { return };
    if INSTALLED.with(|installed| installed.replace(true)) { return; }
    let provider = gtk::CssProvider::new();
    gtk::style_context_add_provider_for_display(&display, &provider, super::theme::COMPOSITOR_GLASS_STYLE_PRIORITY);
    let file = gio::File::for_path(glib::user_state_dir().join("wallpaper/desktop-tint.json"));
    let busy = Rc::new(Cell::new(false));
    let previous = Rc::new(RefCell::new(String::new()));
    glib::timeout_add_local(Duration::from_millis(100), move || {
        if busy.replace(true) { return glib::ControlFlow::Continue; }
        let (file, busy, previous, provider) = (file.clone(), busy.clone(), previous.clone(), provider.clone());
        glib::MainContext::default().spawn_local(async move {
            let css = match file.load_contents_future().await {
                Ok((bytes, _)) => serde_json::from_slice::<State>(&bytes).ok().map(|state| stylesheet(&state)).unwrap_or_default(),
                Err(_) => String::new(),
            };
            if *previous.borrow() != css {
                provider.load_from_string(&css);
                previous.replace(css);
            }
            busy.set(false);
        });
        glib::ControlFlow::Continue
    });
}
