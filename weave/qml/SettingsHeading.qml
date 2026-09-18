import QtQuick
import QtQuick.Controls

// One part of a settings card, named.
//
// The cards are the four subjects, and a card that holds several jobs at once
// reads as a heap unless each of them carries a word over it. The line
// belongs to the part that follows, so the first part in a card asks for
// none.
Item {
    id: heading
    property string text: ""
    property bool rule: true

    width: parent ? parent.width : 200
    // Its own height, stated rather than implied. An Item implies no height
    // at all, and a heading that asked for its implicit one would draw as
    // nothing while its rows stayed.
    implicitHeight: heading.rule ? 32 : 18
    height: implicitHeight

    Rectangle {
        visible: heading.rule
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: Theme.colors.border
    }

    Label {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        text: heading.text.toUpperCase()
        color: Theme.colors.textMuted
        font.pixelSize: 10
        font.letterSpacing: 1.2
        font.weight: Font.DemiBold
    }
}
