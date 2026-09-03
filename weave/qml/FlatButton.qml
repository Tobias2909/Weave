import QtQuick
import QtQuick.Controls

// One button look for the whole application, so no colour literal ever appears
// in a window file.
Button {
    id: control
    property bool accent: false

    implicitHeight: 28
    padding: 10

    contentItem: Label {
        text: control.text
        font.pixelSize: 12
        color: control.enabled
               ? (control.accent ? Theme.colors.badgeText : Theme.colors.text)
               : Theme.colors.textMuted
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: 6
        color: {
            if (!control.enabled)
                return Theme.colors.border
            if (control.accent)
                return control.hovered ? Theme.colors.accentHover : Theme.colors.accent
            return control.hovered ? Theme.colors.surfaceRaised : "transparent"
        }
        border.width: control.accent ? 0 : 1
        border.color: Theme.colors.border
    }
}
