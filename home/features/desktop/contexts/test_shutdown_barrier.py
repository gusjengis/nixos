"""Run with python -m unittest discover -s home/features/desktop/contexts.

The optional ``python test_shutdown_barrier.py --live`` probe acquires/releases
an actual logind inhibitor, but never requests shutdown.
"""

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


HAS_DBUS = importlib.util.find_spec("dbus_next") is not None
if HAS_DBUS:
    spec = importlib.util.spec_from_file_location(
        "shutdown_barrier_under_test", Path(__file__).with_name("shutdown_barrier.py")
    )
    barrier_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(barrier_module)

SPAWN = asyncio.create_subprocess_exec


class Manager:
    """Pipe-backed logind stand-in: EOF proves inhibitor release."""

    def __init__(self):
        self.readers = []
        self.acquisitions = 0

    async def call_inhibit(self, *args):
        if args[0] != "shutdown" or args[-1] != "delay":
            raise AssertionError(f"Unexpected inhibitor request: {args}")
        read, write = os.pipe()
        os.set_blocking(read, False)
        self.readers.append(read)
        self.acquisitions += 1
        return write

    def on_prepare_for_shutdown(self, callback):
        self.signal = callback

    async def get_preparing_for_shutdown(self):
        return False

    def close(self):
        for fd in self.readers:
            os.close(fd)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.005)


@unittest.skipUnless(HAS_DBUS, "dbus_next unavailable")
class ShutdownBarrierTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, code, error=None, timeout=90):
        manager = Manager()
        barrier = barrier_module.ShutdownBarrier(manager)
        self.addCleanup(manager.close)
        self.addCleanup(barrier.release)
        await barrier.acquire()
        fd = barrier.fd

        async def command(*args, **kwargs):
            self.assertEqual(args, ("context-checkpoint", "save", "--reason", "shutdown"))
            return await SPAWN(sys.executable, "-c", code, **kwargs)

        with patch.object(barrier_module.asyncio, "create_subprocess_exec", command), patch.object(
            barrier_module, "CHECKPOINT_TIMEOUT", timeout
        ):
            if error:
                with self.assertRaises(error):
                    await barrier.checkpoint()
            else:
                await barrier.checkpoint()
        self.assertIsNone(barrier.fd)
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertEqual(os.read(manager.readers[-1], 1), b"")

    async def test_success(self):
        await self.exercise("pass")

    async def test_failure(self):
        await self.exercise("raise SystemExit(23)", RuntimeError)

    async def test_timeout(self):
        await self.exercise("import time; time.sleep(60)", TimeoutError, 0.05)

    async def test_missing_command(self):
        manager = Manager()
        barrier = barrier_module.ShutdownBarrier(manager)
        self.addCleanup(manager.close)
        self.addCleanup(barrier.release)
        await barrier.acquire()
        fd = barrier.fd
        with patch.object(
            barrier_module.asyncio, "create_subprocess_exec", side_effect=FileNotFoundError("missing")
        ):
            with self.assertRaises(FileNotFoundError):
                await barrier.checkpoint()
        self.assertIsNone(barrier.fd)
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertEqual(os.read(manager.readers[-1], 1), b"")

    async def test_raw_fd_index_rejected(self):
        with patch.object(barrier_module.os, "readlink", return_value="/dev/null"), patch.object(
            barrier_module.os, "close", wraps=os.close
        ) as close, patch.object(Manager, "call_inhibit", return_value=0):
            with self.assertRaises(RuntimeError):
                await barrier_module.ShutdownBarrier(Manager()).acquire()
            close.assert_not_called()  # Never close stdin for an untranslated index.

    async def test_failure_reaches_systemd(self):
        with patch.object(barrier_module, "run", side_effect=RuntimeError("probe failure")), patch.object(
            barrier_module, "notify_failure"
        ) as notify, self.assertLogs(barrier_module.LOG, level="ERROR"):
            self.assertEqual(await barrier_module.main(), 1)
            notify.assert_awaited_once_with("probe failure")

    async def test_signals_cancel_reacquire_and_disconnect(self):
        manager = Manager()

        class Bus:
            def __init__(self, **kwargs):
                if kwargs != dict(bus_type=barrier_module.BusType.SYSTEM, negotiate_unix_fd=True):
                    raise AssertionError(kwargs)
                self.disconnected = asyncio.Event()

            async def connect(self):
                return self

            async def introspect(self, *args):
                return None

            def get_proxy_object(self, *args):
                return self

            def get_interface(self, *args):
                return manager

            async def wait_for_disconnect(self):
                await self.disconnected.wait()

            def disconnect(self):
                self.disconnected.set()

        bus = Bus(bus_type=barrier_module.BusType.SYSTEM, negotiate_unix_fd=True)
        children = []

        async def command(*args, **kwargs):
            self.assertEqual(args, ("context-checkpoint", "save", "--reason", "shutdown"))
            child = await SPAWN(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
            children.append(child)
            return child

        task = None
        try:
            with patch.object(barrier_module, "MessageBus", return_value=bus), patch.object(
                barrier_module.asyncio, "create_subprocess_exec", command
            ):
                task = asyncio.create_task(barrier_module.run())
                await until(lambda: manager.acquisitions == 1)
                manager.signal(True)
                manager.signal(True)
                await until(lambda: len(children) == 1)
                manager.signal(False)
                await until(lambda: manager.acquisitions == 2)
                self.assertIsNotNone(children[0].returncode)
                self.assertEqual(os.read(manager.readers[0], 1), b"")
                bus.disconnect()
                with self.assertRaisesRegex(RuntimeError, "disconnected"):
                    await task
                self.assertEqual(os.read(manager.readers[1], 1), b"")
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            for child in children:
                if child.returncode is None:
                    child.kill()
                    await child.wait()
            manager.close()


@unittest.skipUnless(HAS_DBUS, "dbus_next unavailable")
@unittest.skipUnless("--live" in sys.argv, "explicit --live required for system D-Bus probe")
class LiveShutdownBarrierTests(unittest.IsolatedAsyncioTestCase):
    async def test_logind_inhibitor_and_entrypoint(self):
        bus = await barrier_module.MessageBus(
            bus_type=barrier_module.BusType.SYSTEM, negotiate_unix_fd=True
        ).connect()
        barrier = None
        try:
            intro = await bus.introspect(barrier_module.NAME, barrier_module.PATH)
            manager = bus.get_proxy_object(
                barrier_module.NAME, barrier_module.PATH, intro
            ).get_interface(barrier_module.NAME + ".Manager")
            self.assertFalse(await manager.get_preparing_for_shutdown())
            barrier = barrier_module.ShutdownBarrier(manager)
            await barrier.acquire()
            fd = barrier.fd
            self.assertTrue(os.readlink(f"/proc/self/fd/{fd}"))
            barrier.release()
            with self.assertRaises(OSError):
                os.fstat(fd)
            self.assertGreater(await manager.get_inhibit_delay_max_u_sec(), 0)
            process = await SPAWN(sys.executable, "-B", spec.origin, stderr=asyncio.subprocess.PIPE)
            try:
                async with asyncio.timeout(10):
                    line = await process.stderr.readline()
                    self.assertIn(b"Acquired shutdown delay inhibitor", line)
                    process.terminate()
                    self.assertEqual(await process.wait(), 0)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        finally:
            if barrier is not None:
                barrier.release()
            bus.disconnect()


if __name__ == "__main__":
    unittest.main(argv=[arg for arg in sys.argv if arg != "--live"], verbosity=2)
