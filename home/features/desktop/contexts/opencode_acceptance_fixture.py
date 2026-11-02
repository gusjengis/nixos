"""Device-local native TUI acceptance fixtures. No production profile is read."""

import codecs
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


AGENTS = Path(__file__).resolve().parent.parent.parent / "agents/opencode"


class Screen:
    """Small VT screen for OpenTUI's absolute-position rendering, not ANSI stripping.

    Handles cursor addressing, overwrite, line/display erase, OSC and style. Unknown
    CSI commands are ignored (terminal queries/modes never become visible text).
    """

    def __init__(self, rows=45, columns=150):
        self.rows, self.columns = rows, columns
        self.cells = [[" "] * columns for _ in range(rows)]
        self.row = self.column = 0
        self.pending = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

    @property
    def lines(self):
        return ["".join(row).rstrip() for row in self.cells]

    @property
    def text(self):
        return "\n".join(self.lines)

    def feed(self, data):
        self.pending += self.decoder.decode(data)
        while self.pending:
            value = self.pending
            if value.startswith("\x1b["):
                match = re.match(r"\x1b\[([0-?]*)([ -/]*)([@-~])", value)
                if not match:
                    return
                self.pending = value[match.end():]
                params, _, command = match.groups()
                if any(c in params for c in "?><="):
                    continue
                args = [int(n or 0) for n in params.split(";")]
                n = args[0] or 1
                if command in ("H", "f"):
                    self.row = min(self.rows - 1, max(0, (args[0] or 1) - 1))
                    self.column = min(self.columns - 1, max(0, (args[1] if len(args) > 1 else 1) - 1))
                elif command == "G":
                    self.column = min(self.columns - 1, n - 1)
                elif command == "d":
                    self.row = min(self.rows - 1, n - 1)
                elif command in "ABCD":
                    dr, dc = {"A": (-n, 0), "B": (n, 0), "C": (0, n), "D": (0, -n)}[command]
                    self.row = min(self.rows - 1, max(0, self.row + dr))
                    self.column = min(self.columns - 1, max(0, self.column + dc))
                elif command == "J":
                    for r in range(self.rows):
                        for c in range(self.columns):
                            if args[0] in (2, 3) or (args[0] == 0 and (r, c) >= (self.row, self.column)) or (args[0] == 1 and (r, c) <= (self.row, self.column)):
                                self.cells[r][c] = " "
                elif command == "K":
                    for c in range(self.columns):
                        if args[0] == 2 or (args[0] == 0 and c >= self.column) or (args[0] == 1 and c <= self.column):
                            self.cells[self.row][c] = " "
                elif command == "X":
                    for c in range(self.column, min(self.columns, self.column + n)):
                        self.cells[self.row][c] = " "
                continue
            if value.startswith(("\x1b]", "\x1bP")):
                match = re.search(r"\x07|\x1b\\", value)
                if not match:
                    return
                self.pending = value[match.end():]
                continue
            if value[0] == "\x1b":
                if len(value) < 2:
                    return
                self.pending = value[2:]
                continue
            char, self.pending = value[0], value[1:]
            if char == "\r":
                self.column = 0
            elif char == "\n":
                self.row = min(self.rows - 1, self.row + 1)
            elif char == "\b":
                self.column = max(0, self.column - 1)
            elif char >= " " and char != "\x7f":
                self.cells[self.row][self.column] = char
                self.column = min(self.columns - 1, self.column + 1)


