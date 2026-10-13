"""Pool sanitized OpenCode conversation transcripts through the synced vault.

SQLite is read-only. Reasoning, attachments, system prompts and arbitrary message
metadata are never exported. Redaction is best-effort, not a privacy guarantee.
"""

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import yaml

VERSION = 1
PRIVATE_PATH = re.compile(
    r"(?:\.config/secrets|(?:^|[/\s\"'])\.env(?:\b|\.)|\.ssh/|\.gnupg/|"
    r"(?:auth|credentials)\.json|(?:id_rsa|id_ed25519)(?:\b|\.)|"
    r"\.git-credentials|\.netrc|/run/secrets|\.aws/|\.kube/config|"
    r"\.pgpass|sops/age/keys\.txt)", re.IGNORECASE
)
SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|token|authorization|api[_-]?key|private[_-]?key|cookie)", re.IGNORECASE
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def timestamp(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat(timespec="milliseconds")


def redact(text):
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  "[REDACTED PRIVATE KEY]", str(text), flags=re.DOTALL)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
                  r"github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|"
                  r"xox[baprs]-[A-Za-z0-9-]{10,})\b", "[REDACTED TOKEN]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
                  "[REDACTED JWT]", text)
    text = re.sub(r"\bAGE-SECRET-KEY-1[0-9A-Z]{50,}\b", "[REDACTED AGE KEY]", text)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/_.=-]+", r"\1 [REDACTED]", text)
    text = re.sub(
        r"(?im)([\w-]*(?:password|passwd|secret|token|api[_-]?key|authorization|cookie)"
        r"[\w-]*[\"']?\s*[:=]\s*)(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,;\n}]+)",
        r"\1[REDACTED]", text,
    )
    text = re.sub(r"(https?://)[^/\s@]+@", r"\1[REDACTED]@", text)
    return text


def sanitize(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) else sanitize(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return redact(value) if isinstance(value, str) else value


def remote_identity(remote):
    """Git HTTPS and SSH spellings share identity; credentials never survive."""
    if not remote:
        return ""
    remote = remote.strip()
    scp = re.fullmatch(r"(?:[^@/]+@)?([^/:]+):(.+)", remote) if "://" not in remote else None
    if scp:
        host, path = scp.groups()
    else:
        parsed = urlsplit(remote)
        if parsed.scheme not in {"https", "http", "ssh", "git"} or not parsed.hostname:
            return ""
        host, path = parsed.hostname, parsed.path
        if parsed.port and parsed.port not in {22, 80, 443}:
            host += f":{parsed.port}"
    path = path.strip("/").removesuffix(".git")
    if not path or any(c in path for c in "?#[]\n\r"):
        return ""
    return f"https://{host.lower()}/{path}"


def repository(project, directory, config):
    root = project.get("worktree") or directory
    mapping = next((r for r in config.get("repositories", []) if root in r.get("paths", [])), {})
    remote = mapping.get("remote", "")
    if not remote and Path(root).is_dir():
        result = subprocess.run(["git", "-C", root, "config", "--get", "remote.origin.url"],
                                capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            remote = result.stdout.strip()
    remote = remote_identity(remote)
    project_id = project["id"]
    # OpenCode's Git project ID is the root commit. Local/non-Git projects must
    # not collide across machines merely because OpenCode calls them 'global'.
    identity = remote or (f"git-root:{project_id}" if re.fullmatch(r"[a-f0-9]{40,64}", project_id)
                          else f"local:{config['device']}:{root}")
    return {
        "repository-id": digest(identity),
        "repository-name": redact(mapping.get("name") or project.get("name") or Path(root).name or "workspace"),
        "repository-remote": remote,
    }


def indented(value):
    # Code indentation preserves literal transcripts without interpreting their
    # wiki links, headings or forged block IDs as vault graph structure.
    return "\n".join("    " + line for line in str(value).splitlines()) + "\n"


def transcript(connection, session):
    lines, omitted = [], {}
    for message in connection.execute(
            "SELECT * FROM message WHERE session_id=? ORDER BY time_created,id", (session["id"],)):
        info = json.loads(message["data"])
        role = info.get("role")
        if role not in {"user", "assistant"}:
            continue
        mid = message["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", mid):
            raise ValueError("invalid message identity")
        lines.append(f"## {role.title()} {timestamp(message['time_created'])} ^{mid}\n")
        for part in connection.execute("SELECT * FROM part WHERE message_id=? ORDER BY time_created,id", (mid,)):
            data = json.loads(part["data"])
            kind = data.get("type", "unknown")
            if kind == "text":
                if data.get("synthetic"):
                    omitted["synthetic-text"] = omitted.get("synthetic-text", 0) + 1
                    continue
                lines.append(indented(redact(data.get("text", ""))))
            elif kind == "tool":
                pid = part["id"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", pid):
                    raise ValueError("invalid part identity")
                name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("tool", "tool")))
                state = data.get("state") or {}
                lines.append(f"### Tool {name} ^{pid}\n")
                public = {k: state[k] for k in ("status", "input", "output", "error") if k in state}
                if PRIVATE_PATH.search(json.dumps(public, ensure_ascii=False)):
                    lines.append(indented("[OMITTED: tool input/output references sensitive credential paths]"))
                else:
                    lines.append(indented(json.dumps(sanitize(public), ensure_ascii=False, indent=2)))
            else:
                omitted[kind] = omitted.get(kind, 0) + 1
    return "\n".join(lines), omitted


def write_atomic(vault, path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=vault,
                                         prefix=".session-capture-", delete=False) as handle:
            stage = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage, path)
    finally:
        if stage:
            stage.unlink(missing_ok=True)


