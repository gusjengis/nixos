#!/usr/bin/env python3
"""Archive versioned theme recipes and asset inventories, with content hashes."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = "https://raw.githubusercontent.com/chromium/chromium"
API = "https://api.github.com/repos/chromium/chromium/contents"
DIRECTORIES = [
    "chrome/browser/ui/color", "chrome/browser/ui/color/mac",
    "chrome/browser/ui/color/linux", "chrome/browser/themes",
    "ui/color", "ui/color/mac", "ui/views/style",
]
FILES = [
    "chrome/browser/ui/layout_constants.cc",
    "chrome/browser/ui/layout_constants.h",
    "chrome/browser/ui/views/chrome_layout_provider.cc",
    "chrome/browser/ui/views/chrome_typography.cc",
    "chrome/browser/ui/views/chrome_typography_provider.cc",
    "chrome/browser/ui/views/frame/browser_frame_view_mac.mm",
    "chrome/browser/ui/views/frame/browser_frame_view_linux.cc",
    "chrome/browser/ui/views/frame/browser_frame_view.cc",
    "chrome/browser/ui/views/frame/glass_frame_service.cc",
    "chrome/browser/ui/views/tabs/tab_style_views.cc",
    "chrome/browser/ui/tabs/tab_style.cc",
    "chrome/browser/ui/webui/theme_source.cc",
    "chrome/browser/resources/settings/appearance_page/appearance_page.ts",
    "chrome/browser/resources/settings/appearance_page/appearance_page.html.ts",
    "chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc",
    "chrome/browser/ui/webui/settings/appearance_handler.cc",
    "ui/native_theme/native_theme_mac.mm",
    "ui/native_theme/native_theme_base.cc",
    "ui/gfx/platform_font_mac.mm",
    "ui/gfx/font_render_params_mac.cc",
    "ui/views/layout/layout_provider.cc",
    "ui/views/controls/menu/menu_config_mac.mm",
    "ui/gfx/platform_font_skia.cc",
    "ui/views/BUILD.gn",
    "ui/views/controls/menu/menu_runner_impl.cc",
    "components/renderer_context_menu/views/toolkit_delegate_views.cc",
    "chrome/browser/ui/views/renderer_context_menu/render_view_context_menu_views.cc",
]
ASSETS = ["chrome/app/vector_icons", "components/vector_icons", "ui/views/vector_icons"]


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "chromium-theme-capture"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def capture(version, destination):
    paths = set(FILES)
    manifest = {"version": version, "sources": {}, "assets": {}, "unavailable": {}}
    previous_path = destination / version / "manifest.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    for directory in DIRECTORIES + ASSETS:
        try:
            entries = json.loads(fetch(f"{API}/{directory}?ref={version}"))
        except Exception as error:
            manifest["unavailable"][directory] = str(error)
            continue
        if directory in ASSETS:
            manifest["assets"][directory] = [
                {"path": entry["path"], "gitBlob": entry["sha"],
                 "url": entry["download_url"], "bytes": entry["size"]}
                for entry in entries if entry["type"] == "file"
            ]
            paths.update(entry["path"] for entry in entries if entry["type"] == "file")
        else:
            paths.update(entry["path"] for entry in entries
                         if entry["type"] == "file"
                         and Path(entry["name"]).suffix in {".cc", ".mm", ".h", ".gn", ".inc"}
                         and "test" not in entry["name"])

    def download(path):
        url = f"{ROOT}/{version}/{path}"
        try:
            target = destination / version / path
            old = previous.get("sources", {}).get(path)
            content = target.read_bytes() if old and target.exists() else None
            if content is None or hashlib.sha256(content).hexdigest() != old["sha256"]:
                content = fetch(url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            return path, {"url": url, "sha256": hashlib.sha256(content).hexdigest(),
                          "bytes": len(content)}, None
        except Exception as error:
            return path, None, str(error)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for path, record, error in executor.map(download, sorted(paths)):
            if error:
                manifest["unavailable"][path] = error
            else:
                manifest["sources"][path] = record
    target = destination / version / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"{version}: {len(manifest['sources'])} source files; "
          f"{sum(map(len, manifest['assets'].values()))} indexed assets; "
          f"{len(manifest['unavailable'])} unavailable paths")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("versions", nargs="+")
    args = parser.parse_args()
    for version in args.versions:
        capture(version, args.destination)
