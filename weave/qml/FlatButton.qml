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
    // A mark is not always drawn in the middle of the room the font gives it.
    // Measured per glyph and corrected here, since the eye reads the ink
    // rather than the box around it.
    property real nudge: 0
    property real nudgeY: 0
    // What it is for, and what it is set to, said under the pointer. A mark
    // cannot say either by itself.
    property string hint: ""

    implicitHeight: 28
    padding: 10

    // The window's own bubble rather than the style's, which is drawn in
    // colours that belong to no theme here.
    ToolTip {
        id: bubble
        parent: control
        visible: control.hint !== "" && control.hovered
        delay: 450
        y: -implicitHeight - 6
        padding: 7

        contentItem: Label {
            text: control.hint
            color: Theme.colors.text
            font.pixelSize: 11
        }

        background: Rectangle {
            radius: 6
            color: Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border
        }
    }

    contentItem: Label {
        text: control.text
        // A transform rather than an x. The control writes the content item's
        // geometry itself, so anything set here would be overwritten.
        transform: Translate { x: control.nudge; y: control.nudgeY }
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
