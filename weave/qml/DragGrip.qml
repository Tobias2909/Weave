import QtQuick

// Six dots that say "this can be picked up", at the start of a row whose
// order can be changed. The row itself is never moved: the list it sits in
// places its rows, and a row moved under it fought that placing and smeared
// as the list scrolled. The grip only says where the pointer is, and the
// DragOrder over the list draws what is carried and where it will land.
//
// The dots are only the sign. The whole row is what is taken hold of, so a
// press that misses them by a little picks the row up rather than dragging
// the list under it, which read as the page moving instead of the playlist.
// A press that does not move is left alone, so the boxes in the row still
// tick and the name still does what it does.
Item {
    id: grip

    // What can be taken hold of. The row the grip sits in, unless told
    // otherwise.
    property Item row: parent
    readonly property bool active: dragger.active
    // Where the pointer is, in the window, while the row is held. A carry
    // begins a little way from the press, so where the press was comes too.
    signal began(real sceneY, real pressSceneY)
    signal carried(real sceneY)
    signal ended()

    width: 18
    height: 24

    Grid {
        anchors.centerIn: parent
        columns: 2
        spacing: 3

        Repeater {
            model: 6
            Rectangle {
                width: 3
                height: 3
                radius: 1.5
                color: (hover.hovered || dragger.active) ? Theme.colors.text
                                                         : Theme.colors.textMuted
            }
        }
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.OpenHandCursor
    }

    // Handling the whole row. A box or the name that takes a press still
    // takes it, and this still hears it, so a press that does not move is a
    // tick or a click as before, and one that moves is taken from them. Over
    // the row in an item of its own instead, it swallowed every click.
    DragHandler {
        id: dragger
        objectName: "dragGripHandler"
        parent: grip.row
        target: null
        xAxis.enabled: false
        cursorShape: Qt.ClosedHandCursor
        // Not to be taken over. A list that may scroll takes a vertical drag
        // for itself once it is far enough, and then the list moved and the
        // row moved at once.
        grabPermissions: PointerHandler.CanTakeOverFromItems
                         | PointerHandler.CanTakeOverFromHandlersOfDifferentType
        onActiveChanged: {
            if (active)
                grip.began(centroid.scenePosition.y, centroid.scenePressPosition.y)
            else
                grip.ended()
        }
        onCentroidChanged: if (active) grip.carried(centroid.scenePosition.y)
    }

    HintBubble {
        parent: grip
        shown: hover.hovered && !dragger.active
        words: "Drag to change the order"
    }
}
