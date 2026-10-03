import QtQuick
import QtQuick.Controls

// One selectable row in the sidebar, used for both groups and boxes.
Rectangle {
    id: row
    property string label: ""
    property int count: 0
    property bool selected: false
    // A quiet mark, for news that belongs to the page this row opens rather
    // than to the window.
    property bool marked: false
    // A word on the right that does something of its own, the same as the
    // one on a section heading. Empty for none.
    property string actionText: ""

    signal activated()
    signal actionRequested()
    signal contextRequested()
    signal revealRequested()

    onSelectedChanged: if (selected) revealRequested()

    height: 32
    color: selected ? Theme.colors.surfaceRaised
                    : (rowHover.hovered ? Theme.wash(Theme.colors.accent, 0.10)
                                        : "transparent")

    HoverHandler { id: rowHover }
    // A press on the word at the right is that word's, not the row's.
    TapHandler {
        onTapped: (eventPoint, button) => {
            if (actionLabel.visible) {
                var at = actionLabel.mapFromItem(row, eventPoint.position.x, eventPoint.position.y)
                if (at.x >= -6 && at.x <= actionLabel.width + 6)
                    return
            }
            row.activated()
        }
    }
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

    Rectangle {
        id: mark
        visible: row.marked
        anchors.right: parent.right
        anchors.rightMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        width: 6
        height: 6
        radius: 3
        color: Theme.colors.accent
    }

    Label {
        id: actionLabel
        objectName: "sidebarRowAction"
        visible: row.actionText !== ""
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: row.actionText
        color: actionHover.hovered ? Theme.colors.accent : Theme.colors.textMuted
        font.pixelSize: 16
        HoverHandler { id: actionHover }
        TapHandler { onTapped: row.actionRequested() }
    }

    Label {
        id: countLabel
        anchors.right: mark.visible ? mark.left : (actionLabel.visible ? actionLabel.left
                                                                        : parent.right)
        anchors.rightMargin: mark.visible || actionLabel.visible ? 8 : 12
        anchors.verticalCenter: parent.verticalCenter
        text: row.count > 0 ? row.count : ""
        font.pixelSize: 11
        color: Theme.colors.textMuted
    }
}
