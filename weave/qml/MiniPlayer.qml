import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Always there once something is queued, whichever view is showing, because
// music that stops when you look at your feed is not music you can use.
Rectangle {
    id: bar
    visible: Audio.hasQueue
    height: visible ? 64 : 0
    // Read through Qt.color, since a theme colour is a string and asking a
    // string for r, g or b gives undefined, which Qt.rgba renders as black.
    readonly property color panel: Qt.color(Theme.colors.surface)
    color: Qt.rgba(panel.r, panel.g, panel.b, Theme.washed ? 0.72 : 1.0)

    function clock(seconds) {
        if (!seconds || seconds < 0)
            return "0:00"
        var m = Math.floor(seconds / 60)
        var s = Math.floor(seconds % 60)
        return m + ":" + (s < 10 ? "0" : "") + s
    }

    Rectangle {
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: Theme.colors.border
    }

    // A live stream has no length, so it gets a bar that means nothing and is
    // better left out.
    // Thicker under the pointer, so it can actually be hit and dragged rather
    // than needing a three pixel target.
    Item {
        id: scrubber
        visible: Audio.length > 0
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 14

        HoverHandler { id: scrubHover }

        Rectangle {
            id: progressTrack
            objectName: "musicScrubTrack"
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: scrubHover.hovered || scrubDrag.active ? 8 : 3
            color: Theme.colors.border
            Behavior on height { NumberAnimation { duration: 90 } }

            Rectangle {
                width: parent.width * Audio.position
                height: parent.height
                color: Theme.colors.accent
            }

            // Where each song in this track begins. A video that is really an
            // album carries them, and without them its bar is one long block
            // with no way to tell that it is six songs. Drawn over the played
            // part as well, in the ground colour, so a mark is a gap in the
            // bar at every point of it rather than something that disappears
            // as the bar catches up with it.
            //
            // The delegate cannot see anything declared around it, so what it
            // needs comes from the view it is in and from the model row.
            Repeater {
                model: Audio.chapters

                Rectangle {
                    objectName: "chapterMark"
                    required property var modelData

                    visible: modelData.at > 0 && modelData.at < 1
                    x: progressTrack.width * modelData.at
                    width: 2
                    height: progressTrack.height
                    color: Theme.colors.background
                }
            }

            Rectangle {
                visible: progressTrack.height > 3
                x: Math.max(0, parent.width * Audio.position - height / 2)
                anchors.verticalCenter: parent.verticalCenter
                width: 12
                height: 12
                radius: 6
                color: Theme.colors.accent
            }
        }

        // What sits under the pointer, named, the way YouTube and mpv both do
        // it. A bar with marks on it is only half the answer without this: the
        // marks say a song begins there and nothing says which one.
        //
        // Above the bar rather than below, which means outside this bar's own
        // height. Nothing clips it and the bar is drawn over the grid already,
        // so it simply hangs over what is behind it.
        Rectangle {
            id: peek
            objectName: "chapterPeek"

            readonly property real along: scrubber.width > 0
                ? Math.max(0, Math.min(1, scrubHover.point.position.x / scrubber.width))
                : 0
            // Asked of the player rather than worked out here, so the name
            // under the pointer and the name under the title come from one
            // rule and cannot disagree about the same second. The list is
            // named as well as asked, because a binding on a function call
            // alone would never be evaluated again on a change of track.
            readonly property var songs: Audio.chapters
            readonly property string song: peek.songs.length > 0
                                           ? Audio.songAt(peek.along) : ""
            readonly property string when: bar.clock(peek.along * Audio.length)

            visible: scrubHover.hovered && Audio.length > 0
            z: 20
            width: Math.max(peekWhen.implicitWidth, peekSong.implicitWidth) + 16
            height: (peek.song !== "" ? peekSong.implicitHeight + 2 : 0)
                    + peekWhen.implicitHeight + 10
            // Centred on the pointer, and kept inside the window at both ends
            // rather than hanging off the edge at the start of a track.
            x: Math.max(4, Math.min(scrubber.width - width - 4,
                                    scrubHover.point.position.x - width / 2))
            y: -height - 6
            radius: 6
            color: Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border

            Column {
                anchors.centerIn: parent
                spacing: 2

                Label {
                    id: peekSong
                    objectName: "chapterPeekSong"
                    visible: peek.song !== ""
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: peek.song
                    color: Theme.colors.text
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }
                Label {
                    id: peekWhen
                    objectName: "chapterPeekTime"
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: peek.when
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                }
            }
        }

        TapHandler {
            onTapped: function (point) { Audio.seek(point.position.x / scrubber.width) }
        }
        DragHandler {
            id: scrubDrag
            target: null
            yAxis.enabled: false
            onCentroidChanged: if (active) Audio.seek(centroid.position.x / scrubber.width)
        }
    }

    Popup {
        id: upNext
        objectName: "upNext"
        y: -height - 8
        x: parent.width - width - 12
        width: 340
        height: Math.min(360, 46 + queued.count * 46)
        padding: 8
        modal: false
        background: Rectangle {
            radius: 8
            color: Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border
        }

        Column {
            anchors.fill: parent
            spacing: 6

            Label {
                text: "QUEUE  ·  " + Audio.queue.length
                color: Theme.colors.textMuted
                font.pixelSize: 10
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }

            ListView {
                id: queued
                objectName: "queuedList"
                // Handed to the rows, because a delegate is built in its own
                // scope and cannot see an id declared out here. Reaching for
                // one raises a reference error and the row does nothing.
                property var owner: upNext
                width: parent.width
                height: parent.height - 22
                clip: true
                spacing: 2
                model: Audio.queue
                // A row picked up leaves a gap that the others slide into,
                // rather than the list jumping to its new shape at the drop.
                moveDisplaced: Transition {
                    NumberAnimation { properties: "y"; duration: 140 }
                }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    id: queuedRow
                    // Which row is playing is read beside the list rather
                    // than carried in it, so moving through the queue does
                    // not rebuild every row.
                    readonly property bool playing: index === Audio.queueIndex
                    required property var modelData
                    required property int index
                    width: queued.width
                    height: 44
                    radius: 5
                    // The one playing stays marked, since the list holds
                    // everything rather than only what is still to come.
                    color: queuedRow.playing ? Theme.colors.surfaceRaised
                                                       : (queuedHover.hovered
                                                          ? Theme.colors.surface
                                                          : "transparent")

                    HoverHandler { id: queuedHover }

                    // Carried above its neighbours while it is held, and
                    // never taken out of the list. Reparenting a row into the
                    // view is the other way to do this and it fights the
                    // view's own placing of its rows.
                    z: rowDrag.active ? 2 : 0
                    opacity: rowDrag.active ? 0.85 : 1.0

                    // Picked up and put down somewhere else. Where it landed
                    // is worked out from how far it moved, since every row is
                    // the same height and the list has no gaps in it.
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
                            // Put back where the view wants it either way. A
                            // move rebuilds the row from the new order, and a
                            // drop that landed where it started must not
                            // leave the row sitting off its line.
                            queuedRow.y = slot
                            if (landed !== queuedRow.index)
                                Audio.moveInQueue(queuedRow.index, landed)
                        }
                    }

                    // Skip straight to it rather than pressing next repeatedly.
                    // A press that turned into a drag is not a press.
                    MouseArea {
                        anchors.fill: parent
                        anchors.rightMargin: 26
                        onClicked: {
                            if (rowDrag.active)
                                return
                            Audio.jumpTo(queuedRow.modelData.at)
                            queuedRow.ListView.view.owner.close()
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
                            text: "\u2715"
                            font.pixelSize: 10
                            color: Theme.colors.text
                        }
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
                        width: 34
                        height: 34
                        radius: 4
                        anchors.verticalCenter: parent.verticalCenter
                        visible: (modelData.thumbnail || "") !== ""
                        source: modelData.thumbnail ? modelData.thumbnail : ""
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 46
                        spacing: 1
                        Label {
                            width: parent.width
                            text: modelData.title
                            color: Theme.colors.text
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                        Label {
                            width: parent.width
                            visible: (modelData.artist || "") !== "" || queuedRow.playing
                            // The one playing says so, since the list holds
                            // what has been played as well as what has not.
                            text: queuedRow.playing
                                  ? ("Playing now"
                                     + ((modelData.artist || "") !== ""
                                        ? "  ·  " + modelData.artist : ""))
                                  : modelData.artist
                            color: queuedRow.playing ? Theme.colors.accent
                                                     : Theme.colors.textMuted
                            font.pixelSize: 10
                            font.weight: queuedRow.playing ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                    }
                    }
                }
            }
        }
    }

    // Inset by the same amount above and below, so the row sits in the middle
    // of the bar. Room left for the scrub track on the top side alone pushed
    // the row down and left a band of empty bar over it. Ten clears the track
    // at its thickest and the handle on it, and the artwork fills the forty
    // four that are left.
    RowLayout {
        anchors.fill: parent
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 12

        RoundedImage {
            objectName: "nowPlayingArt"
            Layout.preferredWidth: 44
            Layout.preferredHeight: 44
            radius: 6
            visible: (Audio.track.thumbnail || "") !== ""
            source: Audio.track.thumbnail ? Audio.track.thumbnail : ""
        }

        ColumnLayout {
            Layout.preferredWidth: 240
            Layout.maximumWidth: 320
            spacing: 1

            Label {
                Layout.fillWidth: true
                text: Audio.track.title ? Audio.track.title : ""
                color: Theme.colors.text
                font.pixelSize: 12
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Label {
                objectName: "musicSecondLine"
                Layout.fillWidth: true
                // Which song of it is playing, when the track is really
                // several. That is the more useful of the two by a distance
                // while it is true, and the name above already says what the
                // whole thing is, so it takes the line rather than crowding
                // in beside the artist.
                text: {
                    if (Audio.loading)
                        return "loading"
                    if (Audio.currentChapter !== "")
                        return Audio.currentChapter
                    return Audio.track.artist ? Audio.track.artist : ""
                }
                color: Audio.currentChapter !== "" && !Audio.loading
                       ? Theme.colors.text : Theme.colors.textMuted
                font.pixelSize: 11
                elide: Text.ElideRight
            }
        }

        // Kept or not. Grey until it is one of the kept ones, then red.
        Item {
            objectName: "favoriteHeart"
            Layout.preferredWidth: 26
            Layout.preferredHeight: 26
            Layout.alignment: Qt.AlignVCenter
            visible: (Audio.track.key || "") !== ""

            Text {
                id: heart
                objectName: "favoriteHeartMark"
                anchors.centerIn: parent
                text: "♥"
                font.pixelSize: 17
                color: App.playingIsFavorite ? Theme.colors.live
                       : (heartHover.hovered ? Theme.colors.text
                                             : Theme.colors.watchedDim)

                Behavior on color {
                    ColorAnimation { duration: 120 }
                }
            }

            HoverHandler { id: heartHover }
            MouseArea {
                anchors.fill: parent
                onClicked: App.toggleFavorite()
            }
        }

        FlatButton {
            text: "◀◀"
            Layout.preferredWidth: 42
            onClicked: Audio.previous()
        }
        FlatButton {
            // Fixed, because the pause and play marks are different widths and
            // everything to the right of it used to shuffle sideways.
            text: Audio.playing ? "❚❚" : "▶"
            accent: true
            Layout.preferredWidth: 46
            onClicked: Audio.toggle()
        }
        FlatButton {
            text: "▶▶"
            Layout.preferredWidth: 42
            onClicked: Audio.next()
        }

        Label {
            visible: Audio.length > 0
            text: bar.clock(Audio.elapsed) + " / " + bar.clock(Audio.length)
            color: Theme.colors.textMuted
            font.pixelSize: 11
        }
        Label {
            visible: Audio.length === 0
            text: "live"
            color: Theme.colors.live
            font.pixelSize: 11
            font.bold: true
        }

        Item { Layout.fillWidth: true }

        FlatButton {
            text: "Shuffle"
            accent: Audio.shuffle
            onClicked: Audio.setShuffle(!Audio.shuffle)
        }
        FlatButton {
            // Off, the whole queue, or the one track. A queue that repeats and
            // a track that repeats are different wants.
            text: Audio.repeatLabel
            accent: Audio.repeat > 0
            Layout.preferredWidth: 92
            onClicked: Audio.cycleRepeat()
        }
        FlatButton {
            // Two things playing at once is never wanted, but it is a choice.
            text: "Pause for video"
            accent: Audio.autoPause
            onClicked: Audio.setAutoPause(!Audio.autoPause)
        }

        Slider {
            id: volume
            // Long enough that a small change is a small movement.
            Layout.preferredWidth: 170
            from: 0
            to: 100
            value: Audio.volume
            onMoved: Audio.setVolume(value)

            // A notch is five, so it can be tuned without aiming.
            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                property real carried: 0
                onWheel: function (event) {
                    carried += event.angleDelta.y
                    while (carried >= 120) { carried -= 120; Audio.nudgeVolume(1) }
                    while (carried <= -120) { carried += 120; Audio.nudgeVolume(-1) }
                }
            }
        }

        FlatButton {
            text: "Queue"
            enabled: Audio.queue.length > 0
            onClicked: upNext.open()
        }

        FlatButton { text: "✕"; onClicked: Audio.stop() }
    }
}
