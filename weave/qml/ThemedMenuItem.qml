import QtQuick
import QtQuick.Controls

// One entry of a themed menu. The highlight is a rounded band inside the
// panel rather than a full width bar, which is what makes a menu look like
// part of this window instead of part of the desktop.
MenuItem {
    id: item

    // A theme colour arrives as a string, and a string has no r, g or b. Read
    // one straight off Theme.colors and every channel is undefined, which
    // Qt.rgba turns into black without a word, so the band under the pointer
    // was a dark smudge rather than a tint of the accent.
    readonly property color accent: Qt.color(Theme.colors.accent)

    implicitHeight: 32
    // An entry that opens a menu of its own is made by the menu rather than
    // declared, so the menu it opens says whether it is offered at all.
    visible: !item.subMenu || item.subMenu.offered !== false
    height: visible ? implicitHeight : 0
    leftPadding: 12
    rightPadding: 12
    focusPolicy: Qt.NoFocus

    contentItem: Label {
        text: item.text
        // Full strength at rest, like every other piece of text in the
        // window. Only what cannot be pressed is muted.
        color: item.enabled ? Theme.colors.text : Theme.colors.watchedDim
        font.pixelSize: 12
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
    }

    // An entry that opens a menu offering a quick pick takes the pick on a
    // press, and the menu still opens on the pointer resting on the entry.
    // The press is caught here, so the entry is not clicked as well, which
    // would open the menu over the pick. Hover is left to the entry.
    MouseArea {
        anchors.fill: parent
        enabled: item.subMenu !== null && item.subMenu.quickPick === true
        acceptedButtons: Qt.LeftButton
        onClicked: item.subMenu.takeQuickPick()
    }

    // Drawn only on an entry that opens a menu of its own.
    arrow: Label {
        x: item.width - width - item.rightPadding
        y: (item.height - height) / 2
        visible: item.subMenu !== null
        text: "\u25b8"
        color: Theme.colors.textMuted
        font.pixelSize: 11
    }

    background: Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        radius: 7
        color: item.hovered ? Qt.rgba(item.accent.r, item.accent.g, item.accent.b, 0.22)
                            : "transparent"
        border.width: item.hovered ? 1 : 0
        border.color: Qt.rgba(item.accent.r, item.accent.g, item.accent.b, 0.45)
    }
}
