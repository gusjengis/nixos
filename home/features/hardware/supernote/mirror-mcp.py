#!/usr/bin/env python3
"""Expose Supernote mirror frames over MCP stdio."""

import base64
import json
import sys
import time
import urllib.error
import urllib.request


STREAM_URL = "http://127.0.0.1:18080/screencast.mjpeg"
MAX_FRAME = 12 * 1024 * 1024


def capture_frame():
    deadline = time.monotonic() + 10
    try:
        with urllib.request.urlopen(STREAM_URL, timeout=3) as stream:
            if "multipart/" not in stream.headers.get("Content-Type", ""):
                raise ValueError("Mirror did not return an MJPEG stream")
            while time.monotonic() < deadline:
                length = None
                while time.monotonic() < deadline:
                    line = stream.readline(4096)
                    if not line:
                        raise ValueError("Supernote mirror returned no complete frame")
                    if line in (b"\r\n", b"\n"):
                        break
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1].strip())
                if length is None:
                    continue
                if not 0 < length <= MAX_FRAME:
                    raise ValueError("Mirror frame has invalid size")
                frame = stream.read(length)
                if len(frame) != length:
                    raise ValueError("Supernote mirror returned an incomplete frame")
                if frame.startswith(b"\x89PNG\r\n\x1a\n"):
                    return frame, "image/png"
                if frame.startswith(b"\xff\xd8"):
                    return frame, "image/jpeg"
                raise ValueError("Mirror frame is not a PNG or JPEG image")
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError(f"Supernote mirror unavailable: {exc}") from exc
    raise ValueError("Supernote mirror returned no complete frame (is screen mirroring active?)")


def screenshot():
    frame, mime_type = capture_frame()
    return {
        "content": [
            {"type": "image", "data": base64.b64encode(frame).decode("ascii"), "mimeType": mime_type},
        ]
    }


def dispatch(request):
    method = request.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "supernote-mirror", "version": "1.0.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{
            "name": "read_screen",
            "description": "Capture current Supernote mirror screen as an image for visual inspection. Mirror must be running; no browser required.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        }]}
    if method == "tools/call":
        params = request.get("params") or {}
        if params.get("name") != "read_screen":
            raise KeyError("Unknown tool")
        try:
            return screenshot()
        except ValueError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    raise KeyError("Unknown method")


def main():
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if "id" not in request:
                continue
            try:
                result = dispatch(request)
                response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            except KeyError as exc:
                response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": str(exc)}}
        except (ValueError, TypeError) as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