class ScriptedProvider:
    """Records actual HTTP dispatch before releasing any streamed response."""

    def __init__(self):
        self.requests = []
        self.release = threading.Event()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append({"at": time.monotonic(), "path": self.path, "body": body})
                fixture.release.wait(30)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for delta, finish in (({"role": "assistant", "content": "OC1 provider completed."}, None), ({}, "stop")):
                        chunk = {"id": "oc1-fixture", "object": "chat.completion.chunk", "created": 1,
                                 "model": "mock", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                        self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def matching(self, token):
        return [item for item in self.requests if token in json.dumps(item["body"].get("messages", []))]

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


class NativeFixture:
    def __init__(self, binary, *, launcher=False, blocked=True, tui_plugins=()):
        self.temporary = tempfile.TemporaryDirectory(prefix="oc1-acceptance-", dir="/tmp/opencode")
        self.base = Path(self.temporary.name)
        self.binary, self.launcher, self.blocked = binary, launcher, blocked
        self.provider = ScriptedProvider()
        self.master = self.child = None
        self.screen = Screen()
        self.raw = bytearray()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("OPENCODE_", "CONTEXT_", "TMUX", "CLAUDE_", "ANTHROPIC_", "OPENAI_"))}
        for name in ("home", "config", "data", "state", "cache", "runtime", "work", "bin"):
            (self.base / name).mkdir(mode=0o700)
        self.env.update(HOME=str(self.base / "home"), XDG_CONFIG_HOME=str(self.base / "config"),
                        XDG_DATA_HOME=str(self.base / "data"), XDG_STATE_HOME=str(self.base / "state"),
                        XDG_CACHE_HOME=str(self.base / "cache"), XDG_RUNTIME_DIR=str(self.base / "runtime"),
                        CONTEXT_ROOT=str(self.base / "contexts"), OPENCODE_DB=str(self.base / "data/opencode/opencode.db"),
                        OPENCODE_DISABLE_PROJECT_CONFIG="1", OPENCODE_DISABLE_DEFAULT_PLUGINS="1",
                        TERM="xterm-256color", NO_COLOR="1",
                        OC1_EVENTS=str(self.base / "events.jsonl"), OC1_BASE=str(self.base))
        # Minimal real context metadata; no notebook/profile initialization needed.
        context_home = self.base / "contexts/OC1 fixture"
        (context_home / ".context").mkdir(parents=True)
        (context_home / ".context/notes/.obsidian").mkdir(parents=True)
        metadata = {"version": 1, "id": str(uuid.uuid4()), "name": "OC1 fixture",
                    "working_directory": str(self.base / "work"), "repositories": []}
        (context_home / ".context/context.json").write_text(json.dumps(metadata))
        self.context = metadata | {"path": str(context_home)}
        self.env.update(CONTEXT_ID=self.context["id"], CONTEXT_DIRECTORY=self.context["path"])
        scope = self.base / "scope.json"
        scope.write_text(json.dumps({"context_id": self.context["id"], "ids": [self.context["id"]], "hidden": []}))
        self.env["OPENCODE_CONTEXT_SCOPE_FILE"] = str(scope)
        self.env["OPENCODE_CONTEXT_STATE_FILE"] = str(self.base / "freshness.json")
        observer = self.base / "observer.js"
        observer.write_text('''import {appendFileSync} from "node:fs";
export const AcceptanceObserver = async () => ({event: async ({event}) => {
  if (["message.updated", "message.part.updated", "session.created", "session.error"].includes(event.type))
    appendFileSync(process.env.OC1_EVENTS, JSON.stringify({event, at:Date.now()})+"\\n");
}});
''')
        tui_observer = self.base / "tui-observer.js"
        tui_observer.write_text('''import {writeFileSync} from "node:fs";
export default {id:"oc1-observer", tui:async(api)=>{
 const timer=setInterval(()=>{
  const route=api.route.current;
  const messages=route.name==="session" ? api.state.session.messages(route.params.sessionID).map(info=>({info,parts:api.state.part(info.id)})) : [];
  writeFileSync(process.env.OC1_BASE+"/tui.json", JSON.stringify({route,ready:api.state.ready,messages,session:route.name==="session"?api.state.session.get(route.params.sessionID):null}));
 },20); api.lifecycle.onDispose(()=>clearInterval(timer));
}};
''')
        helper = self.base / "bin/opencode-context-chats"
        # Real selected-library CLI; only background discovery can be held.
        library = Path(__file__).with_name("context_chat_library.py")
        helper.write_text(f"#!{sys.executable}\n" + f'''import os,sys,time,pathlib
base=pathlib.Path(os.environ["OC1_BASE"])
if sys.argv[1:2] == ["prepare"]:
 (base/"prepare-started").touch()
 (base/"prepare-pid").write_text(str(os.getpid()))
 if os.environ.get("OC1_BLOCK_PREPARE") == "1":
  while not (base/"prepare-release").exists(): time.sleep(.02)
os.execv({sys.executable!r}, [{sys.executable!r}, "-B", {str(library)!r}, *sys.argv[1:]])
''')
        helper.chmod(0o700)
        native_helper = self.base / "bin/opencode"
        native_helper.write_text(f"#!{sys.executable}\nimport os,sys\nos.execv({binary!r},[{binary!r},*sys.argv[1:]])\n")
        native_helper.chmod(0o700)
        self.env["PATH"] = str(self.base / "bin") + os.pathsep + self.env.get("PATH", "")
        self.env["OC1_BLOCK_PREPARE"] = "1" if blocked else "0"
        config = {"model": "oc1-fixture/mock", "small_model": "oc1-fixture/mock",
                  "enabled_providers": ["oc1-fixture"], "plugin": [str(AGENTS / "plugins/context-library.js"), str(observer)],
                  "provider": {"oc1-fixture": {"npm": "@ai-sdk/openai-compatible", "name": "OC1 local fixture",
                    "options": {"baseURL": f"http://127.0.0.1:{self.provider.server.server_port}/v1", "apiKey": "fixture"},
                    "models": {"mock": {"name": "OC1 mock", "tool_call": True,
                                       "limit": {"context": 131072, "output": 4096}}}}}}
        guard = Path.home() / ".config/opencode/plugins/session-policy.js"
        if guard.exists():
            config["plugin"].insert(0, str(guard.resolve()))
        self.env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        directory = self.base / "config/opencode"
        directory.mkdir()
        if os.environ.get("OPENCODE_ACCEPTANCE_INTEGRATED") == "1":
            # Production TUI set for the integrated binary (tmux-only plugins omitted).
            tui_plugins = tuple(dict.fromkeys((*tui_plugins, "context-library.tsx", "context-stale.tsx")))
        plugins = [str(tui_observer), *(str(AGENTS / "tui-plugins" / name) for name in tui_plugins)]
        (directory / "tui.json").write_text(json.dumps({"plugin": plugins}))

    def start(self, args=()):
        if self.child is not None:
            raise RuntimeError("fixture already started")
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.screen.rows, self.screen.columns, 0, 0))
        command = [self.binary, *args]
        if self.launcher:
            command = [sys.executable, "-B", str(Path(__file__).with_name("context_chat_library.py")), "launch", *command]
        self.started = time.monotonic()
        self.child = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                                      cwd=self.base / "work", env=self.env, start_new_session=True)
        os.close(slave)
        self.master = master

    def pump(self, timeout=.02):
        if select.select([self.master], [], [], timeout)[0]:
            try:
                data = os.read(self.master, 262144)
            except OSError:
                data = b""
            self.raw.extend(data)
            self.screen.feed(data)

    def wait(self, predicate, description, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump()
            if predicate():
                return time.monotonic()
            if self.child.poll() is not None:
                break
        raise AssertionError(f"Timed out: {description}; exit={self.child.poll()}\n{self.screen.text}\nEvents: {self.events()[-5:]}")

    def write(self, text):
        os.write(self.master, text.encode())

    def events(self):
        try:
            return [json.loads(line) for line in (self.base / "events.jsonl").read_text().splitlines()]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def tui(self):
        try:
            return json.loads((self.base / "tui.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def accepted(self, token):
        return [message for message in self.tui().get("messages", [])
                if message["info"]["role"] == "user" and
                any(p.get("type") == "text" and token in p.get("text", "") for p in message["parts"])]

    def publish_state(self, **fields):
        """Publish through OC5's actual authoritative API, not alternate state."""
        marker = self.tui()["session"]["metadata"]["desktop_context"]
        code = "import context_chat_state as s,json; print(json.dumps(s.publish(" + ",".join(repr(x) for x in
               (self.env["OPENCODE_CONTEXT_STATE_FILE"], marker["id"], marker["chat"])) + ",**" + repr(fields) + ")))"
        return json.loads(subprocess.check_output([sys.executable, "-B", "-c", code],
                          cwd=Path(__file__).parent, env=self.env, text=True))

    def cli(self, *arguments, timeout=30):
        """Run actual selected-library CLI with isolated native helper executable."""
        return subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("context_chat_library.py")), *arguments],
                              cwd=self.base / "work", env=self.env, capture_output=True, text=True, timeout=timeout)

    def native(self, *arguments):
        # File-backed stdout avoids upstream CLI pipe truncation on large exports.
        with tempfile.TemporaryFile(mode="w+") as output:
            result = subprocess.run([self.binary, *arguments], cwd=self.base / "work",
                                    env=self.env | {"OPENCODE_CONTEXT_HELPER": "1"},
                                    stdout=output, stderr=subprocess.PIPE, text=True, timeout=45)
            output.seek(0)
            result.stdout = output.read()
        return result

    def mirror_from(self, source):
        """Simulate complete archive delivery, never native DB or local ledger."""
        owner = source.context["id"]
        self.context["id"] = owner
        metadata = Path(self.context["path"]) / ".context/context.json"
        value = json.loads(metadata.read_text())
        value["id"] = owner
        metadata.write_text(json.dumps(value))
        self.env["CONTEXT_ID"] = owner
        Path(self.env["OPENCODE_CONTEXT_SCOPE_FILE"]).write_text(json.dumps({"context_id": owner, "ids": [owner], "hidden": []}))
        incoming = Path(source.context["path"]) / ".context/state/chats"
        target = Path(self.context["path"]) / ".context/state/chats"
        shutil.copytree(incoming, target, dirs_exist_ok=True)

    def stop(self):
        if self.child:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.child.wait(3)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait(3)
            self.child = None
        if self.master is not None:
            os.close(self.master)
            self.master = None

    def reset(self):
        self.stop()
        self.screen = Screen()
        self.raw.clear()
        self.provider.requests.clear()
        self.provider.release.clear()
        for name in ("prepare-started", "prepare-release", "events.jsonl", "tui.json"):
            (self.base / name).unlink(missing_ok=True)

    def close(self):
        self.provider.release.set()
        (self.base / "prepare-release").touch()
        self.stop()
        self.provider.close()
        self.temporary.cleanup()
