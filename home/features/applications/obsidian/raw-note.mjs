// Creates a raw note by executing the vault's "Templates/Raw Note.md" with
// Templater's own parser, headless: no Obsidian, no GUI.
//
// The template is the only definition of the raw note format. It runs here
// exactly as in Obsidian (same rusty_engine WASM parser, same tag syntax, real
// JavaScript), so edits made in Obsidian, code included, apply to every
// capture script. Only the `tp` object is a stand-in: it implements the parts
// of Templater's API that make sense without Obsidian and throws on the rest,
// so an unsupported template fails loudly instead of writing a wrong note.
//
// Headless extras for the template:
//   tp.capture = { source, text, created, headless: true }
//   (undefined inside Obsidian, so templates can use `tp.capture?.source`).
//
// Usage:
//   raw-note [--source S] [--created ISO] [--vault DIR]
//            [--name-token T] [--attach SRC=NAME ...] [--attach-dir DIR]
//            [TEXT]                (stdin when TEXT is omitted)
//
// --name-token T: every occurrence of T in the rendered note and in attachment
//   NAMEs is replaced with the final note name (without .md), for embeds whose
//   names depend on the note.
// --attach SRC=NAME: copy SRC to <attach-dir>/NAME (vault-relative, default
//   Raw/Images) before the note appears, so its embeds are never broken.
//
// Prints the path of the created note.

import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";

const lib = process.env.RAW_NOTE_LIB;
if (!lib) throw new Error("RAW_NOTE_LIB is not set");
const moment = createRequire(import.meta.url)(path.join(lib, "moment"));
const { initSync, ParserConfig, Renderer } = await import(
  path.join(lib, "rusty_engine", "rusty_engine.js")
);

const TEMPLATE = "Templates/Raw Note.md";
const START_FOLDER = "Raw";
const MAX_ATTEMPTS = 20;

class Unsupported extends Error {}

function strict(name, object = {}) {
  return new Proxy(object, {
    get(target, key) {
      if (key in target || typeof key === "symbol" || key === "then") {
        return target[key];
      }
      throw new Unsupported(`${name}.${String(key)} is not available headless`);
    },
  });
}

// Obsidian's normalizePath.
function normalizePath(p) {
  p = p.replace(/[\\/\u00A0\u202F]+/g, (m) => (/[\\/]/.test(m) ? "/" : " "));
  p = p.replace(/^\/+|\/+$/g, "");
  return (p === "" ? "/" : p).normalize("NFC");
}

function vaultPath(vault, relative) {
  const normalized = normalizePath(relative);
  const absolute = path.resolve(vault, normalized);
  if (!absolute.startsWith(path.resolve(vault) + path.sep)) {
    throw new Error(`path escapes the vault: ${relative}`);
  }
  return absolute;
}

function untitled(vault, folder) {
  for (let n = 0; ; n++) {
    const candidate = `${folder}/Untitled${n ? ` ${n}` : ""}.md`;
    if (!fs.existsSync(vaultPath(vault, candidate))) return candidate;
  }
}

const TFILE = Symbol("headless TFile");
const MAX_CREATE_DEPTH = 10;

function tfile(relative) {
  return {
    [TFILE]: true,
    path: relative,
    name: path.posix.basename(relative),
    basename: path.posix.basename(relative, path.posix.extname(relative)),
    extension: path.posix.extname(relative).slice(1),
    parent: { path: path.posix.dirname(relative) },
  };
}

// Obsidian's vault.getAvailablePath: "name.md", else "name 1.md", "name 2.md", ...
function availablePath(vault, base, extension) {
  for (let n = 0; ; n++) {
    const candidate = `${base}${n ? ` ${n}` : ""}.${extension}`;
    if (!fs.existsSync(vaultPath(vault, candidate))) return candidate;
  }
}

// Writes content to a new vault file; false if the name was taken meanwhile.
function writeNew(vault, relative, content) {
  const destination = vaultPath(vault, relative);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  // Staged at the vault root under a dot name, which Obsidian and headless
  // sync ignore; link() refuses to overwrite.
  const staged = fs.mkdtempSync(path.join(vault, ".capture."));
  const file = path.join(staged, "note");
  try {
    fs.writeFileSync(file, content, { mode: 0o644 });
    fs.chmodSync(file, 0o644);
    fs.linkSync(file, destination);
    return true;
  } catch (error) {
    if (error.code === "EEXIST") return false;
    throw error;
  } finally {
    fs.rmSync(staged, { recursive: true, force: true });
  }
}

