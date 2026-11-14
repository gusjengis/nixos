// Render actual tooltip text offscreen for comparison with 26-dock/mac.
// QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software quickshell -p test_dock_label_render.qml
import QtQuick
import QtQuick.Window
import Quickshell
import "config" as Desktop

ShellRoot {
    Window {
        visible: true
        width: 160; height: 80
        Item {
            id: scene
            anchors.fill: parent
            Rectangle { anchors.fill: parent; color: "#525252" }
            Text {
                x:14; y:27.28125-baselineOffset
                text:"Google Chrome"; color:"#f2ffffff"
                font { family:"SF Pro";pixelSize:15 }
                renderType:Text.NativeRendering
            }
            Desktop.DockLabel {
                id: label
                x:14; y:67-baselineOffset
                text:"Google Chrome"
            }
        }
        Timer {
            interval:200; running:true
            onTriggered: {
                scene.grabToImage(result => {
                    const path = Quickshell.env("DOCK_LABEL_RENDER") || "/tmp/opencode/dock-label-render.png";
                    if (!result.saveToFile(path)) throw new Error("Cannot save " + path);
                    console.log("PASS: rendered actual tooltip typography",label.implicitWidth);
                    Qt.quit();
                });
            }
        }
    }
}
