import QtQuick
import QtQuick.Controls

// Something is being read for the page this sits on. The same pill and the
// same turning mark as the notice at the foot of the window, so the two read
// as one thing moved, put beside the button that asked for it instead, where
// the eye already is after pressing it. A pill rather than bare words because
// it has to be seen: over the bright corner of a washed theme a muted word
// and an accent mark on their own all but disappeared.
Rectangle {
    id: busy
    property string text: ""

    visible: text !== ""
    implicitWidth: row.implicitWidth + 24
    implicitHeight: 26
    width: implicitWidth
    height: implicitHeight
    radius: 13
    color: Theme.colors.surfaceRaised
    border.width: 1
    border.color: Theme.colors.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 9
            height: 9
            radius: 2
            color: Theme.colors.accent
            RotationAnimator on rotation {
                running: busy.visible
                loops: Animation.Infinite
                from: 0
                to: 360
                duration: 1400
            }
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: busy.text
            color: Theme.colors.text
            font.pixelSize: 12
        }
    }
}
