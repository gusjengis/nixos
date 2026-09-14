import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

Scope {
    id: service

    property bool enabled: false
    property var history: []
    readonly property var device: UPower.displayDevice
    readonly property bool available: enabled
        && device.ready
        && device.isPresent
        && device.isLaptopBattery
    readonly property bool charging: device.state === UPowerDeviceState.Charging
        || device.state === UPowerDeviceState.PendingCharge
        || device.state === UPowerDeviceState.FullyCharged
    readonly property int percentage: Math.round(device.percentage * 100)
    readonly property real estimateSeconds: charging ? device.timeToFull : device.timeToEmpty

    function reloadHistory() {
        const raw = historyFile.text();
        if (!raw || raw.trim() === "") {
            history = [];
            return;
        }

        const cutoff = Date.now() - 3 * 60 * 60 * 1000;
        const samples = [];
        for (const line of raw.trim().split(/\r?\n/)) {
            const parts = line.trim().split(/\s+/);
            if (parts.length < 2)
                continue;
            const timestamp = Number(parts[0]);
            const percentage = Number(parts[1]);
            if (timestamp >= cutoff)
                samples.push({ "timestamp": timestamp, "percentage": percentage });
        }
        history = samples;
    }

    FileView {
        id: historyFile
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state")
            + "/quickshell/battery-history.log"
        preload: true
        watchChanges: true
        onLoaded: service.reloadHistory()
        onFileChanged: service.reloadHistory()
    }

    // Logger prunes via atomic replacement, which can detach an inode watcher.
    Timer {
        interval: 60000
        repeat: true
        running: service.enabled
        onTriggered: historyFile.reload()
    }

    FileView {
        path: (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share")
            + "/quickshell/laptop"
        preload: true
        watchChanges: true
        onLoaded: service.enabled = text().trim() === "1"
        onFileChanged: reload()
    }
}
