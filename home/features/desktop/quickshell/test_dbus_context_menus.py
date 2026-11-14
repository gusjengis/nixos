"""Exercise delayed, nested D-Bus menus through a real StatusNotifierItem.

Run with Python + dbus-next under the active Wayland session. The temporary tray
item unregisters when this process exits; no application commands are executed.
"""

import asyncio
import os
from pathlib import Path

from dbus_next import Variant, PropertyAccess
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property, method


class TrayItem(ServiceInterface):
    def __init__(self):
        super().__init__("org.kde.StatusNotifierItem")

    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":
        return "ApplicationStatus"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":
        return "quickshell-context-menu-test"

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":
        return "QuickShell menu test"

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "Active"

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":
        return "folder"

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":
        return "/Menu"

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":
        return True


class Menu(ServiceInterface):
    def __init__(self):
        super().__init__("com.canonical.dbusmenu")
        self.clicked = asyncio.Event()
        self.clicked_count = 0

    def properties(self, item):
        result = {"label": Variant("s", ["", "Tools", "Deep submenu", "Fixture command"][item]),
                  "enabled": Variant("b", True), "visible": Variant("b", True)}
        if item < 3:
            result["children-display"] = Variant("s", "submenu")
        return result

    def layout(self, item, depth):
        children = [Variant("(ia{sv}av)", self.layout(item + 1, depth - 1))] if item < 3 and depth != 0 else []
        return [item, self.properties(item), children]

    @method()
    async def GetLayout(self, parent: "i", depth: "i", names: "as") -> "u(ia{sv}av)":
        await asyncio.sleep(.12)
        return [1, self.layout(parent, depth)]

    @method()
    def GetGroupProperties(self, ids: "ai", names: "as") -> "a(ia{sv})":
        return [[item, self.properties(item)] for item in ids]

    @method()
    def AboutToShow(self, item: "i") -> "b":
        return False

    @method()
    def Event(self, item: "i", event: "s", data: "v", timestamp: "u"):
        if event == "clicked" and item == 3:
            self.clicked_count += 1
            self.clicked.set()


async def main():
    bus = await MessageBus().connect()
    name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
    await bus.request_name(name)
    menu = Menu()
    bus.export("/StatusNotifierItem", TrayItem())
    bus.export("/Menu", menu)
    watcher = "org.kde.StatusNotifierWatcher"
    introspection = await bus.introspect(watcher, "/StatusNotifierWatcher")
    proxy = bus.get_proxy_object(watcher, "/StatusNotifierWatcher", introspection)
    await proxy.get_interface(watcher).call_register_status_notifier_item(name)
    process = None
    try:
        fixture = Path(__file__).with_name("test_context_menus.qml")
        process = await asyncio.create_subprocess_exec(
            "qs", "--no-color", "-p", str(fixture),
            env={**os.environ, "CONTEXT_MENU_TRAY_FIXTURE": "1"},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(process.communicate(), 20)
        text = output.decode()
        print(text, end="")
        assert process.returncode == 0 and "FAIL:" not in text and "PASS:" in text
        await asyncio.wait_for(menu.clicked.wait(), 2)
        assert menu.clicked_count == 1, menu.clicked_count
        print("PASS: delayed D-Bus root, two hover submenus, and exact leaf clicked event")
    finally:
        if process and process.returncode is None:
            process.terminate()
            await process.wait()
        bus.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
