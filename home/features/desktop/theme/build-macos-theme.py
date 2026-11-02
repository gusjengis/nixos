#!/usr/bin/env python3
"""Build freedesktop icons from export-macos-icons.swift's inventory (requires Pillow)."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re

from PIL import Image

from icon_inventory import filter_app_placeholders
from linux_icon_names import LinuxMimeNames

SIZES = (16, 32, 48, 64, 128, 256, 512)
CONTEXTS = {"places": "Places", "apps": "Applications", "mimetypes": "MimeTypes", "devices": "Devices", "status": "Status", "stock": "Stock"}
PLACES = {
    "folder": ["folder", "inode-directory", "x-directory-normal"],
    "user-home": ["user-home", "folder-home"],
    "user-desktop": ["user-desktop", "folder-desktop"],
    "folder-documents": ["folder-documents"],
    "folder-download": ["folder-download", "folder-downloads"],
    "folder-music": ["folder-music"],
    "folder-pictures": ["folder-pictures"],
    "folder-videos": ["folder-videos"],
    "folder-publicshare": ["folder-publicshare"],
    "applications-other": ["applications-other", "folder-applications"],
    "drive-harddisk": ["drive-harddisk", "drive-harddisk-system", "drive-harddisk-root"],
    "network-workgroup": ["network-workgroup", "network-server", "folder-remote"],
}
RESOURCES = {
    "TrashIcon": ("places", ["user-trash"]),
    "FullTrashIcon": ("places", ["user-trash-full"]),
    "GenericDocumentIcon": ("mimetypes", ["application-octet-stream", "unknown"]),
    "GenericFontIcon": ("mimetypes", ["font-x-generic", "application-x-font-ttf", "application-x-font-otf"]),
    "GenericNetworkIcon": ("places", ["network-workgroup", "network-server", "folder-remote"]),
    "GenericAirDiskIcon": ("devices", ["drive-harddisk-usb", "drive-removable-media"]),
    "OpenFolderIcon": ("places", ["folder-open"]),
    "DeveloperFolderIcon": ("places", ["folder-development"]),
    "LibraryFolderIcon": ("places", ["folder-library"]),
    "SystemFolderIcon": ("places", ["folder-system"]),
    "UsersFolderIcon": ("places", ["folder-users"]),
    "UtilitiesFolder": ("places", ["folder-utilities"]),
    "SmartFolderIcon": ("places", ["folder-saved-search"]),
    "CDAudioVolumeIcon": ("devices", ["media-optical", "media-optical-audio"]),
    "SidebarNetwork": ("places", ["folder-remote-symbolic", "network-workgroup-symbolic"]),
    "SidebarGenericFolder": ("places", ["folder-symbolic"]),
    "SidebarHomeFolder": ("places", ["user-home-symbolic"]),
    "SidebarDesktopFolder": ("places", ["user-desktop-symbolic"]),
    "SidebarDocumentsFolder": ("places", ["folder-documents-symbolic"]),
    "SidebarDownloadsFolder": ("places", ["folder-download-symbolic"]),
    "SidebarMusicFolder": ("places", ["folder-music-symbolic"]),
    "SidebarPicturesFolder": ("places", ["folder-pictures-symbolic"]),
    "SidebarMoviesFolder": ("places", ["folder-videos-symbolic"]),
    "AlertCautionBadgeIcon": ("status", ["dialog-warning"]),
    "AlertStopIcon": ("status", ["dialog-error"]),
    "AlertNoteIcon": ("status", ["dialog-information"]),
}
TYPES = {
    "public.data": ["application-octet-stream"],
    "public.plain-text": ["text-plain", "text-x-generic"],
    "public.rtf": ["application-rtf", "text-rtf"],
    "public.html": ["text-html", "application-xhtml+xml"],
    "public.xml": ["application-xml", "text-xml"],
    "public.json": ["application-json"],
    "public.yaml": ["application-yaml", "text-yaml", "text-x-yaml"],
    "public.source-code": ["text-x-source", "text-x-script"],
    "public.python-script": ["text-x-python", "application-x-python"],
    "public.shell-script": ["application-x-shellscript", "text-x-shellscript"],
    "public.jpeg": ["image-jpeg", "image-x-generic"],
    "public.png": ["image-png"],
    "public.tiff": ["image-tiff"],
    "com.compuserve.gif": ["image-gif"],
    "org.webmproject.webp": ["image-webp"],
    "public.svg-image": ["image-svg+xml"],
    "public.audio": ["audio-x-generic"],
    "public.mp3": ["audio-mpeg"],
    "public.mpeg-4-audio": ["audio-mp4", "audio-x-m4a"],
    "com.microsoft.waveform-audio": ["audio-x-wav", "audio-wav"],
    "public.movie": ["video-x-generic"],
    "public.mpeg-4": ["video-mp4"],
    "com.apple.quicktime-movie": ["video-quicktime"],
    "com.adobe.pdf": ["application-pdf"],
    "public.zip-archive": ["application-zip", "package-x-generic", "application-x-archive"],
    "org.gnu.gnu-zip-archive": ["application-gzip", "application-x-gzip"],
    "public.tar-archive": ["application-x-tar"],
    "public.font": ["font-x-generic"],
    "com.apple.disk-image": ["application-x-apple-diskimage", "application-x-cd-image"],
    "public.calendar-event": ["text-calendar"],
    "public.vcard": ["text-vcard", "text-x-vcard"],
    "org.openxmlformats.wordprocessingml.document": ["application-vnd.openxmlformats-officedocument.wordprocessingml.document", "x-office-document"],
    "org.openxmlformats.spreadsheetml.sheet": ["application-vnd.openxmlformats-officedocument.spreadsheetml.sheet", "x-office-spreadsheet"],
    "org.openxmlformats.presentationml.presentation": ["application-vnd.openxmlformats-officedocument.presentationml.presentation", "x-office-presentation"],
}
APPS = {
    "com.apple.finder": ["system-file-manager", "org.xfce.thunar", "Thunar", "thunar", "io.github.lgse.Strata"],
    "com.apple.Safari": ["web-browser"],
    "com.apple.Terminal": ["utilities-terminal"],
    "com.apple.systempreferences": ["preferences-system", "org.gnome.Settings"],
    "com.apple.calculator": ["accessories-calculator"],
    "com.apple.Preview": ["org.gnome.Loupe", "org.gnome.Evince"],
    "com.apple.TextEdit": ["accessories-text-editor"],
    "com.apple.Music": ["multimedia-audio-player"],
    "com.apple.QuickTimePlayerX": ["multimedia-video-player"],
    "com.apple.iCal": ["office-calendar"],
    "com.google.Chrome": ["google-chrome", "google-chrome-stable"],
    "org.mozilla.firefox": ["firefox"],
    "com.microsoft.VSCode": ["code", "visual-studio-code"],
    "com.tinyspeck.slackmacgap": ["slack", "webapp-slack"],
    "com.hnc.Discord": ["discord", "discord-canary", "webapp-discord"],
    "com.openai.chat": ["chatgpt", "webapp-chatgpt"],
    "com.microsoft.Outlook": ["outlook", "webapp-outlook"],
    "com.microsoft.OneDrive": ["onedrive", "webapp-onedrive"],
    "com.microsoft.Excel": ["excel", "webapp-excel"],
    "us.zoom.xos": ["Zoom", "zoom"],
    "com.bambulab.bambu-studio": ["BambuStudio", "bambu-studio", "com.bambulab.BambuStudio"],
    "com.valvesoftware.steam": ["steam", "com.valvesoftware.Steam"],
    "com.obsproject.obs-studio": ["com.obsproject.Studio", "obs", "obs-studio"],
    "com.1password.1password": ["1password", "com.onepassword.OnePassword"],
    "com.anthropic.claudefordesktop": ["claude", "webapp-claude"],
    "net.whatsapp.WhatsApp": ["whatsapp", "webapp-whatsapp"],
    "com.todoist.mac.Todoist": ["todoist", "webapp-todoist"],
    "org.gimp.gimp": ["gimp", "org.gimp.GIMP"],
    "org.libreoffice.script": ["libreoffice", "libreoffice-startcenter"],
    "org.prismlauncher.PrismLauncher": ["prismlauncher"],
    "cc.arduino.IDE2": ["arduino", "arduino-ide"],
    "io.mpv": ["mpv"],
    "md.obsidian": ["obsidian"],
    "com.spotify.client": ["spotify"],
}


def build(source: Path, destination: Path):
    # The installed theme is an out-of-store directory symlink. Relative asset
    # links must use its physical repository path, not ~/.local/share/icons.
    source = source.resolve()
    destination = destination.resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    assets = destination / "assets"
    assets.mkdir(exist_ok=True)
    links = set()
    owners = {}
    mime_database = LinuxMimeNames()
    generated_manifest = destination / "generated-apps.json"
    generated_names = {entry["icon"] for entry in json.loads(generated_manifest.read_text())} if generated_manifest.exists() else set()
    previous_mapping_file = destination / "linux-mappings.json"
    previous_mappings = json.loads(previous_mapping_file.read_text()) if previous_mapping_file.exists() else []
    inventory, fallback, placeholders = filter_app_placeholders(manifest)
    placeholder_assets = {
        Path(path).stem + suffix
        for entry in placeholders for path in entry["files"].values()
        for suffix in (".png", "-app-v1.png")
    }
    removed_aliases = 0
    # Retire only links to identified placeholder artwork, including old stock
    # names and app IDs. Never remove generated or otherwise unrelated files.
    for link in destination.glob("*x*/*/*.png"):
        if link.is_symlink() and link.readlink().name in placeholder_assets:
            link.unlink()
            removed_aliases += 1

    def install(entry, category, names):
        for size in SIZES:
            image = source / entry["files"].get(str(size), entry["files"]["512"])
            if entry is not fallback and image.name in placeholder_assets:
                # A valid large icon can still have a generic small variant.
                # Scale its real artwork rather than publishing that placeholder.
                image = source / entry["files"]["512"]
            target = assets / (image.stem + "-app-v1.png" if category == "apps" else image.name)
            if category != "apps" and target.is_symlink():
                expected = os.path.relpath(image, assets)
                if target.readlink() != Path(expected):
                    target.unlink()
                    target.symlink_to(expected)
            if not target.exists():
                if category == "apps":
                    # macOS includes Dock padding in the canvas. Linux launchers
                    # size that canvas directly; fit visible art to 94% instead.
                    artwork = Image.open(image).convert("RGBA")
                    bounds = artwork.getchannel("A").point(lambda value: 255 if value >= 64 else 0).getbbox()
                    if not bounds:
                        raise ValueError(f"Empty app icon: {image}")
                    left, top, right, bottom = bounds
                    side = max(right - left, bottom - top) / 0.94
                    cx, cy = (left + right) / 2, (top + bottom) / 2
                    artwork.crop(tuple(round(value) for value in
                        (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2))) \
                        .resize(artwork.size, Image.Resampling.LANCZOS).save(target)
                else:
                    target.symlink_to(os.path.relpath(image, assets))
            directory = destination / f"{size}x{size}" / category
            directory.mkdir(parents=True, exist_ok=True)
            for name in names:
                link = directory / f"{name}.png"
                if link.is_symlink():
                    link.unlink()
                elif link.exists() and category == "apps" and name in generated_names:
                    # A newly imported native app supersedes our own generated
                    # artwork, without taking over unrelated custom icon files.
                    link.unlink()
                elif link.exists():
                    raise FileExistsError(link)
                link.symlink_to(os.path.relpath(target, directory))
                links.add(str(link.relative_to(destination)))
                if size == 128 and category != "stock":
                    owners[f"{category}/{name}"] = (entry["kind"], entry["id"], entry["source"])

    # Stock names expose real artwork; semantic icons override old resources.
    entries = sorted(inventory, key=lambda entry: (entry["kind"] != "resource", entry["source"]))
    # Older mapping mistook Word's Open XML helper for the Excel application.
    # Drop only aliases still pointing at that helper's imported artwork.
    for entry in entries:
        if entry["kind"] == "app" and entry["id"] == "com.microsoft.openxml.excel.app":
            obsolete = {Path(path).stem + suffix for path in entry["files"].values()
                        for suffix in (".png", "-app-v1.png")}
            for size in SIZES:
                for name in ("excel", "webapp-excel"):
                    link = destination / f"{size}x{size}/apps/{name}.png"
                    if link.is_symlink() and link.resolve().name in obsolete:
                        link.unlink()
    # Apply extension-derived mappings before explicit MIME identities. Curated
    # aliases remain authoritative when multiple UTIs describe the same format.
    entries.sort(key=lambda entry: (entry["kind"] != "resource",
        entry["kind"] == "type" and bool(entry.get("mime")),
        entry["kind"] == "type" and entry["id"] in TYPES, entry["source"]))
    for entry in entries:
        kind, name = entry["kind"], entry["id"]
        stock = "macos-" + re.sub(r"[^a-zA-Z0-9._+-]", "-", name)
        unique = hashlib.sha256(entry["source"].encode()).hexdigest()[:10]
        install(entry, "stock", [stock, f"{stock}-{unique}"])
        if kind == "resource" and name in RESOURCES:
            category, names = RESOURCES[name]
            install(entry, category, names)
        elif kind == "place" and name in PLACES:
            category = "devices" if name == "drive-harddisk" else "places"
            install(entry, category, PLACES[name])
        elif kind == "type":
            mime = entry.get("mime", "")
            names = set() if mime_database.canonical(mime).startswith("inode/") else {
                *TYPES.get(name, []), *mime_database.names(entry), *([mime.replace("/", "-")] if mime else [])}
            install(entry, "mimetypes", sorted(names))
        elif kind == "app":
            # Download URLs are provenance, not launcher names. Infer a bundle
            # filename only for actual captured filesystem paths.
            app_names = ([Path(entry["source"]).stem.lower().replace(" ", "-")]
                         if "://" not in entry["source"] else [])
            install(entry, "apps", [name, *app_names, *APPS.get(name, [])])

    # One logical fallback, with the theme's normal resolution variants. Do not
    # expose the same placeholder under app names, MIME types, or stock aliases.
    install(fallback, "apps", ["application-x-executable"])
    # Corrected mappings must also retire their previous links. Restrict this
    # to files still pointing at that recorded source's assets, so user-created
    # overrides and generated icons remain untouched.
    by_identity = {(entry["kind"], entry["id"], entry["source"]): entry for entry in manifest["entries"]}
    for previous in previous_mappings:
        identity = (previous["kind"], previous["id"], previous["source"])
        old_entry = by_identity.get(identity)
        if not old_entry:
            continue
        old_assets = {Path(path).stem + suffix for path in old_entry["files"].values()
                      for suffix in (".png", "-app-v1.png")}
        for alias in previous["aliases"]:
            if alias in owners:
                continue
            for size in SIZES:
                link = destination / f"{size}x{size}" / (alias + ".png")
                if link.is_symlink() and link.readlink().name in old_assets:
                    link.unlink()
    fallback_assets = {
        (destination / f"{size}x{size}/apps/application-x-executable.png").readlink().name
        for size in SIZES
    }
    for name in placeholder_assets - fallback_assets:
        path = assets / name
        if path.is_file():
            path.unlink()

    mappings = {}
    for alias, identity in owners.items():
        mappings.setdefault(identity, []).append(alias)
    metadata = [{"kind": kind, "id": name, "source": source_path, "aliases": sorted(aliases)}
                for (kind, name, source_path), aliases in sorted(mappings.items())]
    temporary = destination / ".linux-mappings.json.tmp"
    temporary.write_text(json.dumps(metadata, indent=2) + "\n")
    temporary.replace(destination / "linux-mappings.json")

    write_index(destination)
    print(f"Built {destination}: {len(inventory)} retained sources, {len(links)} icon links")
    print(f"Filtered {len(placeholders)} placeholder records; removed {removed_aliases} old links; kept application-x-executable fallback")


def write_index(destination):
    destination.mkdir(parents=True, exist_ok=True)
    index = configparser.ConfigParser(interpolation=None)
    index.optionxform = str
    directories = [f"{size}x{size}/{category}" for size in SIZES for category in CONTEXTS]
    index["Icon Theme"] = {"Name": "MacOS Native", "Comment": "Icons extracted from your Mac",
        "Inherits": "Colloid-Dark-Remote,Papirus-Dark,hicolor", "Directories": ",".join(directories)}
    for size in SIZES:
        for category, context in CONTEXTS.items():
            index[f"{size}x{size}/{category}"] = {"Size": str(size), "Type": "Fixed", "Context": context}
            (destination / f"{size}x{size}" / category).mkdir(parents=True, exist_ok=True)
    with (destination / "index.theme").open("w") as file:
        index.write(file, space_around_delimiters=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.source, args.destination)
