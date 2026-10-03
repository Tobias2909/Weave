import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Beside whatever mpv is playing: what YouTube would put next to it on its
// watch page, and mpv's own playlist. A tile pressed goes on the end of that
// playlist; the playlist itself is reordered, skipped through and cut here,
// and every change is mpv's, so what is shown is always what mpv holds.
Item {
    id: view

    // The menu of a tile and the name for a kept queue live in the window,
    // which owns the popups, so they are asked for from here.
    signal cardMenuRequested(int index, string key)
    signal queueMenuRequested(string key)
    signal saveQueueRequested()

    readonly property Item body: content
    // The queue takes about a quarter of the page, never so much that its
    // rows run on past their words, never so little that a title is cut short.
    readonly property int queueWidth: Math.max(420, Math.min(500, Math.round(width * 0.27)))
    readonly property int gap: 12
    readonly property int smallestTile: 250

    Item {
        id: content
        anchors.fill: parent

        // ---- what is beside the song ----------------------------------------

        ColumnLayout {
            id: side
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: queuePanel.left
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 14
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    visible: App.companionNow !== ""
                    text: "Recommended for"
                    color: Theme.colors.text
                    font.pixelSize: 13
                }

                Label {
                    objectName: "companionNow"
                    Layout.fillWidth: true
                    text: App.companionNow !== "" ? App.companionNow : "Companion"
                    color: Theme.colors.text
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                BusyWord {
                    visible: App.companionBusy
                    text: "Asking YouTube"
                }

                FlatButton {
                    objectName: "companionRefresh"
                    visible: App.companionChips.length > 1
                    text: "Refresh"
                    onClicked: App.refreshCompanion()
                }
            }

            Flow {
                objectName: "companionChips"
                Layout.fillWidth: true
                spacing: 8

                Repeater {
                    model: App.companionChips

                    Rectangle {
                        id: chip
                        required property var modelData
                        height: 30
                        radius: 15
                        width: chipWords.implicitWidth + 28
                        color: modelData.chosen ? Theme.wash(Theme.colors.accent, 0.26)
                               : (chipHover.hovered ? Theme.wash(Theme.colors.accent, 0.16)
                                                    : Theme.colors.surfaceRaised)
                        border.width: 1
                        border.color: modelData.chosen || chipHover.hovered
                                      ? Theme.wash(Theme.colors.accent, 0.6) : Theme.colors.border

                        Label {
                            id: chipWords
                            anchors.centerIn: parent
                            text: chip.modelData.label
                            color: Theme.colors.text
                            font.pixelSize: 12
                            font.weight: chip.modelData.chosen ? Font.DemiBold : Font.Normal
                        }

                        HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: App.chooseCompanionChip(chip.modelData.label) }
                    }
                }
            }

            // Said on a raised ground, since a muted line over the bright
            // corner of a gradient theme cannot be read.
            Rectangle {
                objectName: "companionNote"
                visible: App.companionNote !== ""
                Layout.fillWidth: true
                Layout.preferredHeight: noteWords.implicitHeight + 16
                radius: 6
                color: Theme.colors.surfaceRaised
                border.width: 1
                border.color: Theme.colors.border

                Label {
                    id: noteWords
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 10
                    text: App.companionNote
                    color: Theme.colors.text
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }

            GridView {
                id: tiles
                objectName: "companionTiles"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: App.companionCards
                readonly property int columns:
                    Math.max(2, Math.floor((width + view.gap) / (view.smallestTile + view.gap)))
                cellWidth: Math.floor(width / columns)
                cellHeight: Math.round((cellWidth - view.gap) * 9 / 16) + view.gap
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Item {
                    id: cell
                    required property var modelData
                    required property int index
                    width: tiles.cellWidth
                    height: tiles.cellHeight

                    VideoTile {
                        width: cell.width - view.gap
                        height: cell.height - view.gap
                        title: cell.modelData.title
                        channel: cell.modelData.channel
                        picture: cell.modelData.picture
                        duration: cell.modelData.duration
                        queued: cell.modelData.queued
                        channelLeads: cell.modelData.channelId !== ""
                        onChannelChosen: App.openChannel("yt:" + cell.modelData.channelId)
                        onChosen: App.companionAdd(cell.index)
                        onAskedFor: view.cardMenuRequested(cell.index, cell.modelData.key)
                    }
                }
            }
        }

        SmoothScroll {
            flickable: tiles
            step: tiles.cellHeight * App.scrollRowsPerNotch
        }

        // ---- mpv's playlist ---------------------------------------------------

        Rectangle {
            id: queuePanel
            objectName: "companionQueuePanel"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.margins: 14
            width: view.queueWidth
            radius: 10
            color: Theme.wash(Theme.colors.surface, 0.78)
            border.width: 1
            border.color: Theme.colors.border

            RowLayout {
                id: queueHead
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 8

                Label {
                    text: ("Queue in mpv" + (App.companionQueue.length > 0
                                             ? "  ·  " + App.companionQueue.length : ""))
                          .toUpperCase()
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    font.letterSpacing: 1.2
                    font.weight: Font.DemiBold
                }

                Item { Layout.fillWidth: true }

                Label {
                    objectName: "companionLoops"
                    visible: App.companionLooping
                    text: "Goes round (F9)"
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                }

                FlatButton {
                    objectName: "companionSaveQueue"
                    enabled: App.companionQueue.length > 0
                    text: "Save as box"
                    onClicked: view.saveQueueRequested()
                }

                FlatButton {
                    objectName: "companionClearQueue"
                    visible: App.companionQueue.length > 1
                    text: "Clear"
                    hint: "Take everything out of mpv's queue except the video playing"
                    onClicked: App.companionClear()
                }
            }

            ListView {
                id: queueList
                objectName: "companionQueue"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: queueHead.bottom
                anchors.bottom: parent.bottom
                anchors.margins: 8
                anchors.topMargin: 10
                clip: true
                spacing: 4
                model: App.companionQueue
                // Scrolled by the wheel, the bar, or by carrying a row to an
                // edge, never by dragging, so a row taken a little off its
                // grip moves the row rather than the list.
                acceptedButtons: Qt.NoButton
                // A row held while the list scrolls must outlive scrolling out
                // of sight, or the drag ends with nothing to end it on.
                cacheBuffer: 100000
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                // The one playing in sight whenever it changes.
                readonly property int playingAt: {
                    for (var i = 0; i < App.companionQueue.length; i++)
                        if (App.companionQueue[i].playing)
                            return i
                    return -1
                }
                onPlayingAtChanged: if (playingAt >= 0 && !queueOrder.carrying)
                                        positionViewAtIndex(playingAt, ListView.Contain)

                delegate: Rectangle {
                    id: queueRow
                    objectName: "companionQueueRow"
                    required property var modelData
                    required property int index
                    width: queueList.width - 12
                    height: 88
                    radius: 7
                    color: modelData.playing ? Theme.wash(Theme.colors.accent, 0.26)
                           : (rowHover.hovered ? Theme.wash(Theme.colors.accent, 0.14)
                                               : "transparent")
                    opacity: queueOrder.from === index ? 0.35 : (modelData.played ? 0.5 : 1.0)

                    HoverHandler { id: rowHover }

                    // A press on the row plays it, a right press offers its
                    // boxes. Under everything else on the row, so the cross
                    // and the channel's name still take their own presses.
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function (mouse) {
                            if (mouse.button === Qt.RightButton) {
                                if (queueRow.modelData.key !== "")
                                    view.queueMenuRequested(queueRow.modelData.key)
                            } else {
                                App.companionJump(queueRow.index)
                            }
                        }
                    }

                    DragGrip {
                        x: 4
                        anchors.verticalCenter: parent.verticalCenter
                        row: queueRow
                        onBegan: (y, pressY) => queueOrder.begin(queueRow.index,
                                                                 queueRow.modelData.title,
                                                                 y, pressY)
                        onCarried: (y) => queueOrder.carry(y)
                        onEnded: queueOrder.finish()
                    }

                    RoundedImage {
                        id: queuePicture
                        x: 26
                        anchors.verticalCenter: parent.verticalCenter
                        width: 136
                        height: 76
                        radius: 6
                        source: queueRow.modelData.picture
                    }

                    Rectangle {
                        visible: queueRow.modelData.duration !== ""
                        anchors.right: queuePicture.right
                        anchors.bottom: queuePicture.bottom
                        anchors.margins: 4
                        width: queueDuration.implicitWidth + 10
                        height: 17
                        radius: 4
                        color: "#c0000000"

                        Label {
                            id: queueDuration
                            anchors.centerIn: parent
                            text: queueRow.modelData.duration
                            color: "#ffffff"
                            font.pixelSize: 10
                        }
                    }

                    Column {
                        anchors.left: queuePicture.right
                        anchors.leftMargin: 12
                        anchors.right: parent.right
                        anchors.rightMargin: 34
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3

                        Label {
                            visible: queueRow.modelData.playing
                            text: "▶  PLAYING"
                            color: Theme.colors.accent
                            font.pixelSize: 10
                            font.letterSpacing: 1.1
                            font.weight: Font.DemiBold
                        }

                        Label {
                            width: parent.width
                            text: queueRow.modelData.title
                            color: Theme.colors.text
                            font.pixelSize: 13
                            font.weight: queueRow.modelData.playing ? Font.DemiBold : Font.Normal
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }

                        Label {
                            id: queueChannel
                            readonly property bool leads: queueRow.modelData.channelId !== ""
                            width: parent.width
                            visible: queueRow.modelData.channel !== ""
                            text: queueRow.modelData.channel
                            color: leads && queueChannelHover.hovered ? Theme.colors.text
                                                                       : Theme.colors.textMuted
                            font.pixelSize: 11
                            font.underline: leads && queueChannelHover.hovered
                            elide: Text.ElideRight

                            // Only as wide as the words, like the name on a tile.
                            MouseArea {
                                enabled: queueChannel.leads
                                width: Math.min(queueChannel.implicitWidth, queueChannel.width)
                                height: parent.height
                                cursorShape: Qt.PointingHandCursor
                                onClicked: App.openChannel("yt:" + queueRow.modelData.channelId)

                                HoverHandler { id: queueChannelHover }
                            }
                        }
                    }

                    Label {
                        objectName: "companionQueueRemove"
                        visible: rowHover.hovered
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: "✕"
                        color: removeHover.hovered ? Theme.colors.text : Theme.colors.textMuted
                        font.pixelSize: 13

                        HoverHandler { id: removeHover; cursorShape: Qt.PointingHandCursor }
                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -6
                            onClicked: App.companionRemove(queueRow.index)
                        }
                    }
                }

                DragOrder {
                    id: queueOrder
                    objectName: "companionQueueOrder"
                    parent: queueList
                    list: queueList
                    rowHeight: 92
                    rowCount: queueList.count
                    onDropped: (from, to) => App.companionMove(from, to)
                }
            }

            Label {
                visible: App.companionQueue.length === 0
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: queueHead.bottom
                anchors.margins: 16
                text: App.mpvRunning ? "mpv's playlist is empty."
                                     : "mpv is not running. A press on a video starts it."
                color: Theme.colors.textMuted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
        }

        // Two rows a notch, the same as the queue beside the music. Half a
        // row, which is what the grid's own measure came to here, took a
        // dozen notches to get past a handful of videos.
        SmoothScroll {
            flickable: queueList
            step: 2 * 92
        }
    }
}
