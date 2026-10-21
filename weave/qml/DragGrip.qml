import QtQuick
import QtQuick.Controls

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
    // How many moves the held row was told about, for the trace. A row held
    // while the pointer went somewhere else hears of few of them.
    property int moves: 0
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
        // A row whose grip is not shown cannot be picked up, Favorites
        // among the boxes being the one that always stays first.
        enabled: grip.visible && grip.enabled
        target: null
        xAxis.enabled: false
        cursorShape: Qt.ClosedHandCursor
        // Not to be taken over. A list that may scroll takes a vertical drag
        // for itself once it is far enough, and then the list moved and the
        // row moved at once.
        grabPermissions: PointerHandler.CanTakeOverFromItems
                         | PointerHandler.CanTakeOverFromHandlersOfDifferentType
        onActiveChanged: {
            if (active) {
                grip.moves = 0
                grip.began(centroid.scenePosition.y, centroid.scenePressPosition.y)
            } else {
                App.traceMark("grip_let_go", { "moves": grip.moves,
                                               "y": Math.round(centroid.scenePosition.y) })
                grip.ended()
            }
        }
        onCentroidChanged: if (active) { grip.moves += 1; grip.carried(centroid.scenePosition.y) }
        // Who else took hold of the press, and when. A row let go of a few
        // milliseconds after it was taken was taken from, and this says by
        // which kind of thing.
        onGrabChanged: function (transition, point) {
            App.traceMark("grip_grab", { "transition": transition, "active": active,
                                         "x": Math.round(point.scenePosition.x),
                                         "y": Math.round(point.scenePosition.y) })
        }
        onCanceled: function (point) {
            App.traceMark("grip_canceled", { "y": Math.round(point.scenePosition.y) })
        }
    }

    // The hint, drawn in the row beside the dots rather than as the window's
    // usual bubble. That bubble is a popup of its own, and it closed the
    // moment a row was taken; with a real pointer that closing cancelled the
    // hold a few milliseconds in, and the page behind a window took the rest
    // of the drag. Measured from the trace: taken, cancelled after one move,
    // then the page dragging. A plain item coming and going does nothing to a
    // press.
    Rectangle {
        id: hint
        objectName: "dragGripHint"
        readonly property bool wanted: hover.hovered && !dragger.active
        parent: grip.row
        z: 100
        visible: wanted && hintDelay.done
        x: visible ? grip.mapToItem(grip.row, grip.width + 4, 0).x : 0
        y: visible ? grip.mapToItem(grip.row, 0, (grip.height - height) / 2).y : 0
        width: hintWords.implicitWidth + 14
        height: hintWords.implicitHeight + 10
        radius: 6
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border

        // As long as the usual bubble waits, so passing over the dots on the
        // way somewhere else does not flash it.
        Timer {
            id: hintDelay
            property bool done: false
            interval: 450
            running: hint.wanted && !done
            onTriggered: done = true
        }
        onWantedChanged: if (!wanted) hintDelay.done = false

        Label {
            id: hintWords
            textFormat: Text.PlainText
            anchors.centerIn: parent
            text: "Drag to change the order"
            color: Theme.colors.text
            font.pixelSize: 11
        }
    }
}
