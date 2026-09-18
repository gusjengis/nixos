#!/usr/bin/env python3
"""Fetch AI subscription usage and manage OpenAI workspace profiles."""

import base64
import fcntl
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path


TIMEOUT = 10
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_PROFILES = {
    "personal": "Personal",
    "business": "Business",
}


def read_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def data_home(home):
    return Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))


def auth_path(home):
    return data_home(home) / "opencode" / "auth.json"


def profile_path(home, profile):
    return account_dir(home) / f"{profile}.json"


def account_dir(home):
    # Saved OAuth material lives here, so this directory is created private and
    # kept private. Other directories we write into belong to other programs and
    # keep whatever permissions their owner chose.
    directory = data_home(home) / "quickshell" / "ai-accounts"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory


@contextmanager
def account_lock(home):
    # Serializes profile reads/writes against a concurrent switch, so a usage
    # poll cannot publish a half-swapped credential.
    with (account_dir(home) / ".lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def cache_path(home):
    state_home = Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state"))
    return state_home / "quickshell" / "ai-usage.json"


def write_private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(value, file, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def cache_key(provider):
    return provider.get("id", provider["name"])


def read_cache(path):
    try:
        return {cache_key(entry): entry for entry in read_json(path)["providers"]}
    except (KeyError, OSError, TypeError, ValueError):
        return {}


def write_cache(path, providers, cached=None):
    merged = dict(cached or {})
    for provider in providers:
        if not provider.get("stale"):
            merged[cache_key(provider)] = provider

    fresh = list(merged.values())
    if not fresh:
        return
    try:
        write_private_json(path, {"providers": fresh})
    except OSError:
        pass


def request_json(url, headers, data=None):
    request = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def window(label, value, reset):
    return {
        "label": label,
        "used": round(float(value or 0)),
        "reset": reset,
    }


def fresh(provider):
    provider["fetched_at"] = int(time.time())
    return provider


def normalize_claude(data):
    return {
        "id": "anthropic",
        "name": "Anthropic",
        "available": True,
        "windows": [
            window("5h", data.get("five_hour", {}).get("utilization"), data.get("five_hour", {}).get("resets_at")),
            window("7d", data.get("seven_day", {}).get("utilization"), data.get("seven_day", {}).get("resets_at")),
        ],
    }


def openai_identity(profile, saved, active=False):
    return {
        "id": f"openai-{profile}",
        "name": f"OpenAI · {OPENAI_PROFILES[profile]}",
        "profile": profile,
        "saved": saved,
        "active": active,
    }


def normalize_openai(data, profile, active=False):
    limits = data.get("rate_limit") or {}
    primary = limits.get("primary_window") or {}
    secondary = limits.get("secondary_window") or {}
    return {
        **openai_identity(profile, True, active),
        "available": True,
        "windows": [
            window(label, value["used_percent"], value.get("reset_at"))
            for label, value in (("5h", primary), ("7d", secondary))
            if value.get("used_percent") is not None
        ],
    }


class AccountError(Exception):
    """A profile problem worth showing on the card, rather than a transport failure."""


class ReauthRequired(AccountError):
    """The stored login was rejected, so only a fresh save can recover it."""


def unavailable(name, error, cached=None, *, identity=None):
    if isinstance(error, urllib.error.HTTPError):
        reason = "rate limited" if error.code == 429 else f"HTTP {error.code}"
    elif isinstance(error, FileNotFoundError):
        reason = "not logged in"
    else:
        reason = str(error) if isinstance(error, AccountError) else "request failed"

    base = identity or {"name": name}
    previous = (cached or {}).get(cache_key(base)) or {}
    return {
        **base,
        "available": bool(previous.get("windows")),
        "stale": True,
        "error": reason,
        "windows": previous.get("windows", []),
        "fetched_at": previous.get("fetched_at"),
    }


def validate_openai_auth(auth):
    if not isinstance(auth, dict) or auth.get("type") != "oauth":
        raise AccountError("current OpenAI login is not OAuth")
    for key in ("access", "refresh", "accountId"):
        if not auth.get(key):
            raise AccountError("current OpenAI login is incomplete")
    # Not a truthiness check: an already-expired credential is still valid input,
    # because the refresh token is what actually recovers it.
    if not isinstance(auth.get("expires"), (int, float)) or isinstance(auth.get("expires"), bool):
        raise AccountError("current OpenAI login is incomplete")
    return auth


def read_profile(home, profile):
    return validate_openai_auth(read_json(profile_path(home, profile))["auth"])


def account_id_from_token(token):
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
    except (IndexError, TypeError, ValueError):
        return None


def refresh_openai_auth(auth):
    if auth["expires"] > int(time.time() * 1000) + 60_000:
        return auth
    payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": auth["refresh"],
        "client_id": OPENAI_CLIENT_ID,
    }).encode()
    try:
        tokens = request_json(
            "https://auth.openai.com/oauth/token",
            {"Content-Type": "application/x-www-form-urlencoded"},
            payload,
        )
    except urllib.error.HTTPError as error:
        # A rejected refresh token cannot be retried into working; the only way
        # back is re-connecting that workspace in OpenCode and saving again.
        if error.code in (400, 401, 403):
            raise ReauthRequired("saved login expired") from error
        raise
    account_id = account_id_from_token(tokens.get("id_token") or tokens["access_token"]) or auth["accountId"]
    if account_id != auth["accountId"]:
        raise AccountError("refreshed login changed workspace")
    return {
        "type": "oauth",
        "access": tokens["access_token"],
        "refresh": tokens.get("refresh_token", auth["refresh"]),
        "expires": int(time.time() * 1000) + int(tokens.get("expires_in", 3600)) * 1000,
        "accountId": account_id,
    }


