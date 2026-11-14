"""Keep native V2 storage isolated while retaining explicit V1 helper commands."""
import json
from contextlib import closing
import os
from pathlib import Path
import sys


def main():
    specification = json.loads(Path(sys.argv[1]).read_text())
    arguments = sys.argv[2:]
    sys.path.insert(0, specification["contexts"])
    import context_chat_library as library
    import opencode_backend as backend

    legacy = bool(arguments and arguments[0] in {"db", "export", "import"})
    explicit = os.environ.get("OPENCODE_DB")
    if explicit and explicit != ":memory:" and Path(explicit).is_file():
        with closing(backend.connect(explicit)) as db:
            legacy = legacy or db.protocol == 1
    if legacy:
        for key in ("OPENCODE_CONFIG_DIR", "OPENCODE_DATA_DIR", "OPENCODE_STATE_DIR", "OPENCODE_CACHE_DIR", "OPENCODE_HANDOFF_FILE"):
            os.environ.pop(key, None)
        os.environ["OPENCODE_CONFIG_DIR"] = specification["legacy_config"]
        os.environ["OPENCODE_DB"] = explicit or specification["legacy_database"]
        os.environ["OPENCODE_PROTOCOL"] = "1"
        library.launch(specification["legacy_binary"], arguments)
        return
    os.environ.update(specification["environment"])
    os.environ["OPENCODE_DB"] = explicit or specification["database"]
    selected = backend.profile()
    aliases = selected.get("aliases", {})
    for index, argument in enumerate(arguments):
        if index and arguments[index - 1] in {"--session", "-s"}:
            arguments[index] = aliases.get(argument, argument)
        elif argument.startswith("--session="):
            identity = argument.partition("=")[2]
            arguments[index] = "--session=" + aliases.get(identity, identity)
    # The daemon cannot own one desktop context's environment for every TUI.
    # Keep context-bound interactive and scripted requests on private servers.
    commands = {"upgrade", "update", "uninstall", "acp", "api", "debug", "auth", "mcp", "plugin",
                "models", "stats", "mini", "run", "session", "service", "reload", "pair", "serve"}
    server_commands = {"api", "auth", "models", "stats", "mini", "run", "session", "reload"}
    explicit_server = any(value == "--server" or value.startswith("--server=") or value == "--standalone" for value in arguments)
    if not explicit_server:
        if not arguments or arguments[0] not in commands:
            if not any(value in {"--version", "-v", "--help", "-h"} for value in arguments):
                arguments = ["--standalone", *arguments]
        elif arguments[0] in server_commands or (arguments[:2] in [["debug", "agents"], ["debug", "config"]]):
            arguments = [*arguments, "--standalone"]
    library.launch(specification["binary"], arguments)


if __name__ == "__main__":
    main()
