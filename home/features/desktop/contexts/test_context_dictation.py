import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import context_dictation as dictation
import context_notes as api
import notebook
import test_context_notes


class DictationTests(unittest.TestCase):
    def setUp(self):
        self.desktop_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        test_context_notes.ContextNotesTests.setUp(self)

    def capture(self, body="My dictated thought."):
        with patch.object(dictation.subprocess, "Popen", side_effect=OSError("offline")):
            return dictation.capture(self.vault, {"body": body})

    def response(self, title="Recognizable thought"):
        return patch.object(dictation, "urlopen", return_value=io.BytesIO(
            json.dumps({"message": {"content": json.dumps({"title": title})}}).encode()))

    def test_capture_uses_frozen_owner_and_preserves_body(self):
        body = "---\nAn ordinary Markdown rule.\nUser's exact words.\n"
        with patch.object(api.ctl, "launch_context", return_value=self.second):
            card = self.capture(body)
        self.assertEqual(card["status"], "Thoughts")
        self.assertEqual(self.vault.path(card["path"]).parent, self.vault.directory)
        self.assertTrue(card["content"].endswith(body))
        self.assertEqual(api.resolve(self.second["id"]).listing({})["total"], 0)
        _, metadata, _ = notebook.fields(card["content"])
        self.assertEqual(metadata["created-source"], "desktop-dictation")

    def test_naming_preserves_every_byte_and_collision(self):
        card = self.capture()
        with self.response():
            result = dictation.title_capture(self.vault, card | {"body": "My dictated thought."})
        self.assertEqual(result["path"], "Recognizable thought.md")
        self.assertEqual(self.vault.card(result["path"])["content"], card["content"])
        other = self.capture()
        with self.response():
            self.assertIsNone(dictation.title_capture(self.vault, other | {"body": "other"}))
        self.assertTrue(self.vault.path(other["path"]).exists())

    def test_manual_edit_or_rename_wins(self):
        for rename in (False, True):
            card = self.capture()
            path = self.vault.path(card["path"])
            if rename:
                path.rename(path.with_name("Manual name.md"))
            else:
                path.write_text(card["content"] + "Manual edit.\n")
            with self.response():
                self.assertIsNone(dictation.title_capture(self.vault, card | {"body": "thought"}))
        self.assertFalse(self.vault.path("Recognizable thought.md").exists())

    def test_empty_capture_writes_nothing(self):
        self.assertIsNone(self.capture(" \n"))
        self.assertEqual(self.vault.listing({})["total"], 0)

    def test_native_qml_writer(self):
        if not self.desktop_runtime or not os.environ.get("WAYLAND_DISPLAY"):
            self.skipTest("Native PanelWindow requires a running Wayland desktop")
        body = "Native dictation capture acceptance.\n" + (
            "Every letter: office, fully, faster. Quotes: ‘hello’ — café, 日本語, 🎙️.\n" * 100
        ).strip()
        desktop_env = {**os.environ, "XDG_RUNTIME_DIR": self.desktop_runtime}
        clipboard = subprocess.run(["wl-paste", "--no-newline"], env=desktop_env, capture_output=True)
        try:
            result = subprocess.run(
                ["qs", "-p", str(Path(__file__).parent.parent / "quickshell/test_capture.qml"), "--no-color"],
                env={**os.environ, "QT_QPA_PLATFORM": "wayland", "HYPRLAND_INSTANCE_SIGNATURE": "",
                     "XDG_RUNTIME_DIR": self.desktop_runtime,
                     "TEST_CAPTURE_CONTEXT": self.first["id"], "TEST_CAPTURE_BODY": body,
                     "CONTEXT_DICTATION_OLLAMA": "http://127.0.0.1:1/api/chat"},
                capture_output=True, text=True, timeout=15,
            )
        finally:
            if clipboard.returncode == 0:
                subprocess.run(["wl-copy"], env=desktop_env, input=clipboard.stdout, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["wl-copy", "--clear"], env=desktop_env, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("FAILED:", output)
        self.assertIn("PASS: native dictation writer", output)
        cards = self.vault.cards()
        self.assertEqual(len(cards), 1)
        content = cards[0]["content"]
        frontmatter, _, _ = notebook.fields(content)
        self.assertEqual(content[frontmatter.end():], body)

    def test_owner_ignores_inherited_context_and_has_no_fallback(self):
        output = io.StringIO()
        with patch.object(api.ctl, "launch_context", return_value=None), patch("sys.stdout", output):
            self.assertEqual(api.main(["--context", self.first["id"], "capture-owner"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"context_id": ""})
