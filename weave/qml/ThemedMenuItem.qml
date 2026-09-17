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

    // A line under the entry saying why it cannot be pressed. Drawn whenever
    // it is set rather than only under the pointer, because an entry that
    // grows when the hand arrives moves every entry below it out from under
    // the hand that was going there.
    property string note: ""

    implicitHeight: item.note === "" ? 32 : 46
    leftPadding: 12
    rightPadding: 12
    focusPolicy: Qt.NoFocus

    contentItem: Column {
        spacing: 1

        Label {
            width: parent.width
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

        Label {
            objectName: "menuItemNote"
            width: parent.width
            visible: item.note !== ""
            text: item.note
            color: Theme.colors.textMuted
            font.pixelSize: 10
            elide: Text.ElideRight
        }
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
