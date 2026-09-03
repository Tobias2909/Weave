import QtQuick
import QtQuick.Controls

// One selectable row in the sidebar, used for both groups and boxes.
Rectangle {
    id: row
    property string label: ""
    property int count: 0
    property bool selected: false

    signal activated()
    signal contextRequested()

    height: 32
    color: selected ? Theme.colors.surfaceRaised : "transparent"

    HoverHandler { id: rowHover }
    TapHandler { onTapped: row.activated() }
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: row.contextRequested()
    }

    Rectangle {
        visible: row.selected
        width: 3
        height: parent.height
        color: Theme.colors.accent
    }

    Label {
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.right: countLabel.left
        anchors.rightMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        text: row.label
        elide: Text.ElideRight
        font.pixelSize: 13
        color: row.selected || rowHover.hovered ? Theme.colors.text : Theme.colors.textMuted
    }

    Label {
        id: countLabel
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: row.count > 0 ? row.count : ""
        font.pixelSize: 11
        color: Theme.colors.textMuted
    }
}
