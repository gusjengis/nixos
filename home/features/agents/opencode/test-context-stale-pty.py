"""OC6 native PTY acceptance against an integrated binary (opt-in).

OPENCODE_ACCEPTANCE_NATIVE=1 OPENCODE_ACCEPTANCE_BINARY=/nix/store/...-opencode/bin/opencode \
  python3 -B home/features/agents/opencode/test-context-stale-pty.py

Uses OC1's isolated fixture (private HOME/XDG/database, loopback provider) read-only.
Two isolated profiles stand in for devices; this is not a physical two-device test.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import unittest
import uuid
from contextlib import closing

CONTEXTS = Path(__file__).resolve().parents[2] / "desktop/contexts"
sys.path.insert(0, str(CONTEXTS))
from opencode_acceptance_fixture import NativeFixture  # noqa: E402


def settle(fixture, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        fixture.pump()


@unittest.skipUnless(os.environ.get("OPENCODE_ACCEPTANCE_NATIVE") == "1", "set OPENCODE_ACCEPTANCE_NATIVE=1")
class StaleOverlayPty(unittest.TestCase):
    def test_overlay_survives_dismissal_keys_and_restart_then_opens_latest_with_saved_draft(self):
        from test_chat_portability import native_fixture
        binary = os.environ["OPENCODE_ACCEPTANCE_BINARY"]
        source = NativeFixture(binary, blocked=False)
        self.addCleanup(source.close)
        destination = NativeFixture(binary, blocked=False, tui_plugins=("context-stale.tsx",))
        self.addCleanup(destination.close)
        root = source.base / "work"
        (root / "external.txt").write_text("fixture attachment")
        (root / "result.txt").write_text("fixture result")
        chat = native_fixture(root)
        origin = "ses_oc6stale0"
        chat = json.loads(json.dumps(chat).replace(chat["info"]["id"], origin))
        chat["info"]["title"] = "OC6 portable"
        chat["info"]["metadata"] = {"desktop_context": {"id": source.context["id"], "chat": origin, "session": origin}}
        (source.base / "seed.json").write_text(json.dumps(chat))
        self.assertEqual(source.native("import", str(source.base / "seed.json")).returncode, 0)
        self.assertEqual(source.cli("sync", timeout=90).returncode, 0)
        destination.mirror_from(source)
        owner = source.context["id"]
        result = destination.cli("ensure", "--owner", owner, "--chat", origin, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        old = json.loads(result.stdout)["session_id"]
        destination.start(["--session", old])
        destination.wait(lambda: (destination.tui().get("session") or {}).get("id") == old
                         and "OC6 portable" in destination.screen.text, "received copy open", 40)
        draft = "OC6_DRAFT_" + uuid.uuid4().hex[:10]
        destination.write(draft)
        destination.wait(lambda: draft in destination.screen.text, "draft typed")

        with closing(sqlite3.connect(source.env["OPENCODE_DB"])) as db, db:
            db.execute("UPDATE session SET title=?, time_updated=time_updated+1000 WHERE id=?", ("OC6 edited on A", origin))
        self.assertEqual(source.cli("sync", timeout=90).returncode, 0)
        destination.mirror_from(source)
        destination.wait(lambda: "Newer conversation" in destination.screen.text, "blocking overlay", 15)

        # Dismissal / bypass attempts: Escape, Ctrl+C, palette, session list, typing + Enter-less text.
        for keys in ("\x1b", "\x03", "\x03", "\x10", "\x18l", "zzz"):
            destination.write(keys)
            settle(destination, .4)
            self.assertIsNone(destination.child.poll(), f"{keys!r} exited OpenCode")
            self.assertIn("Newer conversation", destination.screen.text, f"{keys!r} dismissed overlay")
            self.assertEqual(destination.tui()["session"]["id"], old, "silent route switch")
        self.assertFalse(destination.provider.requests, "stale content dispatched")

        # Close OpenCode while blocked; the saved draft must survive restart.
        recovery = Path(destination.env["XDG_STATE_HOME"]) / "opencode-context/stale-recovery"
        destination.wait(lambda: recovery.is_dir() and any(draft in p.read_text() for p in recovery.glob("*.json")),
                         "durable private draft record", 5)
        destination.reset()
        destination.start(["--session", old])
        destination.wait(lambda: "Newer conversation" in destination.screen.text, "overlay after restart", 40)
        settle(destination, .5)
        destination.write("\r")
        destination.wait(lambda: (destination.tui().get("session") or {}).get("id") not in (None, old)
                         and "Newer conversation" not in destination.screen.text, "opened latest verified copy", 90)
        destination.wait(lambda: draft in destination.screen.text, "saved draft restored on latest after restart", 10)
        self.assertIn("OC6 edited on A", json.dumps(destination.tui()["session"]))
        self.assertFalse(destination.provider.requests, "draft auto-submitted")
        with closing(sqlite3.connect(destination.env["OPENCODE_DB"])) as db:
            self.assertIn((old,), db.execute("SELECT id FROM session").fetchall(), "superseded history removed")
        exports = [json.loads(p.read_text()) for p in recovery.glob("*.json")]
        self.assertTrue(any(item["reason"] == "preserved-history" and
                            item["draft"]["histories"][0]["info"]["id"] == old for item in exports))
        for path in recovery.glob("*.json"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
