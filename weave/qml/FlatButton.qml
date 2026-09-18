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

    // Theme.colors is a map of STRINGS. Asking a string for .r answers
    // undefined without a word, and Qt.rgba(undefined, ...) is black, so the
    // role is turned into a colour before anything is asked of it.
    readonly property color highlight: Qt.color(Theme.colors.accent)

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
                return Qt.rgba(control.highlight.r, control.highlight.g,
                               control.highlight.b, 0.34)
            if (control.hovered)
                return Qt.rgba(control.highlight.r, control.highlight.g,
                               control.highlight.b, 0.20)
            return "transparent"
        }
        border.width: control.accent ? 0 : 1
        border.color: control.hovered && control.enabled && !control.accent
                      ? Theme.colors.accent : Theme.colors.border
    }
}
