import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("viewed", Path(__file__).parent / "plugins/opencode-viewed.py")
viewed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewed)


class ViewedTest(unittest.TestCase):
    def test_selected_pane_requires_active_context(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(viewed.os.environ, {
                "XDG_RUNTIME_DIR": directory, "HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            catalog = Path(directory) / "desktop-contexts-test.json"
            catalog.write_text(json.dumps({"active_context": "foreground"}))
            for attached, window, pane, session, expected in [
                ("1", "1", "1", "context-background", False),
                ("1", "1", "1", "context-foreground", True),
                ("1", "0", "1", "context-foreground", False),
                ("1", "1", "0", "context-foreground", False),
                ("0", "1", "1", "context-foreground", False),
            ]:
                with self.subTest(session=session, window=window, pane=pane, attached=attached), \
                        patch.object(viewed.subprocess, "check_output", return_value="\t".join([attached, window, pane, session])):
                    self.assertEqual(viewed.viewed("%7"), expected)

    def test_background_clear_does_not_acknowledge(self):
        with patch.object(viewed.sys, "argv", ["helper", "%7", "--clear"]), \
                patch.object(viewed, "viewed", return_value=False), \
                patch.object(viewed.subprocess, "run") as run:
            self.assertEqual(viewed.main(), 0)
            run.assert_not_called()

    def test_background_query_remains_false(self):
        with patch.object(viewed.sys, "argv", ["helper", "%7"]), \
                patch.object(viewed, "viewed", return_value=False):
            self.assertEqual(viewed.main(), 1)

    def test_unknown_visibility_preserves_unread_without_hook_failure(self):
        for error in (FileNotFoundError(), KeyError("HYPRLAND_INSTANCE_SIGNATURE"),
                      ValueError("invalid catalog"), viewed.subprocess.TimeoutExpired("tmux", 1)):
            for clear in (False, True):
                with self.subTest(error=type(error).__name__, clear=clear), \
                        patch.object(viewed.sys, "argv", ["helper", "%7"] + (["--clear"] if clear else [])), \
                        patch.object(viewed, "viewed", side_effect=error), \
                        patch.object(viewed.subprocess, "run") as run:
                    self.assertEqual(viewed.main(), 0 if clear else 1)
                    run.assert_not_called()

    def test_clear_failure_still_reports_error(self):
        with patch.object(viewed.sys, "argv", ["helper", "%7", "--clear"]), \
                patch.object(viewed, "viewed", return_value=True), \
                patch.object(viewed.subprocess, "run", side_effect=viewed.subprocess.CalledProcessError(1, "tmux")):
            self.assertEqual(viewed.main(), 1)

    def test_foreground_clear_targets_only_completion(self):
        with patch.object(viewed.sys, "argv", ["helper", "%7", "--clear"]), \
                patch.object(viewed, "viewed", return_value=True), \
                patch.object(viewed.subprocess, "run") as run:
            self.assertEqual(viewed.main(), 0)
            command = run.call_args.args[0]
            self.assertIn('set-option -p -t %7 @opencode_icon ""', command)
            self.assertEqual(command[5], "#{==:#{@opencode_icon},!}")
            self.assertNotIn("X", command[5])


if __name__ == "__main__":
    unittest.main()
