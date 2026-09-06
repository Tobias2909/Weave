import QtQuick
import QtQuick.Controls

// One entry of a themed menu. The highlight is a rounded band inside the
// panel rather than a full width bar, which is what makes a menu look like
// part of this window instead of part of the desktop.
MenuItem {
    id: item

    implicitHeight: 32
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

    background: Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        radius: 7
        color: item.hovered ? Qt.rgba(Theme.colors.accent.r, Theme.colors.accent.g,
                                      Theme.colors.accent.b, 0.22)
                            : "transparent"
        border.width: item.hovered ? 1 : 0
        border.color: Qt.rgba(Theme.colors.accent.r, Theme.colors.accent.g,
                              Theme.colors.accent.b, 0.45)
    }
}