function makeTp({ vault, target, capture, created, renderer, depth = 0 }) {
  const file = () => ({
    path: target.path,
    basename: path.posix.basename(target.path, ".md"),
    extension: "md",
    parentPath: path.posix.dirname(target.path),
  });
  const dateNow = (format = "YYYY-MM-DD", offset, reference, referenceFormat) => {
    if (reference && !moment(reference, referenceFormat).isValid()) {
      throw new Error("Invalid reference date format");
    }
    let duration;
    if (typeof offset === "string") duration = moment.duration(offset);
    else if (typeof offset === "number") duration = moment.duration(offset, "days");
    return moment(reference, referenceFormat).add(duration).format(format);
  };
  let cursorUsed = false;

  const tp = {
    app: strict("tp.app"),
    obsidian: strict("tp.obsidian", {
      Platform: {
        isDesktop: true,
        isMobile: false,
        isDesktopApp: true,
        isMobileApp: false,
        isIosApp: false,
        isAndroidApp: false,
        isPhone: false,
        isTablet: false,
        isMacOS: false,
        isWin: false,
        isLinux: process.platform === "linux",
        isSafari: false,
      },
      moment,
      normalizePath,
    }),
    config: {
      template_file: { path: TEMPLATE, basename: path.posix.basename(TEMPLATE, ".md") },
      get target_file() {
        return file();
      },
      run_mode: 2,
      active_file: null,
    },
    date: strict("tp.date", {
      now: dateNow,
      tomorrow: (format = "YYYY-MM-DD") => moment().add(1, "days").format(format),
      yesterday: (format = "YYYY-MM-DD") => moment().add(-1, "days").format(format),
      weekday: (format = "YYYY-MM-DD", weekday, reference, referenceFormat) =>
        moment(reference, referenceFormat).weekday(weekday).format(format),
    }),
    file: strict("tp.file", {
      get title() {
        return file().basename;
      },
      content: "",
      tags: [],
      creation_date: (format = "YYYY-MM-DD HH:mm") => moment(created).format(format),
      last_modified_date: (format = "YYYY-MM-DD HH:mm") => moment(created).format(format),
      // Inside Obsidian the cursor marks where typing starts; headless it is
      // where the captured text goes (first cursor only).
      cursor: () => {
        if (cursorUsed) return "";
        cursorUsed = true;
        return capture.text;
      },
      exists: async (p) => fs.existsSync(vaultPath(vault, p)),
      // Obsidian resolves link paths; headless accepts vault paths, with or
      // without .md.
      find_tfile: (linkpath) => {
        const normalized = normalizePath(linkpath);
        for (const candidate of [normalized, `${normalized}.md`]) {
          const absolute = vaultPath(vault, candidate);
          if (fs.existsSync(absolute) && fs.statSync(absolute).isFile()) return tfile(candidate);
        }
        return null;
      },
      // Templater's create_new: renders the template (a TFile or template
      // text) for a new file at folder/filename, picking "filename 1" etc. if
      // taken, and writes it immediately. open_new has no meaning headless.
      create_new: async (template, filename, _openNew = false, folder) => {
        if (depth + 1 > MAX_CREATE_DEPTH) {
          throw new Error(`Reached create_new depth limit (max = ${MAX_CREATE_DEPTH})`);
        }
        let content;
        if (template?.[TFILE]) content = fs.readFileSync(vaultPath(vault, template.path), "utf8");
        else if (typeof template === "string") content = template;
        else throw new Error("tp.file.create_new: template not found");
        if (folder === undefined || folder === null) {
          throw new Error("tp.file.create_new needs a folder headless (Obsidian's default location is unknown)");
        }
        const folderPath = typeof folder === "string" ? folder : folder.path;
        const base = normalizePath(`${folderPath}/${filename || "Untitled"}`);
        for (;;) {
          const child = { path: availablePath(vault, base, "md") };
          const childTp = makeTp({
            vault,
            target: child,
            // No captured text: the new note is not the capture.
            capture: { ...capture, text: "" },
            created,
            renderer,
            depth: depth + 1,
          });
          const rendered = await renderer.render_content(content, childTp);
          if (writeNew(vault, child.path, rendered)) return tfile(child.path);
        }
      },
      folder: (relative = false) =>
        relative ? file().parentPath : path.posix.basename(file().parentPath),
      path: (relative = false) =>
        relative ? target.path : path.join(vault, target.path),
      move: async (newPath) => {
        target.path = normalizePath(`${newPath}.md`);
        vaultPath(vault, target.path);
        return "";
      },
      rename: async (name) => {
        if (/[\\/:]+/.test(name)) {
          throw new Error("File name cannot contain any of these characters: \\ / :");
        }
        target.path = normalizePath(`${file().parentPath}/${name}.md`);
        return "";
      },
    }),
    frontmatter: {},
    hooks: strict("tp.hooks"),
    system: strict("tp.system"),
    web: strict("tp.web"),
    user: strict("tp.user"),
    capture: { ...capture, headless: true },
  };
  return strict("tp", tp);
}

