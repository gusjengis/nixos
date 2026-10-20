"""Checkpoint during logind's delay phase, before session teardown.

Run persistently from session-env-sync AFTER importing fresh display environment.
The inhibitor must exist before shutdown starts: a user ExecStop is too late for
shell-launched Hyprland, tmux, editor and chat APIs. Requires dbus-next with UNIX
FD negotiation, context-checkpoint on PATH, and notify-send for failure notices.
"""

import asyncio
import logging
import os
import signal
import stat

from dbus_next import BusType
from dbus_next.aio import MessageBus

LOG = logging.getLogger("context-shutdown-barrier")
CHECKPOINT_TIMEOUT = 90
DBUS_TIMEOUT = 10
NAME = "org.freedesktop.login1"
PATH = "/org/freedesktop/login1"


async def notify_failure(message):
    LOG.error("%s", message)
    process = None
    try:
        async with asyncio.timeout(3):
            process = await asyncio.create_subprocess_exec(
                "notify-send", "--urgency=critical", "Context checkpoint failed", message
            )
            if await process.wait():
                LOG.error("notify-send failed with status %s", process.returncode)
    except Exception:
        LOG.exception("Could not deliver checkpoint failure notification")
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


class ShutdownBarrier:
    def __init__(self, manager):
        self.manager = manager
        self.fd = None

    async def acquire(self):
        if self.fd is not None:
            return
        # The high-level dbus-next proxy replaces D-Bus 'h' indices using the
        # message's unix_fds array. Never treat a raw message body index as an FD.
        fd = await asyncio.wait_for(
            self.manager.call_inhibit(
                "shutdown", "context-checkpoint", "Save desktop context before shutdown", "delay"
            ),
            DBUS_TIMEOUT,
        )
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
            if (
                not isinstance(fd, int)
                or fd <= 2
                or not stat.S_ISFIFO(os.fstat(fd).st_mode)
                or not target.startswith(("pipe:[", "/run/systemd/inhibit/"))
            ):
                raise RuntimeError(f"Inhibit returned no logind pipe FD: {fd!r} -> {target}")
            os.set_inheritable(fd, False)
        except BaseException:
            if isinstance(fd, int) and fd > 2:
                os.close(fd)
            raise
        self.fd = fd
        LOG.info("Acquired shutdown delay inhibitor fd=%d -> %s", fd, target)

    def release(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)
            LOG.info("Released shutdown delay inhibitor fd=%d", fd)

    async def checkpoint(self):
        process = None
        try:
            LOG.info("Shutdown announced; saving context (maximum %ss)", CHECKPOINT_TIMEOUT)
            async with asyncio.timeout(CHECKPOINT_TIMEOUT):
                process = await asyncio.create_subprocess_exec(
                    "context-checkpoint", "save", "--reason", "shutdown",
                    start_new_session=True,
                )
                status = await process.wait()
                if status:
                    raise RuntimeError(f"context-checkpoint exited with status {status}")
            LOG.info("Shutdown checkpoint complete")
        finally:
            # Release BEFORE cleanup/notifications, including timeout, cancellation
            # and spawn failure. logind also enforces its independent 120s ceiling.
            self.release()
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.returncode is None:
                    await asyncio.wait_for(process.wait(), 2)


async def run():
    bus = MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True)
    barrier = None
    save = receive = disconnected = None
    try:
        await asyncio.wait_for(bus.connect(), DBUS_TIMEOUT)
        introspection = await asyncio.wait_for(bus.introspect(NAME, PATH), DBUS_TIMEOUT)
        manager = bus.get_proxy_object(NAME, PATH, introspection).get_interface(NAME + ".Manager")
        barrier = ShutdownBarrier(manager)
        events = asyncio.Queue()
        manager.on_prepare_for_shutdown(events.put_nowait)
        # Round-trip after AddMatch ensures the signal subscription is installed.
        preparing = await asyncio.wait_for(manager.get_preparing_for_shutdown(), DBUS_TIMEOUT)
        if preparing:
            raise RuntimeError("Started during shutdown; inhibitor must be acquired earlier")
        await barrier.acquire()
        if await asyncio.wait_for(manager.get_preparing_for_shutdown(), DBUS_TIMEOUT):
            raise RuntimeError("Shutdown raced inhibitor startup; cannot promise checkpoint barrier")
        disconnected = asyncio.create_task(bus.wait_for_disconnect())
        receive = asyncio.create_task(events.get())
        preparing = False
        while True:
            waiting = [receive, disconnected] + ([save] if save is not None else [])
            done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
            if disconnected in done:
                await disconnected
                raise RuntimeError("System D-Bus disconnected")
            if save in done:
                await save  # Checkpoint failures must reach systemd as nonzero exit.
                save = None
            if receive in done:
                active = receive.result()
                receive = asyncio.create_task(events.get())
                if active and not preparing:
                    preparing = True
                    save = asyncio.create_task(barrier.checkpoint())
                elif not active:
                    preparing = False
                    if save is not None:
                        save.cancel()
                        await asyncio.gather(save, return_exceptions=True)
                        save = None
                    await barrier.acquire()
    finally:
        if barrier is not None:
            barrier.release()
        tasks = [task for task in (save, receive, disconnected) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bus.disconnect()


async def main():
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await run()
    except asyncio.CancelledError:
        return 0
    except Exception as error:
        LOG.exception("Shutdown barrier failed")
        await notify_failure(str(error) or type(error).__name__)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(levelname)s: %(message)s")
    raise SystemExit(asyncio.run(main()))
