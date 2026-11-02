"""Resolve exported MIME/extension metadata using Linux's shared MIME database."""
import os
from pathlib import Path

# Known format identities whose macOS export omits a registered MIME spelling.
# Do not infer vendor formats merely because Linux recognizes their suffix.
TYPE_MIME_FALLBACKS = {
    "com.adobe.illustrator.ai-image": "application/illustrator",
    "com.apple.chess.pgn": "application/vnd.chess-pgn",
    "com.apple.ibooks.epub": "application/epub+zip",
    "com.apple.icns": "image/x-icns",
    "com.apple.installer-package-archive": "application/x-xar",
    "com.apple.iwork.keynote.key": "application/vnd.apple.keynote",
    "com.apple.iwork.numbers.numbers": "application/vnd.apple.numbers",
    "com.apple.iwork.pages.pages": "application/vnd.apple.pages",
    "com.apple.log": "text/x-log",
    "com.apple.macpaint-image": "image/x-macpaint",
    "com.apple.mail.mbox": "application/mbox",
    "com.apple.pict": "image/x-pict",
    "com.apple.pkpass-data": "application/vnd.apple.pkpass",
    "com.apple.protected-mpeg-4-audio-b": "audio/x-m4b",
    "com.audible.aa-audiobook": "audio/vnd.audible",
    "com.ilm.openexr-image": "image/x-exr",
    "com.microsoft.dds": "image/x-dds",
    "com.microsoft.word.mhtml": "application/x-mimearchive",
    "com.microsoft.word.openxmlformats.wordprocessingml.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "com.microsoft.word.openxmlformats.wordprocessingml.template": "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    "com.microsoft.word.strictopenxmlformats.wordprocessingml.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "com.sgi.sgi-image": "image/x-sgi",
    "com.topografix.gpx": "application/gpx+xml",
    "org.gnu.gnu-zip-tar-archive": "application/x-compressed-tar",
    "org.khronos.astc": "image/astc",
    "org.khronos.ktx": "image/ktx",
    "org.khronos.ktx2": "image/ktx2",
    "org.oasis-open.xliff": "application/xliff+xml",
    "org.tukaani.tar-xz-archive": "application/x-xz-compressed-tar",
}


class LinuxMimeNames:
    def __init__(self, roots=None):
        if roots is None:
            roots = [*(Path(path) for path in os.environ.get("XDG_DATA_DIRS", "").split(":") if path),
                     Path.home() / ".nix-profile/share", Path("/run/current-system/sw/share"),
                     Path("/usr/local/share"), Path("/usr/share")]
        self.types, self.aliases, self.icons, self.extensions = set(), {}, {}, {}
        for root in dict.fromkeys(roots):
            base = root / "mime"
            if not base.is_dir():
                continue
            for line in self.lines(base / "types"):
                self.types.add(line)
            for line in self.lines(base / "aliases"):
                alias, canonical = line.split()
                self.aliases.setdefault(alias, canonical)
            for line in self.lines(base / "icons"):
                mime, icon = line.split(":", 1)
                self.icons.setdefault(mime, icon)
            for line in self.lines(base / "globs2"):
                weight, mime, pattern, *_ = line.split(":")
                if not pattern.startswith("*.") or any(character in pattern[2:] for character in "*?[]"):
                    continue
                extension = pattern[2:]
                rank, candidates = self.extensions.setdefault(extension, (int(weight), set()))
                if int(weight) > rank:
                    self.extensions[extension] = (int(weight), {mime})
                elif int(weight) == rank:
                    candidates.add(mime)
        self.type_spellings = {mime.casefold(): mime for mime in self.types}
        self.alias_spellings = {alias.casefold(): canonical for alias, canonical in self.aliases.items()}

    @staticmethod
    def lines(path):
        if path.is_file():
            return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
        return []

    def canonical(self, mime):
        visited = set()
        while mime.casefold() in self.alias_spellings and mime.casefold() not in visited:
            visited.add(mime.casefold())
            mime = self.alias_spellings[mime.casefold()]
        return self.type_spellings.get(mime.casefold(), mime)

    def names(self, entry):
        mime = self.canonical(entry.get("mime", ""))
        # macOS document bundles (for example .logarchive) can advertise
        # inode/directory. That describes their container, not their artwork's
        # identity. Filesystem icons belong to the dedicated places mapping.
        if mime.startswith("inode/"):
            return []
        candidates = {mime} if mime in self.types else set()
        if not candidates:
            explicit = self.canonical(TYPE_MIME_FALLBACKS.get(entry.get("id"), ""))
            if explicit in self.types:
                candidates.add(explicit)
        if not candidates:
            if not entry.get("id", "").startswith("public."):
                return []
            for extension in entry.get("extensions", []):
                _, matches = self.extensions.get(extension, (0, set()))
                canonical = {self.canonical(match) for match in matches}
                # A suffix such as .dat can describe unrelated formats. Never
                # invent a mapping when Linux's own data is ambiguous.
                if len(canonical) == 1:
                    candidates.update(canonical)
        names = set()
        for candidate in candidates:
            if candidate.startswith("inode/"):
                continue
            family = {candidate, *(alias for alias in self.aliases if self.canonical(alias) == candidate)}
            names.update(value.replace("/", "-") for value in family)
            names.update(self.icons[value] for value in family if value in self.icons)
        return sorted(names)
