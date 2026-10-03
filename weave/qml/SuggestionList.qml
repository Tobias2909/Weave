import QtQuick
import QtQuick.Controls

// What to search for, offered under a search box while it is typed in. The
// box keeps the keyboard the whole time: the arrows move through the list,
// return takes the one picked or the words as typed, and escape puts the list
// away before it empties the box.
Popup {
    id: list

    // The box it hangs under, and which suggestions are its own.
    property Item field: null
    property string where: "youtube"
    // The row the arrows are on, -1 for the words as typed.
    property int picked: -1
    signal chosen(string words)

    readonly property var items: App.suggestionsFor === list.where ? App.suggestions : []

    parent: field
    x: 0
    y: field ? field.height + 4 : 0
    width: field ? Math.max(field.width, 340) : 340
    padding: 4
    modal: false
    focus: false
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    background: Rectangle {
        radius: 8
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border
    }

    // Moved by the arrows, and wrapping through the words as typed. Says
    // whether it moved, so the box can let the key do its usual thing when
    // there is no list.
    function move(by) {
        if (!list.opened || list.items.length === 0)
            return false
        var count = list.items.length + 1
        list.picked = ((list.picked + 1 + by) % count + count) % count - 1
        return true
    }

    function takePicked() {
        if (!list.opened || list.picked < 0 || list.picked >= list.items.length)
            return false
        list.chosen(list.items[list.picked])
        return true
    }

    // A Popup owns its own visibility, so it is opened and closed from here
    // rather than bound, which would be a loop.
    Connections {
        target: App
        function onSuggestionsChanged() {
            list.picked = -1
            if (list.items.length > 0 && list.field && list.field.activeFocus)
                list.open()
            else
                list.close()
        }
    }

    contentItem: Column {
        spacing: 2

        Repeater {
            model: list.items

            Rectangle {
                required property var modelData
                required property int index
                objectName: "suggestion" + index
                width: list.availableWidth
                height: 30
                radius: 6
                color: index === list.picked
                       ? Theme.wash(Theme.colors.accent, 0.26)
                       : (rowHover.hovered ? Theme.wash(Theme.colors.accent, 0.14)
                                           : "transparent")

                HoverHandler { id: rowHover }

                Label {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData
                    color: Theme.colors.text
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: list.chosen(modelData)
                }
            }
        }
    }
}
