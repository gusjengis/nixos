//@ pragma UseQApplication
import QtQuick
import Quickshell
import Quickshell.Io
import "config" as Desktop

ShellRoot {
    id: test
    property string log: ""
    property int stage: 0
    function check(value, message) {
        if (!value)
            throw new Error(message)
    }
    function openMenu() {
        peer.connected = true
        menus.peer = peer
        menus.show(peer, {x: 400, y: 300})
    }
    QtObject {
        id: peer
        property bool connected: true
        property var request: ({items: [
            {text: "&Open && inspect", mnemonic: true, enabled: true, token: 0, children: []},
            {text: "Disabled", enabled: false, token: 1, children: []},
            {text: "Separator", isSeparator: true, children: []},
            {text: "Checked", checkable: true, checked: true, enabled: true, token: 3, children: []},
            {text: "Submenu", enabled: true, children: [{text: "Child & literal", enabled: true, token: 5, children: []}]}
        ]})
        function write(value) { test.log += value }
        function flush() { }
    }
    Desktop.ExternalContextMenus {
        id: menus
        socketPath: "/tmp/opencode/chromium-menu-test.sock"
    }
    Process {
        id: client
        command: ["python3", "-c", "import socket,json; s=socket.socket(socket.AF_UNIX); s.connect('/tmp/opencode/chromium-menu-test.sock'); s.sendall((json.dumps({'items':[{'text':'Socket command','enabled':True,'token':42,'children':[]}]})+'\\n').encode()); print(s.recv(64).decode().strip(),flush=True); s.close()"]
        stdout: StdioCollector {
            onStreamFinished: {
                if (text.trim() === "42")
                    console.log("PASS: real Unix socket request, cascade node rendering, exact command response");
                else
                    console.error("FAIL: Unix socket response", text)
                Qt.quit()
            }
        }
    }
    Timer {
        interval: 100
        repeat: true
        running: test.stage === 1
        onTriggered: {
            if (menus.node && menus.node.entryAt(0) && menus.node.entryAt(0).token === 42)
                menus.node.activateIndex(0)
        }
    }
    Timer {
        interval: 10000
        running: true
        onTriggered: {
            console.error("FAIL: external context menu socket timed out")
            Qt.quit()
        }
    }
    Timer {
        id: stageTimer
        interval: 400
        running: true
        onTriggered: {
            stageTimer.stop()
            try {
                // Shared cascade node: rows, mnemonics, checkmarks, navigation.
                openMenu()
                const root = menus.node
                test.check(root !== null, "Root cascade node created")
                test.check(root.entryAt(0).text === "Open & inspect", "Mnemonic escaping")
                test.check(root.entryAt(3).checkState === Qt.Checked, "Checked state")
                test.check(root.entryAt(4).hasChildren === true, "Submenu entry marked")
                root.moveHighlight(1)
                root.moveHighlight(1)
                test.check(root.currentIndex === 3, "Keyboard skips disabled items and separators")
                // Leaf activation delivers its token exactly once and tears down.
                root.currentIndex = 0
                const leafRoot = root
                root.activateHighlighted()
                test.check(test.log === "0\n", "Leaf token delivered once")
                test.check(menus.node === null, "Cascade closed after leaf")
                test.check(menus.peer === null, "Connection released after command")
                test.check(leafRoot.visible === false, "Root window hidden after leaf")
                // Child level: spawn onto the chain, activate from the child.
                openMenu()
                menus.node.currentIndex = 4
                menus.node.activateHighlighted()
                test.check(menus.node !== null, "Cascade stays open on submenu entry")
                const child = menus.node.tipNode()
                test.check(child !== null && child !== menus.node, "Child node on chain")
                test.check(child.entryAt(0).text === "Child & literal", "Literal ampersand preserved")
                test.check(child.entryAt(0).token === 5, "Child token intact")
                child.currentIndex = 0
                child.activateHighlighted()
                test.check(test.log === "0\n5\n", "Child leaf token delivered")
                test.check(menus.node === null, "Whole chain torn down via root")
                // Back pops the child; cancel reports -1.
                openMenu()
                const backRoot = menus.node
                backRoot.currentIndex = 4
                backRoot.activateHighlighted()
                test.check(backRoot.liveNodes.length === 1, "Child open before back")
                backRoot.backOne()
                test.check(backRoot.liveNodes.length === 0, "Back pops child")
                test.check(menus.node === backRoot, "Root retained after back")
                backRoot.closeCascade(true)
                test.check(test.log === "0\n5\n-1\n", "Cancel reports -1")
                test.check(backRoot.visible === false && menus.node === null, "Canceled chain cleaned up")
                // Error/disconnect path still reports -1 without a cascade.
                peer.connected = true
                menus.peer = peer
                menus.finish(-1)
                test.check(test.log === "0\n5\n-1\n-1\n", "Direct finish writes -1")
                console.log("PASS: external context menus use the shared cascade; render, navigate, submenus, back, commands, dismissal")
                test.stage = 1
                client.running = true
            } catch (error) {
                console.error("FAIL:", error)
                Qt.quit()
            }
        }
    }
}
