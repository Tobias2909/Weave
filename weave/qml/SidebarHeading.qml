import QtQuick
import QtQuick.Controls

// A section title in the sidebar, with an optional single action on the right.
Item {
    id: heading
    property string text: ""
    property string actionText: ""
    signal action()

    width: parent ? parent.width : 200
    // Its own height, so a heading that is drawn only sometimes can be given
    // the room it takes and none when it is not there. An Item implies no
    // height of its own, and a section that asked for its implicit one got
    // nothing and vanished while its rows stayed.
    implicitHeight: 26
    height: implicitHeight

    Label {
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        text: heading.text.toUpperCase()
        color: Theme.colors.textMuted
        font.pixelSize: 10
        font.letterSpacing: 1.2
        font.weight: Font.DemiBold
    }

    Label {
        id: actionLabel
        visible: heading.actionText !== ""
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: heading.actionText
        color: actionHover.hovered ? Theme.colors.accent : Theme.colors.textMuted
        font.pixelSize: 16
        HoverHandler { id: actionHover }
        TapHandler { onTapped: heading.action() }
    }
}