function copyAttachment(src, destination) {
  const staged = `${destination}.${process.pid}.tmp`;
  fs.copyFileSync(src, staged);
  fs.chmodSync(staged, 0o644);
  fs.renameSync(staged, destination);
}

async function create(options) {
  const { vault, text, source, created, nameToken, attachments, attachDir } = options;
  const template = fs.readFileSync(vaultPath(vault, TEMPLATE), "utf8");

  initSync(fs.readFileSync(path.join(lib, "rusty_engine", "rusty_engine_bg.wasm")));
  // Same configuration as Templater 2.x.
  const renderer = new Renderer(new ParserConfig("<%", "%>", "\0", "*", "-", "_", "tR"));

  // Freeze the clock at capture time so tp.date.* describes the capture,
  // not the moment it was processed.
  moment.now = () => created.valueOf();
  globalThis.moment = moment;

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    const target = { path: untitled(vault, START_FOLDER) };
    const tp = makeTp({
      vault,
      target,
      capture: { source, text, created: created.format() },
      created,
      renderer,
    });
    let content = await renderer.render_content(template, tp);

    const destination = vaultPath(vault, target.path);
    if (fs.existsSync(destination)) continue;
    const name = path.basename(destination, ".md");
    if (nameToken) content = content.replaceAll(nameToken, name);

    fs.mkdirSync(path.dirname(destination), { recursive: true });
    const copied = [];
    for (const [src, attachName] of attachments) {
      const dir = vaultPath(vault, attachDir);
      fs.mkdirSync(dir, { recursive: true });
      const attachDestination = path.join(
        dir,
        nameToken ? attachName.replaceAll(nameToken, name) : attachName,
      );
      copyAttachment(src, attachDestination);
      copied.push(attachDestination);
    }

    // A concurrent capture that took the name first makes us render again
    // (and see it as taken).
    if (writeNew(vault, target.path, content)) return destination;
    for (const f of copied) fs.rmSync(f, { force: true });
  }
  throw new Error(`no free note name after ${MAX_ATTEMPTS} attempts`);
}

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    source: { type: "string", default: process.env.CAPTURE_SOURCE ?? "desktop-dictation" },
    created: { type: "string" },
    vault: {
      type: "string",
      default: process.env.OBSIDIAN_VAULT ?? path.join(process.env.HOME, "Documents/Obsidian/Notes"),
    },
    "name-token": { type: "string" },
    attach: { type: "string", multiple: true, default: [] },
    "attach-dir": { type: "string", default: "Raw/Images" },
  },
});

const text = positionals.length ? positionals.join(" ") : fs.readFileSync(0, "utf8");
// Nothing said, nothing saved.
if (!text.trim()) process.exit(0);

const created = values.created ? moment.parseZone(values.created, moment.ISO_8601, true) : moment();
if (!created.isValid()) throw new Error(`invalid --created: ${values.created}`);

const attachments = values.attach.map((spec) => {
  const at = spec.lastIndexOf("=");
  if (at < 1) throw new Error(`--attach needs SRC=NAME: ${spec}`);
  const name = spec.slice(at + 1);
  if (name.includes("/") || name.startsWith(".")) throw new Error(`bad attachment name: ${name}`);
  return [spec.slice(0, at), name];
});

try {
  const note = await create({
    vault: values.vault,
    text: text.replace(/^\n+|\n+$/g, ""),
    source: values.source,
    // Local time, like notes typed in Obsidian.
    created: created.local(),
    nameToken: values["name-token"],
    attachments,
    attachDir: values["attach-dir"],
  });
  console.log(note);
} catch (error) {
  console.error(`raw-note: ${error instanceof Unsupported ? "template uses " : ""}${error.message}`);
  process.exit(1);
}
