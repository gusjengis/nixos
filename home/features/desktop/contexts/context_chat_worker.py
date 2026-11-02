"""Device-local chat scheduling primitives; no archive or freshness policy lives here.

Family ownership spans expensive work, but publication locks are context-scoped
and short. Durable completion is supplied by the caller's verified ledger, not
by an independent result cache that could mistake an interrupted import for success.
"""

import contextvars
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager


class Busy(TimeoutError):
    pass


class Cancelled(RuntimeError):
    pass


_deadline = contextvars.ContextVar("chat_worker_deadline", default=None)
_cancel = contextvars.ContextVar("chat_worker_cancel", default=None)


def operation_deadline():
    return _deadline.get()


def cancellation_requested():
    cancel = _cancel.get()
    return bool(cancel and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()))


def _cancelled(cancel):
    return cancellation_requested() or bool(cancel and (
        cancel.is_set() if hasattr(cancel, "is_set") else cancel()))


def _end(timeout, deadline=None):
    limits = [time.monotonic() + max(0, timeout)]
    limits.extend(value for value in (deadline, operation_deadline()) if value is not None)
    return min(limits)


def database_identity(database):
    """Local DB incarnation; callers must not pass an external working root."""
    path = Path(database).absolute()
    try:
        stat = path.stat()
        incarnation = [stat.st_dev, stat.st_ino]
    except FileNotFoundError:
        incarnation = None
    return [str(path), incarnation]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _root(owner):
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    path = base / "desktop-contexts/chat-workers" / _digest(str(owner))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _notify(callback, state):
    if callback:
        callback(state)


@contextmanager
def _selected(owner):
    directory = _root(owner) / "selected"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / uuid.uuid4().hex
    with path.open("x") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def _selected_waiting(owner):
    directory = _root(owner) / "selected"
    if not directory.exists():
        return False
    for path in directory.iterdir():
        try:
            with path.open("r") as lease:
                # Creation and flock cannot be atomic. Give a newly created
                # marker time to acquire its lease before stale-file cleanup.
                if time.time() - os.fstat(lease.fileno()).st_mtime < 0.1:
                    return True
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
    return False


@contextmanager
def scoped_lock(owner, *, database=None, conversation=None, kind="publication",
                timeout=0.25, deadline=None, cancel=None, on_state=None,
                priority="selected"):
    """Bounded advisory lock. No network/root probe or subprocess inside helper.

    Omitting database is deliberate for a context's shared archive writer lock.
    Different kinds never alias. Nested callers must not reacquire the same key.
    """
    if priority not in ("selected", "maintenance"):
        raise ValueError("Unknown chat work priority")
    key = [kind, database_identity(database) if database is not None else None, conversation]
    path = _root(owner) / (_digest(key) + ".lock")
    end = _end(timeout, deadline)
    waiting = False
    with path.open("a") as lock:
        while True:
            if _cancelled(cancel):
                raise Cancelled("Chat operation cancelled while waiting for lock")
            try:
                if priority == "maintenance" and _selected_waiting(owner):
                    raise BlockingIOError()
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not waiting:
                    _notify(on_state, "waiting_lock")
                    waiting = True
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise Busy("Chat operation waiting for " + kind + " lock")
                time.sleep(min(0.02, remaining))
        try:
            _notify(on_state, "locked")
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def selected_work(owner, database, conversation, revision, work, *, check,
                  timeout=30, cancel=None, on_state=None):
    """Coalesce selected imports using the authoritative completion check.

    `check` must match requested revision and return None unless verified ready.
    Followers recheck after acquiring ownership, including after owner death.
    Cancellation of a follower only stops that follower. Owner cancellation can
    leave recovery work for the next owner, never a cached successful result.
    """
    end = _end(timeout)
    prior_cancel = _cancel.get()
    deadline_token = _deadline.set(end)
    cancel_token = _cancel.set(lambda: bool(
        (prior_cancel and (prior_cancel.is_set() if hasattr(prior_cancel, "is_set") else prior_cancel()))
        or (cancel and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()))))
    try:
        with _selected(owner), scoped_lock(owner, database=database, conversation=conversation,
                                          kind="family", timeout=timeout, deadline=end,
                                          on_state=on_state):
            if time.monotonic() >= end:
                raise Busy("Selected chat deadline expired")
            result = check()
            if result is not None:
                if cancellation_requested():
                    raise Cancelled("Selected chat cancelled")
                if time.monotonic() >= end:
                    raise Busy("Selected chat deadline expired during verification")
                _notify(on_state, "ready")
                return result
            if cancellation_requested():
                raise Cancelled("Selected chat cancelled")
            _notify(on_state, "running")
            result = work()
            # The caller owns durable acknowledgement; exceptions never become ready.
            if cancellation_requested():
                raise Cancelled("Selected chat cancelled")
            if time.monotonic() >= end:
                raise Busy("Selected chat deadline expired during work")
            _notify(on_state, "ready")
            return result
    finally:
        _cancel.reset(cancel_token)
        _deadline.reset(deadline_token)


