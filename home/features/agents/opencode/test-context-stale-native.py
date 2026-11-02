"""Validate owned native patch against exact pinned upstream in an isolated tree.

Run OPENCODE_STALE_VERIFY_NATIVE=1 python3 test-context-stale-native.py. Fetches
only public source files, never launches user's OpenCode or mutates its database.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.request

ROOT = Path(__file__).parent
REVISION = "e3c4eb242585dcd77be1a867391b7c25fd47ce52"


@unittest.skipUnless(os.environ.get("OPENCODE_STALE_VERIFY_NATIVE"), "opt-in pinned upstream source check")
class NativePatch(unittest.TestCase):
    def test_patch_applies_and_blocks_native_entry_points(self):
        with tempfile.TemporaryDirectory(prefix="oc6-native-") as directory:
            tree = Path(directory)
            paths = ["packages/tui/src/" + path for path in [
                "app.tsx", "context/route.tsx", "ui/dialog.tsx", "component/prompt/index.tsx"]]
            source = Path(os.environ.get("OPENCODE_STALE_SOURCE", "/nix/store/j4c7rw0ph5k9ma0shhp5bx7z0dkvpgya-source"))
            for name in paths:
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if (source / name).is_file():
                    shutil.copyfile(source / name, path)
                else:
                    with urllib.request.urlopen(f"https://raw.githubusercontent.com/anomalyco/opencode/{REVISION}/{name}", timeout=30) as response:
                        path.write_bytes(response.read())
            result = subprocess.run(["git", "apply", "--check", "--unidiff-zero", str(ROOT / "context-stale.patch")],
                                    cwd=tree, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(["patch", "--dry-run", "--fuzz=0", "-p1", "-i", str(ROOT / "context-stale.patch")],
                                    cwd=tree, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            subprocess.run(["git", "apply", "--unidiff-zero", str(ROOT / "context-stale.patch")], cwd=tree, check=True)
            route = (tree / paths[1]).read_text()
            self.assertIn("if (!desktopStale.allowRoute(route)) return", route)
            prompt = (tree / paths[3]).read_text()
            self.assertLess(prompt.index("await desktopStale.beforeSubmit()"), prompt.index("sdk.client.session.shell"))
            self.assertEqual(prompt.count(".catch(rejected)"), 2)
            self.assertIn("rejected(error)", prompt)
            self.assertIn("desktopStale.bindPrompt", prompt)
            self.assertIn('if (store.mode === "shell") {\n      const rejected = desktopStale.submission(sessionID)', prompt)
            self.assertIn('} else {\n      move.startSubmit()\n      const rejected = desktopStale.submission(sessionID)', prompt)
            self.assertIn("!desktopStale.blocked() && value.stack.length", (tree / paths[2]).read_text())
            self.assertIn("<DesktopStaleOverlay />", (tree / paths[0]).read_text())
            bun = os.environ.get("BUN") or shutil.which("bun")
            if bun:
                result = subprocess.run([bun, "-e", 'const t=new Bun.Transpiler({loader:"tsx"}); for(const p of process.argv.slice(1)) t.transformSync(await Bun.file(p).text());',
                                         *[str(tree / path) for path in paths]], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
