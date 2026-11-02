import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("desktop_files", Path(__file__).with_name("desktop-files.py"))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class DesktopFilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_visible_entries_mime_links_and_literal_urls(self):
        (self.root / ".context").mkdir()
        (self.root / ".hidden").touch()
        (self.root / "Folder").mkdir()
        (self.root / "notes #1%.txt").write_text("hello")
        (self.root / "document.pdf").touch()
        (self.root / "broken").symlink_to(self.root / "missing")
        entries = {item["name"]: item for item in desktop.entries(self.root)}
        self.assertEqual(set(entries), {"Folder", "notes #1%.txt", "document.pdf", "broken"})
        self.assertEqual(entries["Folder"]["icon"], "folder")
        self.assertEqual(entries["document.pdf"]["icon"], "application-pdf")
        self.assertEqual(entries["notes #1%.txt"]["icon"], "text-plain")
        self.assertIn("notes%20%231%25.txt", entries["notes #1%.txt"]["url"])

    def test_new_folder_never_replaces_existing_file_or_link(self):
        (self.root / "untitled folder").write_text("keep")
        (self.root / "untitled folder 2").symlink_to(self.root / "missing")
        self.assertEqual(desktop.new_folder(self.root), "untitled folder 3")
        self.assertEqual((self.root / "untitled folder").read_text(), "keep")
        self.assertEqual(desktop.new_folder(self.root), "untitled folder 4")

    def test_shortcut_label_and_explicit_launch(self):
        shortcut = self.root / "test.desktop"
        shortcut.write_text("[Desktop Entry]\nType=Application\nName=My App\nIcon=kitty\nExec=kitty\n")
        entry = desktop.entries(self.root)[0]
        self.assertEqual(entry["name"], "test.desktop")
        self.assertEqual(entry["displayName"], "My App")
        with patch("sys.argv", ["desktop-files", "open", str(self.root), shortcut.name]), patch.object(desktop.subprocess, "run") as run:
            desktop.main()
        run.assert_called_once_with(["gio", "launch", str(shortcut)], check=True)

    def test_mutations_stay_at_root_and_trash_link_not_target(self):
        for name in ("", ".context", "..", "../other", "folder/file", "/tmp/elsewhere", "bad\x00name"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                desktop.child(self.root, name)
        target = self.root / ".hidden"
        link = self.root / "link"
        link.symlink_to(target)
        self.assertEqual(desktop.child(self.root, "link"), link)

    def test_trash_passes_names_as_arguments(self):
        name = "--literal; $(touch bad)"
        with patch("sys.argv", ["desktop-files", "trash", str(self.root), "--", name]), patch.object(desktop.subprocess, "run") as run:
            desktop.main()
        run.assert_called_once_with(["gio", "trash", "--", str(self.root / name)], check=True)

    def test_dash_prefixed_names_remain_operands(self):
        with patch("sys.argv", ["desktop-files", "open", str(self.root), "--", "--help"]), patch.object(desktop.subprocess, "run") as run:
            desktop.main()
        run.assert_called_once_with(["gio", "open", (self.root / "--help").as_uri()], check=True)

    @unittest.skipUnless(shutil.which("quickshell") and shutil.which("context-desktop-files"), "Requires deployed desktop helper and Quickshell")
    def test_live_qml_model_context_switches_and_mutation(self):
        first, second = self.root / "first", self.root / "second"
        first.mkdir()
        second.mkdir()
        (first / "first.txt").touch()
        (first / ".context").mkdir()
        environment = dict(os.environ, TEST_DESKTOP_FIRST=str(first), TEST_DESKTOP_SECOND=str(second))
        result = subprocess.run(["quickshell", "-p", str(Path(__file__).with_name("test_desktop_model.qml"))],
                                capture_output=True, text=True, env=environment, timeout=15)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("PASS: desktop model", output)
        self.assertNotIn("FAILED:", output)
        self.assertTrue((second / "untitled folder").is_dir())
        self.assertFalse((first / "untitled folder").exists())


if __name__ == "__main__":
    unittest.main()
