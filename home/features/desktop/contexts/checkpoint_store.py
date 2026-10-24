"""Single-root immutable chunk storage. Unknown incoming objects are never swept.

Tree is an in-memory artifact filesystem shared by capture and lazy validated
readers. Publication callers serialize locally and compare the root read before
capture; application RPC must never run inside that publication lock.
"""

import fnmatch
import hashlib
import io
import json
import os
import shutil
from pathlib import Path, PurePosixPath

CHUNK = 65536
GEAR = [int(hashlib.sha256(bytes([n])).hexdigest()[:8], 16) for n in range(256)]


def chunks(data):
    """Bounded content-defined pieces retain suffixes across insertions/deletions."""
    start, line_start, rolling = 0, 0, 0
    for index, byte in enumerate(data, 1):
        rolling = ((rolling << 1) + GEAR[byte]) & 0xFFFFFFFF
        size = index - start
        line_anchor = byte == 10 and int(hashlib.sha256(data[line_start:index]).hexdigest()[:4], 16) % 16 == 0
        if byte == 10:
            line_start = index
        if size >= CHUNK or (size >= 8192 and (rolling & 0x3FFF == 0 or line_anchor)):
            yield data[start:index]
            start, rolling = index, 0
    if start < len(data) or not data:
        yield data[start:]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def object_key(key):
    if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("Invalid object hash")
    return key


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data):
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in reversed(missing):
        fsync_dir(directory.parent)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fsync_dir(path.parent)


def relative(name):
    value = PurePosixPath(name)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"Artifact escapes checkpoint: {name}")
    return str(value) if str(value) != "." else ""


class Tree:
    def __init__(self, files=None, loader=None):
        self.files = dict(files or {})
        self.loader = loader

    def path(self, name=""):
        return MemoryPath(self, relative(name))

    def read(self, name):
        if name not in self.files:
            raise FileNotFoundError(name)
        if self.files[name] is None:
            self.files[name] = self.loader(name)
        return self.files[name]

    def copy_from(self, source, prefix="", absent_only=False):
        for path in source.rglob("*"):
            if path.is_file():
                name = str(path.relative_to(source))
                target = relative(str(PurePosixPath(prefix) / name))
                if not absent_only or target not in self.files:
                    self.files[target] = path.read_bytes()


class MemoryPath:
    """Small Path-shaped artifact API, deliberately without an OS path coercion."""
    def __init__(self, tree, name):
        self.tree, self.key = tree, name

    def __truediv__(self, name):
        return self.tree.path(str(PurePosixPath(self.key) / name))

    def __str__(self):
        return self.key

    @property
    def name(self):
        return PurePosixPath(self.key).name

    @property
    def parent(self):
        return self.tree.path(str(PurePosixPath(self.key).parent))

    def relative_to(self, other):
        return PurePosixPath(self.key).relative_to(other.key)

    def read_bytes(self):
        return self.tree.read(self.key)

    def read_text(self):
        return self.read_bytes().decode()

    def open(self, mode="r"):
        return io.BytesIO(self.read_bytes()) if "b" in mode else io.StringIO(self.read_text())

    def write_bytes(self, data):
        self.tree.files[self.key] = bytes(data)

    def write_text(self, data):
        self.write_bytes(data.encode())

    def is_file(self):
        return self.key in self.tree.files

    def exists(self):
        return bool(self.tree.files) if not self.key else self.is_file() or any(n.startswith(self.key + "/") for n in self.tree.files)

    def mkdir(self, **_kwargs):
        pass

    def iterdir(self):
        prefix = self.key + "/" if self.key else ""
        names = {n[len(prefix):].split("/", 1)[0] for n in self.tree.files if n.startswith(prefix)}
        return iter(self / n for n in sorted(names))

    def glob(self, pattern):
        return (p for p in self.iterdir() if fnmatch.fnmatch(p.name, pattern))

    def rglob(self, pattern):
        prefix = self.key + "/" if self.key else ""
        return (self.tree.path(n) for n in sorted(self.tree.files)
                if n.startswith(prefix) and fnmatch.fnmatch(n.rsplit("/", 1)[-1], pattern))


def references(manifest):
    return {chunk for info in manifest.get("artifacts", {}).values() for chunk in info["chunks"]}