def _stop_group(child, grace):
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    until = time.monotonic() + grace
    # Continue through grace even if the group leader exits: grandchildren may
    # ignore TERM and still hold output files or a native database transaction.
    while time.monotonic() < until:
        child.poll()
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def _guardian(arguments, grace):
    """Lifeline EOF handles abrupt caller death, including SIGKILL.

    Only this short-lived guardian owns the native process group. Native stdin
    never inherits the lifeline. No global signal handler is installed in caller.
    """
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    child = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        while child.poll() is None:
            readable, _, _ = select.select([sys.stdin.buffer], [], [], 0.02)
            if stopping or (readable and not os.read(sys.stdin.fileno(), 1)):
                _stop_group(child, grace)
                return 125
        result = child.returncode
        # Also clean up descendants left by an exited native command.
        _stop_group(child, grace)
        return result if result >= 0 else 128 - result
    except BaseException:
        _stop_group(child, grace)
        raise


def run_child(args, *, timeout=30, deadline=None, cancel=None, cwd=None,
              env=None, check=True, grace=1):
    """Run bounded native work; cancellation/parent death cleans descendants."""
    args = list(map(str, args))
    end = _end(timeout, deadline)
    if _cancelled(cancel):
        raise Cancelled("Chat subprocess cancelled before launch")
    if time.monotonic() >= end:
        raise subprocess.TimeoutExpired(args, timeout)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output, \
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
        guardian = subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).absolute()), "--guardian", str(grace), *args],
            stdin=subprocess.PIPE, stdout=output, stderr=errors, cwd=cwd, env=env,
            start_new_session=True)
        problem = None
        try:
            while guardian.poll() is None:
                if _cancelled(cancel):
                    problem = Cancelled("Chat subprocess cancelled")
                    break
                if time.monotonic() >= end:
                    problem = subprocess.TimeoutExpired(args, timeout)
                    break
                time.sleep(0.02)
        finally:
            guardian.stdin.close()
            try:
                guardian.wait(timeout=max(0, grace) + 2)
            except subprocess.TimeoutExpired:
                # Guardian normally terminates its group via EOF. This fallback
                # bounds a broken guardian; it never targets unrelated processes.
                guardian.kill()
                guardian.wait()
        output.seek(0)
        errors.seek(0)
        stdout, stderr = output.read(), errors.read()
        if problem:
            if isinstance(problem, subprocess.TimeoutExpired):
                problem.output, problem.stderr = stdout, stderr
            raise problem
        result = subprocess.CompletedProcess(args, guardian.returncode, stdout, stderr)
        if check and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, args, stdout, stderr)
        return result


if __name__ == "__main__" and len(sys.argv) >= 4 and sys.argv[1] == "--guardian":
    sys.exit(_guardian(sys.argv[3:], max(0, float(sys.argv[2]))))
