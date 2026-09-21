import QtQuick
import Quickshell
import Quickshell.Io
import "../notifications"

Scope {
    id: root

    property bool shown: true

    function syncHyprlandBarState(): void {
        Quickshell.execDetached([
            "hyprctl",
            "eval",
            "require('monitor-modes').set_bar_visible(" + (root.shown ? "true" : "false") + ")"
        ]);
    }

    onShownChanged: syncHyprlandBarState()
    Component.onCompleted: syncHyprlandBarState()

    UsageService { id: usageService }
    BatteryService { id: batteryService }
    SystemControlsService { id: systemControlsService }
    MonitorModes {
        id: monitorModes
        onHugeMarginsChanged: root.syncHyprlandBarState()
    }
    NotificationService { id: notifications }

    IpcHandler {
        target: "bar"

        function toggle(): void { root.shown = !root.shown; }
        function show(): void { root.shown = true; }
        function hide(): void { root.shown = false; }
        function refreshUsage(): void { usageService.refresh(); }
        function usage(): string { return JSON.stringify(usageService.usage); }
        function battery(): string {
            return JSON.stringify({
                "enabled": batteryService.enabled,
                "ready": batteryService.device.ready,
                "present": batteryService.device.isPresent,
                "laptopBattery": batteryService.device.isLaptopBattery,
                "available": batteryService.available,
                "percentage": batteryService.percentage,
                "charging": batteryService.charging
            });
        }
        function clearNotifications(): void { notifications.clear(); }
    }

    Variants {
        model: monitorModes.initialized ? Quickshell.screens : []

        delegate: Component {
            BarWindow {
                required property var modelData
                screen: modelData
                shown: root.shown
                hugeMargins: monitorModes.hugeMargins[modelData.name] === true
                usage: usageService.usage
                refreshUsage: () => usageService.refresh()
                accountAction: (profile, saved) => usageService.account(profile, saved)
                accountBusy: usageService.accountBusy
                accountError: usageService.accountError
                battery: batteryService
                systemControls: systemControlsService
                notificationService: notifications
            }
        }
    }

    Variants {
        model: Quickshell.screens

        delegate: Component {
            NotificationStack {
                required property var modelData
                screen: modelData
                barShown: root.shown
                notificationService: notifications
            }
        }
    }
}
