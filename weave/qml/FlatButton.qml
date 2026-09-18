import QtQuick
import QtQuick.Controls

// One button look for the whole application, so no colour literal ever appears
// in a window file.
Button {
    id: control
    property bool accent: false
    // A mark rather than a word wants to be drawn larger, or it reads as
    // small print beside the marks around it.
    property int fontSize: 12

    implicitHeight: 28
    padding: 10

    contentItem: Label {
        text: control.text
        font.pixelSize: control.fontSize
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
            // A wash of the accent rather than the raised surface. Every
            // window drawn over a page is that surface itself, so inside one
            // the old highlight was the ground and the button lit up as
            // nothing at all. A wash stands out on either ground and in a
            // light theme as well as a dark one.
            if (control.down)
                return Theme.wash(Theme.colors.accent, 0.34)
            if (control.hovered)
                return Theme.wash(Theme.colors.accent, 0.20)
            return "transparent"
        }
        border.width: control.accent ? 0 : 1
        border.color: control.hovered && control.enabled && !control.accent
                      ? Theme.colors.accent : Theme.colors.border
    }
}
