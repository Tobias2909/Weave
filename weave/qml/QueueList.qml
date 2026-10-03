import QtQuick
import QtQuick.Controls

// The queue, drawn the one way. It is shown in two places, the popup over the
// music bar and the Now playing page, and both are the same list with the same
// handles on it, so a row dragged in one is already in its new place when the
// other is looked at. Two implementations of this drifted apart the moment one
// of them grew a feature, which is why there is only the one.
//
// Wide enough, it draws the companion's rows: a big picture, the title on two
// lines, what has been played dimmed. Narrow, as in the popup, it draws small
// rows, so the popup still shows more than a handful. Either way a row is
// carried the same way, by a copy that follows the pointer.
ListView {
    id: queued

    // What to close once a row has been jumped to, if anything. The popup
    // wants to get out of the way; the page is where the list lives and stays.
    // Handed down rather than read from out here, because a delegate is built
    // in its own scope and cannot see an id declared around it. Reaching for
    // one raises a reference error and the row silently does nothing.
    property var owner: null
    // Small rows, for a narrow list.
    property bool compact: width < 400
    readonly property int rowHeight: compact ? 44 : 88

    // A right press on a row, for the window's menu of its boxes.
    signal menuRequested(string key)

    clip: true
    spacing: compact ? 2 : 4
    model: Audio.queue
    // Scrolled by the wheel, the bar, or by carrying a row to an edge, never
    // by dragging, so a row taken a little off its grip moves the row rather
    // than the list.
    acceptedButtons: Qt.NoButton
    // A row held while the list scrolls must outlive scrolling out of sight,
    // or the drag ends with nothing to end it on.
    cacheBuffer: 100000
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    // The one playing in sight whenever it changes, unless a row is being
    // carried, when the list is the hand's to move.
    readonly property int playingAt: Audio.queueIndex
    onPlayingAtChanged: if (playingAt >= 0 && !rowOrder.carrying)
                            positionViewAtIndex(playingAt, ListView.Contain)

    delegate: Rectangle {
        id: queuedRow
        objectName: "queueSongRow"
        // Which row is playing is read beside the list rather than carried in
        // it, so moving through the queue does not rebuild every row.
        readonly property bool playing: index === Audio.queueIndex
        readonly property bool played: Audio.queueIndex >= 0 && index < Audio.queueIndex
        readonly property bool compact: queued.compact
        required property var modelData
        required property int index
        width: queued.width - (compact ? 0 : 12)
        height: queued.rowHeight
        radius: compact ? 5 : 7
        // The one playing stays marked, since the list holds everything rather
        // than only what is still to come.
        color: queuedRow.playing ? Theme.wash(Theme.colors.accent, 0.26)
                                 : (queuedHover.hovered
                                    ? Theme.wash(Theme.colors.accent, 0.14)
                                    : "transparent")
        opacity: rowOrder.from === index ? 0.35 : (played && !compact ? 0.5 : 1.0)

        HoverHandler { id: queuedHover }

        // Skip straight to it rather than pressing next repeatedly, or offer
        // its boxes. Under everything else on the row, so the cross and the
        // name still take their own presses.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onClicked: function (mouse) {
                if (mouse.button === Qt.RightButton) {
                    var key = queuedRow.modelData.key || ""
                    if (key.indexOf("yt:") === 0)
                        queued.menuRequested(key)
                    return
                }
                Audio.jumpTo(queuedRow.modelData.at)
                var holder = queuedRow.ListView.view.owner
                if (holder)
                    holder.close()
            }
        }

        DragGrip {
            x: queuedRow.compact ? 0 : 4
            anchors.verticalCenter: parent.verticalCenter
            row: queuedRow
            onBegan: (y, pressY) => rowOrder.begin(queuedRow.index,
                                                   queuedRow.modelData.title, y, pressY)
            onCarried: (y) => rowOrder.carry(y)
            onEnded: rowOrder.finish()
        }

        // The picture. A square cover gets a square box in the middle of the
        // wide one, on a ground of its own, rather than being cropped to a
        // band of itself.
        Rectangle {
            id: pictureSlot
            x: queuedRow.compact ? 20 : 26
            anchors.verticalCenter: parent.verticalCenter
            width: queuedRow.compact ? queued.rowHeight - 10 : 136
            height: queuedRow.compact ? queued.rowHeight - 10 : 76
            radius: queuedRow.compact ? 4 : 6
            color: !queuedRow.compact && rowPicture.width < width
                   ? Theme.colors.surfaceRaised : "transparent"
            visible: (queuedRow.modelData.thumbnail || "") !== ""

            RoundedImage {
                id: rowPicture
                anchors.centerIn: parent
                height: parent.height
                width: queuedRow.compact || rowPicture.ratio === 0 || rowPicture.ratio > 1.5
                       ? parent.width : Math.round(parent.height * rowPicture.ratio)
                radius: parent.radius
                source: queuedRow.modelData.thumbnail ? queuedRow.modelData.thumbnail : ""
            }

            Rectangle {
                visible: !queuedRow.compact && (queuedRow.modelData.duration || "") !== ""
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 4
                width: rowLength.implicitWidth + 10
                height: 17
                radius: 4
                color: "#c0000000"

                Label {
                    id: rowLength
                    anchors.centerIn: parent
                    text: queuedRow.modelData.duration || ""
                    color: "#ffffff"
                    font.pixelSize: 10
                }
            }
        }

        Column {
            anchors.left: pictureSlot.right
            anchors.leftMargin: queuedRow.compact ? 8 : 12
            anchors.right: parent.right
            anchors.rightMargin: queuedRow.compact ? 26 : 34
            anchors.verticalCenter: parent.verticalCenter
            spacing: queuedRow.compact ? 1 : 3

            Label {
                visible: queuedRow.playing && !queuedRow.compact
                text: "▶  PLAYING"
                color: Theme.colors.accent
                font.pixelSize: 10
                font.letterSpacing: 1.1
                font.weight: Font.DemiBold
            }

            Label {
                width: parent.width
                text: queuedRow.modelData.title
                color: Theme.colors.text
                font.pixelSize: queuedRow.compact ? 11 : 13
                font.weight: queuedRow.playing && !queuedRow.compact ? Font.DemiBold
                                                                     : Font.Normal
                wrapMode: queuedRow.compact ? Text.NoWrap : Text.Wrap
                maximumLineCount: queuedRow.compact ? 1 : 2
                elide: Text.ElideRight
            }

            Label {
                id: queuedArtist
                // Whoever made it: an artist of the music service, or for a
                // video queued from the recommendations its YouTube channel.
                // Never on the small row that is playing, whose line is mostly
                // the words "Playing now" rather than a name.
                readonly property string artistTo: queuedRow.modelData.artistId || ""
                readonly property string channelTo: queuedRow.modelData.channelId || ""
                readonly property bool saysPlaying: queuedRow.compact && queuedRow.playing
                readonly property bool leads: !saysPlaying
                                              && (artistTo !== "" || channelTo !== "")
                width: parent.width
                visible: (queuedRow.modelData.artist || "") !== "" || saysPlaying
                // The small row playing says so, since the list holds what has
                // been played as well as what has not.
                text: saysPlaying
                      ? ("Playing now"
                         + ((queuedRow.modelData.artist || "") !== ""
                            ? "  ·  " + queuedRow.modelData.artist : ""))
                      : (queuedRow.modelData.artist || "")
                color: saysPlaying ? Theme.colors.accent
                       : (leads && queuedArtistHover.hovered
                          ? Theme.colors.text : Theme.colors.textMuted)
                font.pixelSize: queuedRow.compact ? 10 : 11
                font.weight: saysPlaying ? Font.DemiBold : Font.Normal
                font.underline: leads && queuedArtistHover.hovered
                elide: Text.ElideRight

                // A MouseArea, because the row's own press sits underneath
                // and a handler would not consume this one, so a press on
                // the name would jump the queue as well as leave the page.
                // Only as wide as the words.
                MouseArea {
                    enabled: queuedArtist.leads
                    width: Math.min(queuedArtist.implicitWidth, parent.width)
                    height: parent.height
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (queuedArtist.artistTo !== "")
                            App.openArtistChannel(queuedArtist.artistTo)
                        else
                            App.openChannel("yt:" + queuedArtist.channelTo)
                    }

                    HoverHandler { id: queuedArtistHover }
                }
            }
        }

        // Out of the queue, and out of nothing else.
        Label {
            objectName: "queueRowRemove"
            visible: queuedHover.hovered
            anchors.right: parent.right
            anchors.rightMargin: queuedRow.compact ? 8 : 10
            anchors.verticalCenter: parent.verticalCenter
            text: "✕"
            color: removeHover.hovered ? Theme.colors.text : Theme.colors.textMuted
            font.pixelSize: queuedRow.compact ? 11 : 13

            HoverHandler { id: removeHover; cursorShape: Qt.PointingHandCursor }
            // A MouseArea rather than a TapHandler, because a handler does not
            // consume the press and the row underneath would take it too.
            MouseArea {
                anchors.fill: parent
                anchors.margins: -6
                onClicked: Audio.removeFromQueue(queuedRow.modelData.at)
            }
        }
    }

    // A place in the list as shown is a place in the play order, which is
    // what the player moves by, shuffled or not.
    DragOrder {
        id: rowOrder
        objectName: "queueOrder"
        parent: queued
        list: queued
        rowHeight: queued.rowHeight + queued.spacing
        rowCount: queued.count
        onDropped: (from, to) => Audio.moveInQueue(from, to)
    }
}