def export_session(connection, session, args, config, seen):
    selected = args.session or config.get("include_sessions", [])
    if selected and session["id"] not in selected:
        return None
    if session.get("parent_id") and not config.get("include_children", False):
        return None
    directory = session["directory"]
    if any(Path(directory).is_relative_to(Path(p)) for p in config.get("exclude_directories", [])):
        return None
    key = digest(json.dumps([session["id"], session["project_id"], session["time_created"]]))
    latest_message = connection.execute("SELECT max(time_updated) FROM message WHERE session_id=?",
                                        (session["id"],)).fetchone()[0]
    latest_part = connection.execute(
        "SELECT max(part.time_updated) FROM part JOIN message ON part.message_id=message.id "
        "WHERE message.session_id=?", (session["id"],)).fetchone()[0]
    updated = timestamp(max(session["time_updated"], latest_message or 0, latest_part or 0))
    if seen.get(key, "") >= updated:
        return None
    project_row = connection.execute("SELECT * FROM project WHERE id=?", (session["project_id"],)).fetchone()
    if project_row is None:
        raise ValueError("session project missing")
    body, omitted = transcript(connection, session)
    if not body.strip():
        return None
    meta = {"type": "opencode-transcript", "schema": VERSION,
            "session-key": key, "session-id": session["id"],
            "parent-session-id": session.get("parent_id"), "device": args.device,
            "title": redact(session["title"]), "created": timestamp(session["time_created"]),
            "updated": updated, **repository(dict(project_row), directory, config),
            "checkout": directory,
            "projects": config.get("session_projects", {}).get(session["id"], []),
            "omitted-parts": omitted, "redaction": "best-effort-v1", "revision": digest(body)}
    text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=10**6) + "---\n" + body
    path = args.vault / "Sessions/OpenCode/Transcripts" / args.device / f"{key}.md"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        pieces = old.split("---\n", 2)
        old_meta = yaml.safe_load(pieces[1]) if len(pieces) == 3 else None
        if not isinstance(old_meta, dict):
            raise ValueError("existing transcript metadata corrupt; left untouched")
        if old_meta.get("updated", "") > updated:
            seen[key] = old_meta["updated"]
            return None
        if old == text:
            seen[key] = updated
            return None
    if not args.dry_run:
        write_atomic(args.vault, path, text)
    seen[key] = updated
    return key


def capture(args):
    config = json.loads(args.config.read_text())
    config["device"] = args.device
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.device):
        raise ValueError("device must be a filesystem-safe roster name")
    if not args.vault.is_dir():
        raise ValueError("vault does not exist; establish Obsidian Sync first")
    args.state.mkdir(parents=True, exist_ok=True)
    exported, failures, seen = set(), 0, {}
    with (args.state / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for filename in config.get("databases", ["opencode.db"]):
            if Path(filename).name != filename or not filename.endswith(".db"):
                raise ValueError("database must be a basename ending in .db")
            database = args.data / filename
            if not database.is_file():
                continue
            connection = None
            try:
                connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
                connection.row_factory = sqlite3.Row
                with connection:
                    connection.execute("BEGIN")
                    sessions = list(connection.execute("SELECT * FROM session ORDER BY time_updated DESC,id"))
                    for row in sessions:
                        try:
                            key = export_session(connection, dict(row), args, config, seen)
                            if key:
                                exported.add(key)
                        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error,
                                yaml.YAMLError, subprocess.SubprocessError):
                            failures += 1
                            print("Session capture: session skipped; source contents not logged")
            except (OSError, ValueError, sqlite3.Error, yaml.YAMLError, subprocess.SubprocessError):
                failures += 1
                print(f"Session capture: {filename} failed; retry next run (contents not logged)")
            finally:
                if connection is not None:
                    connection.close()
    print(f"Session capture: {len(exported)} {'would export' if args.dry_run else 'exported'}, {failures} failures")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path.home() / ".local/share/opencode")
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/state/opencode-session-capture")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_suffix(".json"))
    parser.add_argument("--device", required=True)
    parser.add_argument("--session", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        raise SystemExit(bool(capture(args)))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"Session capture: {type(exc).__name__}; check configuration (contents not logged)\n")


if __name__ == "__main__":
    main()
