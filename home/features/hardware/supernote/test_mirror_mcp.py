import base64
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("mirror_mcp", Path(__file__).with_name("mirror-mcp.py"))
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


class FakeStream(io.BytesIO):
    headers = {"Content-Type": "multipart/x-mixed-replace; boundary=test"}

class MirrorTest(unittest.TestCase):
    def test_capture_detects_png_despite_mislabeled_multipart(self):
        png = b"\x89PNG\r\n\x1a\nimage"
        stream = FakeStream(b"Content-Type: image/jpeg\r\nContent-Length: 13\r\n\r\n" + png)
        with patch.object(mirror.urllib.request, "urlopen", return_value=stream):
            self.assertEqual(mirror.capture_frame(), (png, "image/png"))

    def test_tool_stays_available_when_mirror_is_down(self):
        with patch.object(mirror.urllib.request, "urlopen", side_effect=OSError("offline")):
            result = mirror.dispatch({"method": "tools/call", "params": {"name": "read_screen"}})
        self.assertTrue(result["isError"])
        self.assertIn("unavailable", result["content"][0]["text"])
        self.assertEqual(mirror.dispatch({"method": "ping"}), {})

    def test_tool_returns_image(self):
        jpeg = b"\xff\xd8image\xff\xd9"
        with patch.object(mirror, "capture_frame", return_value=(jpeg, "image/jpeg")):
            result = mirror.dispatch({"method": "tools/call", "params": {"name": "read_screen"}})
        self.assertEqual(result["content"], [{
            "type": "image", "data": base64.b64encode(jpeg).decode(), "mimeType": "image/jpeg",
        }])


if __name__ == "__main__":
    unittest.main()
