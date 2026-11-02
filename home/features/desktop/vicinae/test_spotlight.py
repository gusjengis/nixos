#!/usr/bin/env python3
"""Exercise patched production QML offscreen: completion gates and stable glyph geometry.

Run with PySide6 and the pinned Vicinae source path as the sole argument.
Native icon/selection-shader pixel measurements additionally use real launcher captures.
"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtCore import QPointF, QUrl, qInstallMessageHandler
from PySide6.QtGui import QFont, QGuiApplication, QImage
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest


def patched_source(upstream, destination):
    owner = Path(__file__).parent
    names = ['spotlight-layout.patch', 'spotlight-glass.patch', 'spotlight-suggestion.patch',
             'spotlight-placement.patch', 'spotlight-parity.patch']
    paths = set()
    for name in names:
        paths.update(re.findall(r'^--- a/(.*)$', (owner / name).read_text(), re.M))
    for name in paths:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / name, target)
    for name in names:
        subprocess.run(['patch', '--batch', '-p1', '-i', str(owner / name)], cwd=destination,
                       capture_output=True, text=True, check=True)
    return destination / 'src/server/src/ui/qml'


messages = []
qInstallMessageHandler(lambda kind, context, message: messages.append(message))
app = QGuiApplication([])
app.setFont(QFont('SF Pro'))
engine = QQmlEngine()
components = []


def create(source, properties=None):
    component = QQmlComponent(engine)
    component.setData(source.encode(), QUrl('file:///tmp/opencode/spotlight-regression.qml'))
    root = component.createWithInitialProperties(properties or {})
    assert root is not None, '\n'.join(e.toString() for e in component.errors())
    components.append(component)
    return root


def settle():
    QTest.qWait(40)
    app.processEvents()


def frame(window):
    settle()
    image = window.grabWindow().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not image.isNull()
    return bytes(image.constBits())


with tempfile.TemporaryDirectory(prefix='spotlight-qml-') as temporary:
    qml = patched_source(Path(sys.argv[1]), Path(temporary))
    delegate = (qml / 'list/ListItemDelegate.qml').read_text()
    delegate = delegate.replace('import Vicinae\n', '').replace('SelectableDelegate {', 'Item {', 1)
    delegate = delegate.replace('Theme.', 'root.theme.')
    for name in ('titleText', 'subtitleText', 'textRow'):
        delegate = delegate.replace(f'id: {name}', f'id: {name}; objectName: "{name}"')
    delegate = delegate.replace('    id: root', '''    id: root
    property bool selected: false
    property bool hovered: false
    readonly property bool strongSelected: selected
    readonly property bool softSelected: false
    property bool quickAccessActive: false
    property QtObject theme: QtObject {
        property real regularFontSize: 10.5
        property string fontFamily: "SF Pro"
        property color textMuted: "gray"
        property color foreground: "#e2e2e9"
    }
    property QtObject appearance: QtObject {
        property int rowLeftPadding: 16
        property int rowRightPadding: 19
        property int rowTextSpacing: 6
        property color selectedSecondaryText: "white"
        property color hoveredSecondaryText: "gray"
    }''', 1)
    # Only native image/badge/accessory dependencies are stubbed. The actual
    # RowLayout, title, subtitle, font, supersampling and positioning stay intact.
    delegate = delegate.rstrip()[:-1] + '''
    component ViciImage: Item { property var source; property bool safetyMargins }
    component TextBadge: Text {}
    component ShortcutBadge: Item { property var tokens; implicitWidth: 30 }
    component ListAccessoryRow: Item {
        property var accessories
        implicitWidth: accessories.length ? 90 : 0
        implicitHeight: 18
    }
}'''
    root = create(delegate, dict(width=638,
        itemTitle='Power Off System', itemSubtitle='', itemIconSource='fixture',
        itemAlias='', itemIsActive=False, itemAccessory=''))
    assert root.property('featured') and root.height() == 57, 'Plugin/shared rows must use Spotlight geometry by default'
    window = QQuickWindow()
    window.resize(638, 57)
    root.setParentItem(window.contentItem())
    window.show()
    original = frame(window)
    title = root.findChild(QQuickItem, 'titleText')
    subtitle = root.findChild(QQuickItem, 'subtitleText')
    origin = title.mapToScene(QPointF())
    assert origin.x() == 70, origin
    assert origin.y() == round(origin.y()), origin
    baseline = (origin.x(), origin.y(), title.width(), title.height())
    count = 0
    for selected in (True, False, True):
        for subtitle_text in ('Metadata that must stay hidden', '', 'Returned from extension'):
            root.setProperty('selected', selected)
            root.setProperty('itemSubtitle', subtitle_text)
            root.setProperty('itemAccessory', 'Application' if selected else '')
            current = frame(window)
            point = title.mapToScene(QPointF())
            assert (point.x(), point.y(), title.width(), title.height()) == baseline
            assert not subtitle.isVisible()
            assert current == original, 'Selection/accessory/subtitle transition changed glyph pixels'
            count += 1
    print(f'PASS: {count} subtitle/accessory/selection transitions; glyph pixels byte-identical; title origin {origin.x()},{origin.y()}')
    window.close()

    search = (qml / 'launcher/SearchBar.qml').read_text()
    start = search.index('    readonly property string suggestionTitle:')
    end = search.index('    // Soft (query-focused)', start)
    bindings = search[start:end].replace('Launcher.', 'root.launcher.')
    start = search.index('            Rectangle {\n                id: suggestionPill')
    end = search.index('            TextInput {', start)
    visuals = search[start:end].replace('id: suggestionPill', 'id: suggestionPill; objectName: "pill"')
    placeholder_gate = re.search(r'visible: (!searchInput.displayText[^\n]+)', search).group(1)
    completion = create('''import QtQuick
Item {
    id: root
    width: 550; height: 55
    property alias query: searchInput.text
    property alias cursor: searchInput.cursorPosition
    property string currentTitle: "Slack"
    property QtObject commandView: QtObject {
        property string spotlightTitle: root.currentTitle
        property string spotlightIcon: "icon://selected"
    }
    property QtObject launcher: QtObject {
        property bool searchInteractive: true
        property bool hasCompleter: false
        property bool compacted: false
        property bool showBackButton: false
    }
    property QtObject appearance: QtObject { property bool keyboardSelection: true }
    TextInput { id: searchInput; anchors.fill: parent; text: "s"; font.pixelSize: 26 }
    Text { objectName: "placeholder"; visible: PLACEHOLDER }
BINDINGS
VISUALS
}'''.replace('PLACEHOLDER', placeholder_gate.replace('Launcher.', 'root.launcher.'))
        .replace('BINDINGS', bindings).replace('VISUALS', visuals))
    pill = completion.findChild(QQuickItem, 'pill')
    placeholder = completion.findChild(QQuickItem, 'placeholder')
    settle()
    completion.setProperty('cursor', 1)
    for name in ('Slack', 'System Settings', 'Safari'):
        completion.setProperty('currentTitle', name)
        settle()
        assert pill.isVisible(), name
        assert completion.property('suggestionIcon') == 'icon://selected'
    completion.setProperty('query', '')
    settle()
    assert completion.property('suggestionSuffix') == 'Safari — Open'
    assert pill.isVisible() and not placeholder.isVisible()
    completion.setProperty('query', 'sa')
    completion.setProperty('cursor', 1)
    settle()
    assert not pill.isVisible() and completion.property('suggestionIcon') == ''
    completion.setProperty('cursor', 2)
    settle()
    assert pill.isVisible()
    completion.setProperty('currentTitle', 'S' + 'a' * 200)
    settle()
    assert pill.width() <= completion.width() - pill.x()
    print('PASS: selected-result completion, empty query, placeholder exclusion, cursor editing, long-title clipping')
    assert not messages, messages
    print('PASS: no QML warnings')
