import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Always there once something is queued, whichever view is showing, because
// music that stops when you look at your feed is not music you can use.
Rectangle {
    id: bar
    visible: Audio.hasQueue
    height: visible ? 64 : 0

    // Out of sight while the picture fills the screen and nothing has moved
    // for a while. Faded and switched off rather than hidden: hiding takes
    // its height with it, and the bar coming back would jump into place
    // instead of arriving. Switched off so that a bar nobody can see cannot
    // take a press meant for the picture behind it.
    property bool dimmed: false
    opacity: dimmed ? 0 : 1
    enabled: !dimmed
    Behavior on opacity {
        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
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
        // Nothing to scrub through on a broadcast. It is not that its length
        // is unknown, it is that it does not have one.
        visible: !Audio.isLive && Audio.length > 0
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
        // The right button lands on a song rather than between two. Hitting a
        // mark by hand on a bar a few hundred pixels wide is luck, so a rough
        // press with this button is enough.
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: function (point) {
                Audio.seekToTick(point.position.x / scrubber.width)
            }
        }
        DragHandler {
            id: scrubDrag
            target: null
            yAxis.enabled: false
            onCentroidChanged: if (active) Audio.seek(centroid.position.x / scrubber.width)
        }
        // The wheel over the bar moves along the track, in seconds rather than
        // in a share of it, since the gesture is the same whatever is playing.
        // Carried the way the volume carries its own, so a touchpad, which
        // sends one turn as a pile of small ones, moves once rather than not
        // at all.
        WheelHandler {
            objectName: "musicScrubWheel"
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            property real carried: 0
            onWheel: function (event) {
                carried += event.angleDelta.y
                while (carried >= 120) { carried -= 120; Audio.nudgeSeek(1) }
                while (carried <= -120) { carried += 120; Audio.nudgeSeek(-1) }
            }
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

            QueueList {
                id: queued
                objectName: "queuedList"
                owner: upNext
                width: parent.width
                height: parent.height - 22
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
                id: secondLine
                objectName: "musicSecondLine"
                // The name leads to whoever made it, but only while it is a
                // name. This line carries the chapter where a track has one,
                // and the word "loading" before that, and neither of those is
                // somebody to go and see.
                readonly property string leadsTo:
                    (!Audio.loading && Audio.currentChapter === ""
                     && Audio.track.artistId) ? Audio.track.artistId : ""
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
                color: (Audio.currentChapter !== "" && !Audio.loading)
                       || (secondLine.leadsTo !== "" && secondLineHover.hovered)
                       ? Theme.colors.text : Theme.colors.textMuted
                font.pixelSize: 11
                font.underline: secondLine.leadsTo !== "" && secondLineHover.hovered
                elide: Text.ElideRight

                HoverHandler {
                    id: secondLineHover
                    enabled: secondLine.leadsTo !== ""
                    cursorShape: Qt.PointingHandCursor
                }

                // Only as wide as the words, so the rest of the bar is not a
                // target for something that cannot be seen.
                MouseArea {
                    enabled: secondLine.leadsTo !== ""
                    width: Math.min(secondLine.implicitWidth, parent.width)
                    height: parent.height
                    onClicked: App.openArtistMusic(secondLine.leadsTo)
                }
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
            objectName: "previousButton"
            text: "◀◀"
            hint: "The one before"
            fontSize: 14
            nudgeY: -1.5
            Layout.preferredWidth: 42
            onClicked: Audio.previous()
        }
        FlatButton {
            // Fixed, because the pause and play marks are different widths and
            // everything to the right of it used to shuffle sideways.
            objectName: "playButton"
            text: Audio.playing ? "❚❚" : "▶"
            hint: Audio.playing ? "Pause" : "Play"
            fontSize: 15
            // MEASURED: both marks sit dead centre of the box. A triangle
            // still reads as leaning left, because its weight is nearer the
            // base than the point, so the one is carried a pixel over. The
            // two bars are symmetrical and want nothing.
            nudge: Audio.playing ? 0 : 1
            nudgeY: -1.5
            accent: true
            Layout.preferredWidth: 46
            onClicked: Audio.toggle()
        }
        FlatButton {
            objectName: "nextButton"
            text: "▶▶"
            hint: "The next one"
            fontSize: 14
            nudgeY: -1.5
            Layout.preferredWidth: 42
            onClicked: Audio.next()
        }

        Label {
            visible: !Audio.isLive && Audio.length > 0
            text: bar.clock(Audio.elapsed) + " / " + bar.clock(Audio.length)
            color: Theme.colors.textMuted
            font.pixelSize: 11
        }
        Label {
            objectName: "musicLiveWord"
            // Said because the entry is a broadcast, never because a length
            // has not arrived yet. Read the other way it claimed live for the
            // second at the start of every ordinary track, and went out again
            // on a real one the moment mpv reported the window it was holding.
            visible: Audio.isLive
            text: "live"
            color: Theme.colors.live
            font.pixelSize: 11
            font.bold: true
        }

        Item { Layout.fillWidth: true }

        // Marks rather than words, like the transport beside them. Both are
        // states rather than acts, and a word that is only lit when it is on
        // is read as a button that does nothing the rest of the time.
        FlatButton {
            objectName: "shuffleButton"
            text: "\u21c4"
            hint: Audio.shuffle ? "Shuffle is on" : "Shuffle is off"
            fontSize: 16
            nudgeY: -1
            accent: Audio.shuffle
            Layout.preferredWidth: 42
            onClicked: Audio.setShuffle(!Audio.shuffle)
        }
        FlatButton {
            // Off, the whole queue, or the one track. A queue that repeats
            // and a track that repeats are different wants, so the one track
            // carries a 1 beside the mark.
            objectName: "repeatButton"
            text: Audio.repeat === 2 ? "\u21bb 1" : "\u21bb"
            hint: Audio.repeatLabel === "Repeat" ? "Repeat is off"
                                                 : (Audio.repeat === 2 ? "Repeating this song"
                                                                       : "Repeating the queue")
            fontSize: 16
            accent: Audio.repeat > 0
            Layout.preferredWidth: 48
            onClicked: Audio.cycleRepeat()
        }
        FlatButton {
            // Two things playing at once is never wanted, but it is a choice.
            objectName: "autoPauseButton"
            text: "Pause for video"
            hint: Audio.autoPause ? "The music stops when a video starts"
                                  : "The music keeps playing over a video"
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
            objectName: "queueButton"
            text: "Queue"
            hint: Audio.queue.length + (Audio.queue.length === 1 ? " song in the queue"
                                                                 : " songs in the queue")
            enabled: Audio.queue.length > 0
            onClicked: upNext.open()
        }

        FlatButton {
            // The page where the queue, the words and the picture are. A mark
            // rather than a word, because the bar it sits on already says what
            // it would be naming, and every other player puts one here.
            objectName: "nowPlayingButton"
            text: App.viewKind === "nowplaying" ? "\u2304" : "\u2303"
            hint: App.viewKind === "nowplaying" ? "Back to where you were"
                                                : "The Now playing page"
            fontSize: 15
            nudgeY: 4
            accent: App.viewKind === "nowplaying"
            enabled: Audio.queue.length > 0
            Layout.preferredWidth: 42
            onClicked: App.toggleNowPlaying()
        }
        FlatButton {
            objectName: "stopButton"
            text: "✕"
            hint: "Stop the music"
            fontSize: 13
            onClicked: Audio.stop()
        }
    }
}
