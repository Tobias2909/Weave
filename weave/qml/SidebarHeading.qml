import QtQuick
import QtQuick.Controls

// A section title in the sidebar, with an optional single action on the right.
Item {
    id: heading
    property string text: ""
    property string actionText: ""
    signal action()

    width: parent ? parent.width : 200
    height: 26

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
