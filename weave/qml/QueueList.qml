import QtQuick
import QtQuick.Controls

// The queue, drawn the one way. It is shown in two places, the popup over the
// music bar and the Now playing page, and both are the same list with the same
// handles on it, so a row dragged in one is already in its new place when the
// other is looked at. Two implementations of this drifted apart the moment one
// of them grew a feature, which is why there is only the one.
ListView {
    id: queued

    // What to close once a row has been jumped to, if anything. The popup
    // wants to get out of the way; the page is where the list lives and stays.
    // Handed down rather than read from out here, because a delegate is built
    // in its own scope and cannot see an id declared around it. Reaching for
    // one raises a reference error and the row silently does nothing.
    property var owner: null
    property int rowHeight: 44

    clip: true
    spacing: 2
    model: Audio.queue

    // A row picked up leaves a gap that the others slide into, rather than the
    // list jumping to its new shape at the drop.
    moveDisplaced: Transition {
        NumberAnimation { properties: "y"; duration: 140 }
    }
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    delegate: Rectangle {
        id: queuedRow
        // Which row is playing is read beside the list rather than carried in
        // it, so moving through the queue does not rebuild every row.
        readonly property bool playing: index === Audio.queueIndex
        required property var modelData
        required property int index
        width: queued.width
        height: queued.rowHeight
        radius: 5
        // The one playing stays marked, since the list holds everything rather
        // than only what is still to come.
        color: queuedRow.playing ? Theme.wash(Theme.colors.accent, 0.26)
                                 : (queuedHover.hovered
                                    ? Theme.wash(Theme.colors.accent, 0.14)
                                    : "transparent")

        HoverHandler { id: queuedHover }

        // Carried above its neighbours while it is held, and never taken out of
        // the list. Reparenting a row into the view is the other way to do this
        // and it fights the view's own placing of its rows.
        z: rowDrag.active ? 2 : 0
        opacity: rowDrag.active ? 0.85 : 1.0

        // Picked up and put down somewhere else. Where it landed is worked out
        // from how far it moved, since every row is the same height and the
        // list has no gaps in it.
        DragHandler {
            id: rowDrag
            objectName: "queueRowDrag"
            xAxis.enabled: false
            yAxis.enabled: true
            onActiveChanged: {
                if (active)
                    return
                var step = queuedRow.height + queued.spacing
                var slot = queuedRow.index * step
                var landed = Math.max(0, Math.min(
                    queued.count - 1,
                    queuedRow.index
                    + Math.round((queuedRow.y - slot) / step)))
                // Put back where the view wants it either way. A move rebuilds
                // the row from the new order, and a drop that landed where it
                // started must not leave the row sitting off its line.
                queuedRow.y = slot
                if (landed !== queuedRow.index)
                    Audio.moveInQueue(queuedRow.index, landed)
            }
        }

        // Skip straight to it rather than pressing next repeatedly. A press
        // that turned into a drag is not a press.
        MouseArea {
            anchors.fill: parent
            anchors.rightMargin: 26
            onClicked: {
                if (rowDrag.active)
                    return
                Audio.jumpTo(queuedRow.modelData.at)
                var holder = queuedRow.ListView.view.owner
                if (holder)
                    holder.close()
            }
        }

        // Out of the queue, and out of nothing else.
        Rectangle {
            objectName: "queueRowRemove"
            anchors.right: parent.right
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            height: 20
            radius: 10
            visible: queuedHover.hovered
            color: removeHover.hovered ? Theme.colors.live
                                       : Theme.colors.surfaceRaised

            HoverHandler { id: removeHover }
            Text {
                anchors.centerIn: parent
                text: "✕"
                font.pixelSize: 10
                color: Theme.colors.text
            }
            // A MouseArea rather than a TapHandler, because a handler does not
            // consume the press and the row underneath would take it too.
            MouseArea {
                anchors.fill: parent
                onClicked: Audio.removeFromQueue(queuedRow.modelData.at)
            }
        }

        Row {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 8

            RoundedImage {
                width: queued.rowHeight - 10
                height: queued.rowHeight - 10
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                visible: (queuedRow.modelData.thumbnail || "") !== ""
                source: queuedRow.modelData.thumbnail
                        ? queuedRow.modelData.thumbnail : ""
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - (queued.rowHeight + 12)
                spacing: 1
                Label {
                    width: parent.width
                    text: queuedRow.modelData.title
                    color: Theme.colors.text
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
                Label {
                    id: queuedArtist
                    // Only where the song carries an address for whoever made
                    // it, and never on the row that is playing, whose line is
                    // mostly the words "Playing now" rather than a name.
                    readonly property string leadsTo:
                        !queuedRow.playing && queuedRow.modelData.artistId
                        ? queuedRow.modelData.artistId : ""
                    width: parent.width
                    visible: (queuedRow.modelData.artist || "") !== ""
                             || queuedRow.playing
                    // The one playing says so, since the list holds what has
                    // been played as well as what has not.
                    text: queuedRow.playing
                          ? ("Playing now"
                             + ((queuedRow.modelData.artist || "") !== ""
                                ? "  ·  " + queuedRow.modelData.artist : ""))
                          : queuedRow.modelData.artist
                    color: queuedRow.playing ? Theme.colors.accent
                           : (leadsTo !== "" && queuedArtistHover.hovered
                              ? Theme.colors.text : Theme.colors.textMuted)
                    font.pixelSize: 10
                    font.weight: queuedRow.playing ? Font.DemiBold : Font.Normal
                    font.underline: leadsTo !== "" && queuedArtistHover.hovered
                    elide: Text.ElideRight

                    HoverHandler {
                        id: queuedArtistHover
                        enabled: queuedArtist.leadsTo !== ""
                        cursorShape: Qt.PointingHandCursor
                    }

                    // A MouseArea, because the row's own press sits underneath
                    // and a handler would not consume this one, so a press on
                    // the name would jump the queue as well as leave the page.
                    MouseArea {
                        enabled: queuedArtist.leadsTo !== ""
                        width: Math.min(queuedArtist.implicitWidth, parent.width)
                        height: parent.height
                        onClicked: App.openArtistChannel(queuedArtist.leadsTo)
                    }
                }
            }
        }
    }
}