def current_openai_auth(home):
    return validate_openai_auth(read_json(auth_path(home))["openai"])


def account_status(home):
    """Return identity metadata only; never expose tokens or refresh a login."""
    try:
        current = current_openai_auth(home)["accountId"]
    except (KeyError, OSError, ValueError, AccountError):
        current = None
    profiles = []
    active = None
    for profile in OPENAI_PROFILES:
        try:
            saved = read_profile(home, profile)
        except (KeyError, OSError, ValueError, AccountError):
            continue
        profiles.append(profile)
        if saved["accountId"] == current:
            active = profile
    return {"ok": True, "active": active, "saved": profiles}


def store_profile(home, profile, auth):
    write_private_json(profile_path(home, profile), {
        "id": profile,
        "label": OPENAI_PROFILES[profile],
        "auth": auth,
    })


def sync_current_profile(home):
    try:
        current = current_openai_auth(home)
    except (KeyError, OSError, ValueError, AccountError):
        return None
    for profile in OPENAI_PROFILES:
        try:
            saved = read_profile(home, profile)
        except (KeyError, OSError, ValueError, AccountError):
            continue
        if saved["accountId"] == current["accountId"]:
            store_profile(home, profile, current)
            return profile
    return None


def save_profile(home, profile):
    if profile not in OPENAI_PROFILES:
        raise AccountError(f"unknown profile: {profile}")
    current = current_openai_auth(home)
    for other, label in OPENAI_PROFILES.items():
        if other == profile:
            continue
        try:
            saved = read_profile(home, other)
        except (KeyError, OSError, ValueError, AccountError):
            continue
        if saved["accountId"] == current["accountId"]:
            raise AccountError(f"this login is already saved as {label}")
    # Overwriting this same slot is allowed on purpose: it is the only way to
    # recover a profile whose refresh token died. The cross-slot check above is
    # what keeps the two cards from ever pointing at one workspace.
    store_profile(home, profile, current)


def activate_profile(home, profile):
    if profile not in OPENAI_PROFILES:
        raise AccountError(f"unknown profile: {profile}")
    sync_current_profile(home)
    selected = refresh_openai_auth(read_profile(home, profile))
    store_profile(home, profile, selected)
    path = auth_path(home)
    all_auth = read_json(path)
    all_auth["openai"] = selected
    write_private_json(path, all_auth)


