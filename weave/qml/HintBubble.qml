import QtQuick
import QtQuick.Controls

// The window's own bubble for saying what something is for, the same one a
// button's hint uses, for anything that is not a button: a box to tick, a
// handle to drag. The style's own is drawn in colours no theme here chose.
ToolTip {
    id: bubble
    // Shown while this is true, which is usually the thing being hovered.
    property bool shown: false
    property string words: ""

    visible: shown && words !== ""
    delay: 450
    y: -implicitHeight - 6
    padding: 7

    contentItem: Label {
        text: bubble.words
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