class Store:
    def __init__(self, directory, local):
        self.directory, self.local = Path(directory), Path(local)

    def object(self, key):
        object_key(key)
        path = self.directory / "objects" / key
        if path.is_symlink() or not path.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError("Object escapes checkpoint")
        return path

    def cache(self, key):
        self.object(key)  # Validate hash syntax before using it in local paths.
        return self.local / "objects" / key

    def load(self):
        if list(self.directory.glob("current.sync-conflict*.json")):
            raise ValueError("Divergent Syncthing current manifests; resolve explicit conflict before saving")
        if list((self.directory / "conflicts").glob("*.json")):
            raise ValueError("Divergent checkpoint preserved in conflicts; resolve before loading/saving")
        path = self.directory / "current.json"
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_bytes())
            manifest = envelope["manifest"]
            if sha(canonical(manifest)) != envelope["sha256"]:
                raise ValueError("hash mismatch")
            if manifest["version"] != 2:
                raise ValueError("identity/schema mismatch")
            if (not isinstance(manifest["artifacts"], dict) or not isinstance(manifest["clock"], dict)
                    or not isinstance(manifest["id"], str) or not isinstance(manifest["device"], str)):
                raise TypeError("identity/schema mismatch")
            for name, info in manifest["artifacts"].items():
                if not name or relative(name) != name or not isinstance(info["size"], int) or info["size"] < 0:
                    raise ValueError("Invalid artifact index")
                object_key(info["sha256"])
                if not isinstance(info["chunks"], list) or not info["chunks"]:
                    raise ValueError("Invalid artifact chunks")
                for key in info["chunks"]:
                    object_key(key)
            return manifest
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Latest checkpoint manifest missing/corrupt; no older fallback: {exc}") from exc

    def view(self, manifest):
        def load(name):
            info = manifest["artifacts"][name]
            try:
                pieces = []
                for key in info["chunks"]:
                    data = self.object(key).read_bytes()
                    if sha(data) != key:
                        raise ValueError("hash mismatch")
                    pieces.append(data)
                data = b"".join(pieces)
                if len(data) != info["size"] or sha(data) != info["sha256"]:
                    raise ValueError("artifact mismatch")
                return data
            except (OSError, ValueError) as exc:
                raise ValueError(f"Latest checkpoint artifact missing/corrupt: {name}; wait for sync") from exc
        return Tree(dict.fromkeys(manifest["artifacts"]), load).path()

    def validate(self, manifest):
        view = self.view(manifest)
        for name in manifest["artifacts"]:
            (view / name).read_bytes()

    def _recover(self, current):
        journal = self.local / "pending.json"
        if not journal.exists():
            journal.with_name("pending.json.pending").unlink(missing_ok=True)
            return
        transaction = json.loads(journal.read_bytes())
        witness = self.local / "witness.json"
        # A crash after root publication but before the local witness must finish
        # that transaction before reclaiming the witness's bytes.
        if (current and transaction.get("target") == current["id"]
                and (not witness.exists() or json.loads(witness.read_bytes()) != current)):
            atomic(witness, canonical(current))
        keep = references(current) if current else set()
        for conflict in (self.directory / "conflicts").glob("*.json"):
            keep |= references(json.loads(conflict.read_bytes()))
        # Only known objects from this local transaction may be removed. In
        # particular, an incoming object with no local ownership is never GC'd.
        for key in set(transaction["created"] + transaction["retired"]) - keep:
            self.object(key).unlink(missing_ok=True)
        for key in set(transaction.get("created_local", []) + transaction["retired"]) - keep:
            self.cache(key).unlink(missing_ok=True)
        for key in transaction["created"]:
            self.object(key).with_name(key + ".pending").unlink(missing_ok=True)
        for key in transaction.get("created_local", []):
            self.cache(key).with_name(key + ".pending").unlink(missing_ok=True)
        (self.directory / "current.json.pending").unlink(missing_ok=True)
        witness.with_name("witness.json.pending").unlink(missing_ok=True)
        journal.with_name("pending.json.pending").unlink(missing_ok=True)
        for directory in (self.directory / "objects", self.local / "objects"):
            if directory.is_dir():
                fsync_dir(directory)
        journal.unlink()
        fsync_dir(self.local)

    def publish(self, tree, metadata, expected):
        current = self.load()
        if current != expected:
            raise ValueError("Checkpoint changed during capture; retry (no stale publication)")
        witness_path = self.local / "witness.json"
        witness = json.loads(witness_path.read_bytes()) if witness_path.exists() else None
        journal = self.local / "pending.json"
        if journal.exists():
            transaction = json.loads(journal.read_bytes())
            candidate = transaction.get("manifest")
            if (candidate and (current or {}).get("id") not in (transaction.get("base"), candidate["id"])
                    and any((current or {}).get("clock", {}).get(k, 0) < n for k, n in candidate["clock"].items())):
                # Root replacement may race a crash between synced publication
                # and local acknowledgement. The one pending index retains that
                # branch; never discard it merely because the old witness lost.
                witness = candidate
        if witness and (not current or any(current.get("clock", {}).get(k, 0) < n
                                           for k, n in witness.get("clock", {}).items())):
            # The previous local root was replaced by a concurrent/older synced
            # root. Preserve it explicitly and stop; never merge or choose older.
            # The bounded machine-local mirror protects the locally committed
            # branch against synced deletions before divergence was noticed.
            for key in references(witness):
                try:
                    data = self.cache(key).read_bytes()
                except FileNotFoundError as exc:
                    raise ValueError("Divergent interrupted checkpoint incomplete; pending transaction retained") from exc
                if sha(data) != key:
                    raise ValueError("Divergent local recovery object missing/corrupt")
                target = self.object(key)
                if not target.is_file() or sha(target.read_bytes()) != key:
                    atomic(target, data)
            atomic(self.directory / "conflicts" / (witness["id"] + ".json"), canonical(witness))
            raise ValueError("Divergent checkpoint preserved in conflicts; resolve before saving")
        if list((self.directory / "conflicts").glob("*.json")):
            raise ValueError("Divergent checkpoint preserved in conflicts; resolve before saving")
        if current:
            self.validate(current)
        self._recover(current)
        objects, artifacts = {}, {}
        for name in sorted(tree.files):
            data = tree.read(name)
            fingerprint = sha(data)
            old_info = (current or {}).get("artifacts", {}).get(name)
            if old_info and old_info["sha256"] == fingerprint and old_info["size"] == len(data):
                artifacts[name] = old_info
                continue
            pieces = list(chunks(data))
            keys = [sha(chunk) for chunk in pieces]
            objects.update(zip(keys, pieces))
            artifacts[relative(name)] = {"size": len(data), "sha256": fingerprint, "chunks": keys}
        if current and artifacts == current["artifacts"] and metadata.get("warnings", []) == current.get("warnings", []):
            return current, False
        for key in references({"artifacts": artifacts}) - objects.keys():
            objects[key] = self.object(key).read_bytes()
        clock = dict((current or {}).get("clock", {}))
        clock[metadata["device"]] = clock.get(metadata["device"], 0) + 1
        manifest = dict(metadata, version=2, artifacts=artifacts, clock=clock,
                        parent=(current or {}).get("id"))
        manifest["id"] = sha(canonical(manifest))
        created = [key for key in objects if not self.object(key).exists()]
        created_local = [key for key in objects if not self.cache(key).exists()]
        retired = sorted((references(current or {}) | references(witness or {})) - set(objects))
        atomic(self.local / "pending.json", canonical({"target": manifest["id"], "created": created,
                                                       "created_local": created_local, "retired": retired,
                                                       "base": (current or {}).get("id"), "manifest": manifest}))
        for key, content in objects.items():
            path = self.object(key)
            if key in created:
                atomic(path, content)
            elif sha(path.read_bytes()) != key:
                raise ValueError(f"Corrupt immutable object: {key}")
            if key in created_local:
                atomic(self.cache(key), content)
            elif sha(self.cache(key).read_bytes()) != key:
                raise ValueError(f"Corrupt machine-local recovery object: {key}")
        self.validate(manifest)
        if self.load() != current:
            raise ValueError("Checkpoint changed during publication; pending capture retained; retry")
        # All chunks and object directory entries are durable before the root.
        atomic(self.directory / "current.json", canonical({"manifest": manifest, "sha256": sha(canonical(manifest))}))
        atomic(witness_path, canonical(manifest))
        self._recover(manifest)
        return manifest, True

    def materialize(self, view, destination):
        """Restore-only local cache; never used to detect a no-op capture."""
        destination = Path(destination)
        sources = list(view.rglob("*"))
        names = {str(source.relative_to(view)) for source in sources}
        for source in sources:
            target = destination / str(source.relative_to(view))
            data = source.read_bytes()
            if not target.is_file() or target.read_bytes() != data:
                atomic(target, data)
        for path in destination.rglob("*"):
            if path.is_file() and str(path.relative_to(destination)) not in names:
                path.unlink()
        return destination

    def remove_v1(self):
        # Called only after a complete new root has been validated. Conflicts and
        # unknown sync data outside these obsolete v1 namespaces stay intact.
        current = self.load()
        if not current:
            return
        self.validate(current)
        selected = current.get("migrated_from")
        ancestors = set()
        if (self.directory / "heads").exists():
            if not selected:
                raise ValueError("v1 heads arrived after v2 publication; explicit migration/conflict review required")
            while selected and selected not in ancestors:
                ancestors.add(selected)
                path = self.directory / relative(selected) / "manifest.json"
                if not path.is_file():
                    break
                selected = json.loads(path.read_bytes()).get("parent")
            for head_path in (self.directory / "heads").glob("*.json"):
                head = json.loads(head_path.read_bytes())
                generation = relative(head["generation"])
                if generation not in ancestors:
                    source = self.directory / generation
                    if source.is_symlink() or not source.resolve().is_relative_to(self.directory.resolve()):
                        raise ValueError("Legacy generation escapes checkpoint")
                    target = self.directory / "legacy-conflicts" / Path(generation).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.exists() and not target.exists():
                        os.replace(source, target)
                    atomic(target.parent / (head_path.stem + ".head.json"), canonical(head))
            shutil.rmtree(self.directory / "heads")
        generations = self.directory / "generations"
        for candidate in generations.glob("*"):
            identity = "generations/" + candidate.name
            manifest_path = candidate / "manifest.json"
            try:
                metadata = json.loads(manifest_path.read_bytes()) if manifest_path.is_file() else {}
            except (OSError, ValueError):
                metadata = {}  # Incomplete unknown incoming data is not ours to GC.
            owned = metadata.get("device") == current["device"] or f"-{current['device']}-" in candidate.name
            if identity in ancestors or owned:
                shutil.rmtree(candidate)
            # Other unreferenced generations may be incoming before their head.
            # Do not destroy them merely because migration saw an older head.
        if generations.is_dir() and not any(generations.iterdir()):
            generations.rmdir()
