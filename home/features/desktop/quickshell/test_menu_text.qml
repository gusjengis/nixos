//@ pragma UseQApplication
import QtQuick
import Quickshell
import "config/menus"

ShellRoot {
    id: test
    FloatingWindow {
        implicitWidth: 300
        implicitHeight: 100
        visible: true
        color: "#263e47"
        ContextMenuRow {
            id: row
            x: 10; y: 10; width: 260; height: 24
            entry: ({text: "New Folder", enabled: true, icon: "", isSeparator: false,
                buttonType: QsMenuButtonType.None, checkState: Qt.Unchecked, hasChildren: false})
        }
    }
    Timer {
        interval: 400
        running: true
        onTriggered: {
            const label = row.children.find(item => item.objectName === "context-menu-label");
            label.grabToImage(result => {
                result.saveToFile("/tmp/opencode/menu-text-unhighlighted.png");
                row.keyboardHighlighted = true;
                selected.start();
            });
        }
    }
    Timer {
        id: selected
        interval: 100
        onTriggered: {
            const label = row.children.find(item => item.objectName === "context-menu-label");
            label.grabToImage(result => {
                result.saveToFile("/tmp/opencode/menu-text-highlighted.png");
                console.log("PASS: isolated production label captured in both selection states");
                Qt.quit();
            });
        }
    }
}