def fetch_claude(home, cached):
    try:
        auth = read_json(home / ".claude" / ".credentials.json")["claudeAiOauth"]
        data = request_json(
            "https://api.anthropic.com/api/oauth/usage",
            {
                "Authorization": f"Bearer {auth['accessToken']}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "quickshell-ai-usage/1",
            },
        )
        return fresh(normalize_claude(data))
    except (KeyError, OSError, ValueError, urllib.error.URLError) as error:
        return unavailable("Anthropic", error, cached, identity={"id": "anthropic", "name": "Anthropic"})


def unsaved_profile(profile, reason):
    return {
        **openai_identity(profile, False, False),
        "available": False,
        "error": reason,
        "windows": [],
    }


def fetch_openai_profile(home, profile, active, cached):
    identity = openai_identity(profile, True, active)
    try:
        auth = refresh_openai_auth(read_profile(home, profile))
        store_profile(home, profile, auth)
        if active:
            all_auth = read_json(auth_path(home))
            if all_auth.get("openai", {}).get("accountId") == auth["accountId"]:
                all_auth["openai"] = auth
                write_private_json(auth_path(home), all_auth)
        data = request_json(
            "https://chatgpt.com/backend-api/wham/usage",
            {
                "Authorization": f"Bearer {auth['access']}",
                "ChatGPT-Account-Id": auth["accountId"],
                "User-Agent": "quickshell-ai-usage/1",
            },
        )
        return fresh(normalize_openai(data, profile, active))
    except FileNotFoundError:
        return unsaved_profile(profile, "not saved")
    except ReauthRequired as error:
        return unsaved_profile(profile, str(error))
    except urllib.error.HTTPError as error:
        # A rejected token means this profile can only be fixed by saving again,
        # so the card goes back to being a save button. Every other HTTP failure
        # is treated as transient and keeps the cached numbers.
        if error.code in (401, 403):
            return unsaved_profile(profile, "saved login rejected")
        return unavailable(identity["name"], error, cached, identity=identity)
    except (KeyError, OSError, ValueError, AccountError, urllib.error.URLError) as error:
        return unavailable(identity["name"], error, cached, identity=identity)


def collect_usage(home):
    path = cache_path(home)
    cached = read_cache(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claude = pool.submit(fetch_claude, home, cached)
        with account_lock(home):
            active = sync_current_profile(home)
            openai = [
                fetch_openai_profile(home, profile, active == profile, cached)
                for profile in OPENAI_PROFILES
            ]
        providers = [claude.result(), *openai]
    write_cache(path, providers, cached)
    return {"providers": providers}


def account_command(args):
    home = Path.home()
    if args == ["status"]:
        with account_lock(home):
            return account_status(home)
    if not (len(args) == 2 and args[0] in ("save", "select") or
            len(args) == 3 and args[0] == "select"):
        raise AccountError("usage: quickshell-ai-account status | <save|select> <personal|business> [expected-active]")
    action, profile = args[:2]
    with account_lock(home):
        # Router selections are conditional; do not undo a switch made by
        # another pane or the widget while this caller waited for the lock.
        if len(args) == 3 and account_status(home)["active"] != args[2]:
            return {**account_status(home), "action": "select", "switched": False}
        if action == "save":
            save_profile(home, profile)
        else:
            activate_profile(home, profile)
        return {**account_status(home), "profile": profile, "action": action, "switched": action == "select"}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "account":
        try:
            result = account_command(sys.argv[2:])
        except (KeyError, OSError, ValueError, AccountError, urllib.error.URLError) as error:
            json.dump({"ok": False, "error": str(error)}, sys.stdout, separators=(",", ":"))
            sys.stdout.write("\n")
            return 1
    else:
        result = collect_usage(Path.home())
    json.dump(result, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
