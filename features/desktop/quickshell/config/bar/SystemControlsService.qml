import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root

    property var wifi: ({ "enabled": false, "connected": null, "networks": [] })
    property var bluetooth: ({ "powered": false, "discovering": false, "devices": [] })
    property var brightness: ({ "available": false, "percent": 0 })
    property string actionError: ""
    property string actionTarget: ""
    readonly property string commandPath: Quickshell.env("HOME")
        + "/.nix-profile/bin/quickshell-system-controls"

    function parseState(output, fallback) {
        try {
            return JSON.parse(output);
        } catch (error) {
            const state = Object.assign({}, fallback);
            state.error = "Invalid system control response";
            return state;
        }
    }

    function refreshWifi() {
        if (!wifiRequest.running)
            wifiRequest.running = true;
    }

    function refreshBluetooth() {
        if (!bluetoothRequest.running)
            bluetoothRequest.running = true;
    }

    function refreshBrightness() {
        if (!brightnessRequest.running)
            brightnessRequest.running = true;
    }

    function refresh() {
        refreshWifi();
        refreshBluetooth();
        refreshBrightness();
    }

    function run(target, args) {
        if (action.running)
            return;
        actionError = "";
        actionTarget = target;
        action.command = [commandPath].concat(args);
        action.running = true;
    }

    function wifiPower(enabled) { run("wifi", ["wifi-power", enabled ? "on" : "off"]); }
    function wifiScan() { run("wifi", ["wifi-scan"]); }
    function wifiConnect(ssid, password) {
        const args = ["wifi-connect", ssid];
        if (password)
            args.push(password);
        run("wifi", args);
    }
    function wifiDisconnect() { run("wifi", ["wifi-disconnect"]); }
    function bluetoothPower(enabled) { run("bluetooth", ["bluetooth-power", enabled ? "on" : "off"]); }
    function bluetoothScan() { run("bluetooth", ["bluetooth-scan"]); }
    function bluetoothAction(actionName, address) {
        run("bluetooth", ["bluetooth-" + actionName, address]);
    }
    function setBrightness(percent) { run("brightness", ["brightness-set", Math.round(percent).toString()]); }

    property var wifiRequest: Process {
        command: [root.commandPath, "wifi-state"]
        stdout: StdioCollector { id: wifiOutput }
        onExited: (code, status) => {
            root.wifi = root.parseState(wifiOutput.text,
                ({ "enabled": false, "connected": null, "networks": [] }));
        }
    }

    property var bluetoothRequest: Process {
        command: [root.commandPath, "bluetooth-state"]
        stdout: StdioCollector { id: bluetoothOutput }
        onExited: (code, status) => {
            root.bluetooth = root.parseState(bluetoothOutput.text,
                ({ "powered": false, "discovering": false, "devices": [] }));
        }
    }

    property var brightnessRequest: Process {
        command: [root.commandPath, "brightness-state"]
        stdout: StdioCollector { id: brightnessOutput }
        onExited: (code, status) => {
            root.brightness = root.parseState(brightnessOutput.text,
                ({ "available": false, "percent": 0 }));
        }
    }

    property var action: Process {
        stdout: StdioCollector { id: actionOutput }
        onExited: (code, status) => {
            let result = {};
            try {
                result = JSON.parse(actionOutput.text);
            } catch (error) {
                result = { "ok": false, "error": "System control failed" };
            }
            root.actionError = result.ok ? "" : result.error || "System control failed";
            if (root.actionTarget === "wifi")
                root.refreshWifi();
            else if (root.actionTarget === "bluetooth")
                root.refreshBluetooth();
            else if (root.actionTarget === "brightness")
                root.refreshBrightness();
            action.command = [];
        }
    }

    property var poll: Timer {
        interval: 15000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }
}
