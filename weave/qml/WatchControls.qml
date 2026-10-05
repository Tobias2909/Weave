import QtQuick
import QtQuick.Controls

// The controls floating over the foot of the picture. White on a dark fade,
// whatever the theme, because they sit on a picture and not on the window; the
// one colour taken from the theme is the part already played.
//
// The bar is drawn the way the music bar draws its own: the chapters cut into
// it as gaps, and the pointer over it says which chapter and when.
Item {
    id: controls
    objectName: "watchControls"

    // Bigger when the picture is the screen.
    property bool big: false
    // Whether the screen is filled, for the words on the last button.
    property bool cinema: false

    signal fullscreenToggled()

    readonly property int rowHeight: big ? 38 : 30
    readonly property bool live: Video.isLive
    height: big ? 132 : 104

    // How far up from the foot of the picture the controls reach, which is
    // how far a caption is lifted while they are up.
    readonly property real reach: height - bar.y + 8

    // A menu open on the picture keeps the controls up under it.
    readonly property bool menuOpen: speedMenu.opened || captionMenu.opened
                                     || qualityMenu.opened

    function speedText(speed) {
        return (Math.round(speed * 100) / 100) + "\u00d7"
    }

    function clock(seconds) {
        seconds = Math.max(0, Math.floor(seconds))
        var h = Math.floor(seconds / 3600)
        var m = Math.floor((seconds % 3600) / 60)
        var s = seconds % 60
        var mm = h > 0 && m < 10 ? "0" + m : "" + m
        return (h > 0 ? h + ":" : "") + mm + ":" + (s < 10 ? "0" + s : s)
    }

    component ControlButton: Rectangle {
        id: button
        property string text: ""
        property string hint: ""
        property int fontSize: controls.big ? 15 : 13
        property bool on: false
        signal pressed()
        width: label.implicitWidth + (controls.big ? 24 : 18)
        height: controls.rowHeight
        radius: 6
        color: on ? Theme.wash(Theme.colors.accent, 0.55)
                  : (hover.hovered ? Qt.rgba(1, 1, 1, 0.16) : "transparent")
        Label {
            id: label
            anchors.centerIn: parent
            text: button.text
            color: "#f2f2f2"
            font.pixelSize: button.fontSize
            font.weight: Font.DemiBold
        }
        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
        // Kept to itself. A handler shares a press with every handler under
        // it, and the page has been over cards that would take it too.
        TapHandler {
            gesturePolicy: TapHandler.ReleaseWithinBounds
            onTapped: button.pressed()
        }
        // Not over a menu the button has opened.
        ToolTip.visible: hint !== "" && hover.hovered && !controls.menuOpen
        ToolTip.delay: 450
        ToolTip.text: hint
    }

    // A menu of the buttons on the right, rising from the button it belongs
    // to and lined up with its right edge. A long one scrolls rather than
    // reaching past the picture.
    component PictureMenu: ThemedMenu {
        id: pictureMenu
        property real tallest: controls.big ? 520 : 340
        implicitWidth: 190
        height: Math.min(implicitHeight, tallest)
        x: parent ? parent.width - width : 0
        y: -height - 6
    }

    // The fade the controls stand on.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.8) }
        }
    }

    // ---- the bar -----------------------------------------------------------
    Item {
        id: bar
        objectName: "watchSeekBar"
        visible: !controls.live && Video.length > 0
        x: controls.big ? 28 : 18
        width: parent.width - 2 * x
        y: parent.height - controls.rowHeight - (controls.big ? 18 : 10) - 22
        height: 16

        HoverHandler { id: barHover; cursorShape: Qt.PointingHandCursor }

        readonly property real pointerAt: barHover.hovered
            ? Math.max(0, Math.min(1, barHover.point.position.x / Math.max(1, width))) : -1
        readonly property bool raised: barHover.hovered || barPress.dragging

        Rectangle {
            id: track
            objectName: "watchSeekTrack"
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: bar.raised ? 7 : 4
            color: Qt.rgba(1, 1, 1, 0.26)
            Behavior on height { NumberAnimation { duration: 90 } }

            // What is fetched already, lighter than the rest, the way every
            // player draws it.
            Repeater {
                model: Video.buffered
                Rectangle {
                    objectName: "watchBuffered"
                    required property var modelData
                    x: track.width * modelData.at
                    width: track.width * (modelData.to - modelData.at)
                    height: track.height
                    color: Qt.rgba(1, 1, 1, 0.42)
                }
            }

            Rectangle {
                width: parent.width * (barPress.dragging ? barPress.along : Video.position)
                height: parent.height
                color: Theme.colors.accent
            }

            // What SponsorBlock's users marked, in its own colours, over
            // the played part and the rest alike.
            Repeater {
                model: Video.segments
                Rectangle {
                    objectName: "watchSegmentMark"
                    required property var modelData
                    x: track.width * modelData.at
                    width: Math.max(2, track.width * (modelData.to - modelData.at))
                    height: track.height
                    color: modelData.colour
                }
            }

            // The chapters, as gaps cut into the bar.
            Repeater {
                model: Video.chapters
                Rectangle {
                    objectName: "watchChapterMark"
                    required property var modelData
                    visible: modelData.at > 0 && modelData.at < 1
                    x: track.width * modelData.at - 1
                    width: 3
                    height: track.height
                    color: Qt.rgba(0, 0, 0, 0.9)
                }
            }
        }

        Rectangle {
            visible: bar.raised
            x: track.width * (barPress.dragging ? barPress.along : Video.position) - 7
            anchors.verticalCenter: parent.verticalCenter
            width: 14; height: 14; radius: 7
            color: Theme.colors.accent
        }

        // A left press or a drag goes there. A right press goes to the
        // chapter start nearest the pointer, back or forward, the way the
        // player this replaces does it, or to the start or the end of a part
        // SponsorBlock marked, whichever of them all is nearest.
        //
        // One area for both, so a press is never argued over by two handlers.
        // Dragging shows where it will land and goes there on letting go, so a
        // stream is not asked to seek for every pixel the hand passes.
        MouseArea {
            id: barPress
            objectName: "watchSeekArea"
            anchors.fill: parent
            anchors.topMargin: -6
            anchors.bottomMargin: -6
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            property bool dragging: false
            property real along: 0
            function alongAt(x) { return Math.max(0, Math.min(1, x / Math.max(1, width))) }
            onPressed: function (mouse) {
                if (mouse.button === Qt.RightButton) {
                    var marks = Video.chapters.map(function (one) {
                        return { at: one.at, seconds: one.start }
                    })
                    Video.segments.forEach(function (one) {
                        marks.push({ at: one.at, seconds: one.start })
                        marks.push({ at: one.to, seconds: one.end })
                    })
                    if (!marks.length)
                        return
                    var here = alongAt(mouse.x)
                    var best = marks[0]
                    for (var i = 1; i < marks.length; i++)
                        if (Math.abs(marks[i].at - here) < Math.abs(best.at - here))
                            best = marks[i]
                    Video.seekTo(best.seconds)
                    return
                }
                along = alongAt(mouse.x)
                dragging = true
            }
            onPositionChanged: function (mouse) {
                if (dragging)
                    along = alongAt(mouse.x)
            }
            onReleased: function (mouse) {
                if (!dragging)
                    return
                dragging = false
                Video.seek(alongAt(mouse.x))
            }
            onCanceled: dragging = false

            // The wheel over the bar moves along the video, five seconds a
            // turn, the way it does over the music's bar, and carried the same
            // way for a touchpad. Here rather than on the bar, so the strip
            // above and below it that takes a press takes the wheel too, and
            // the volume the picture gives the wheel does not.
            WheelHandler {
                objectName: "watchScrubWheel"
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                property real carried: 0
                onWheel: function (event) {
                    carried += event.angleDelta.y
                    while (carried >= 120) { carried -= 120; Video.nudgeSeek(1) }
                    while (carried <= -120) { carried += 120; Video.nudgeSeek(-1) }
                }
            }
        }
    }

    // What the pointer over the bar would go to: a picture of that moment
    // when YouTube made some, the chapter, and when.
    Rectangle {
        id: peek
        objectName: "watchSeekPeek"
        visible: bar.visible && bar.pointerAt >= 0
        readonly property string chapter: visible ? Video.chapterAt(bar.pointerAt) : ""
        readonly property string segment: visible && Video.segments.length > 0
                                          ? Video.segmentAt(bar.pointerAt) : ""
        readonly property var board: Video.storyboard
        readonly property bool pictured: board.sheets !== undefined
        readonly property var frame: visible && pictured ? Video.previewAt(bar.pointerAt) : ({})
        readonly property real shotWidth: controls.big ? 256 : 200
        readonly property real shotHeight: pictured
                                           ? Math.round(shotWidth * board.height / board.width) : 0
        width: pictured ? shotWidth + 12
                        : Math.max(80, Math.min(260, peekWords.implicitWidth + 20))
        height: (pictured ? shotHeight + 6 : 0) + peekWords.implicitHeight + 12
        radius: 6
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border
        x: Math.max(4, Math.min(controls.width - width - 4,
                                bar.x + bar.width * bar.pointerAt - width / 2))
        y: bar.y - height - 6

        // One frame of a sheet of them, the sheet scaled to the box and moved
        // so that frame is the part showing. Sized by the sheet itself, since
        // the last one of a video holds only the frames that are left.
        Rectangle {
            id: shot
            visible: peek.pictured
            x: 6
            y: 6
            width: peek.shotWidth
            height: peek.shotHeight
            radius: 3
            clip: true
            color: "#000000"

            Image {
                objectName: "watchSeekShot"
                readonly property real scaled: peek.shotWidth / Math.max(1, peek.board.width || 1)
                source: peek.frame.sheet || ""
                asynchronous: true
                cache: true
                // The sheet before stays up while the next one comes, rather
                // than a black box for the time it takes.
                retainWhileLoading: true
                smooth: true
                width: implicitWidth * scaled
                height: implicitHeight * scaled
                x: -(peek.frame.column || 0) * peek.shotWidth
                y: -(peek.frame.row || 0) * peek.shotHeight
            }
        }

        Label {
            id: peekWords
            anchors.horizontalCenter: parent.horizontalCenter
            y: peek.pictured ? shot.y + shot.height + 4 : (peek.height - height) / 2
            width: Math.min(peek.pictured ? peek.shotWidth : 240, implicitWidth)
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            textFormat: Text.PlainText
            text: (peek.segment !== "" ? peek.segment + "\n" : "")
                  + (peek.chapter !== "" ? peek.chapter + "\n" : "")
                  + controls.clock(bar.pointerAt * Video.length)
            color: Theme.colors.text
            font.pixelSize: 12
        }
    }

    // ---- the buttons -------------------------------------------------------
    Row {
        x: controls.big ? 18 : 10
        y: parent.height - controls.rowHeight - (controls.big ? 18 : 10)
        height: controls.rowHeight
        spacing: 4

        ControlButton {
            objectName: "watchPlayButton"
            text: Video.playing ? "❚❚" : "▶"
            hint: Video.playing ? "Pause" : "Play"
            fontSize: controls.big ? 18 : 15
            onPressed: Video.toggle()
        }
        ControlButton {
            objectName: "watchNextButton"
            visible: Video.queueIndex >= 0 && Video.queueIndex + 1 < Video.queue.length
            text: "▶▶"
            hint: "The next one"
            onPressed: Video.next()
        }

        // The sound: a mark and a slider, the wheel moving it five a notch.
        Item {
            width: controls.big ? 150 : 120
            height: controls.rowHeight
            // Drawn rather than taken from a font: the emoji ones come in
            // colour, and every other mark here is white.
            Canvas {
                id: soundMark
                x: 6
                width: 18
                height: 18
                anchors.verticalCenter: parent.verticalCenter
                property bool silent: Video.volume === 0
                onSilentChanged: requestPaint()
                onPaint: {
                    var g = getContext("2d")
                    g.reset()
                    g.fillStyle = "#f2f2f2"
                    g.beginPath()
                    g.moveTo(1, 6); g.lineTo(5, 6); g.lineTo(10, 1)
                    g.lineTo(10, 17); g.lineTo(5, 12); g.lineTo(1, 12)
                    g.closePath()
                    g.fill()
                    g.strokeStyle = "#f2f2f2"
                    g.lineWidth = 1.6
                    if (silent) {
                        g.beginPath(); g.moveTo(12, 6); g.lineTo(17, 12); g.stroke()
                        g.beginPath(); g.moveTo(17, 6); g.lineTo(12, 12); g.stroke()
                    } else {
                        g.beginPath(); g.arc(10, 9, 4, -0.9, 0.9); g.stroke()
                        g.beginPath(); g.arc(10, 9, 7, -0.9, 0.9); g.stroke()
                    }
                }
            }
            Slider {
                id: loudness
                objectName: "watchVolume"
                x: soundMark.x + soundMark.width + 6
                width: parent.width - x - 4
                anchors.verticalCenter: parent.verticalCenter
                from: 0
                to: 100
                value: Video.volume
                onMoved: Video.setVolume(value)
                // Drawn to match the marks beside it rather than in the
                // style's own colours, which are a theme's and sit on a picture
                // here.
                background: Rectangle {
                    x: loudness.leftPadding
                    y: loudness.topPadding + loudness.availableHeight / 2 - height / 2
                    width: loudness.availableWidth
                    height: 4
                    radius: 2
                    color: Qt.rgba(1, 1, 1, 0.3)
                    Rectangle {
                        width: loudness.visualPosition * parent.width
                        height: parent.height
                        radius: 2
                        color: "#f2f2f2"
                    }
                }
                handle: Rectangle {
                    x: loudness.leftPadding + loudness.visualPosition
                       * (loudness.availableWidth - width)
                    y: loudness.topPadding + loudness.availableHeight / 2 - height / 2
                    width: 12
                    height: 12
                    radius: 6
                    color: "#f2f2f2"
                }
                WheelHandler {
                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                    property real carried: 0
                    onWheel: function (event) {
                        carried += event.angleDelta.y
                        while (carried >= 120) { carried -= 120; Video.nudgeVolume(1) }
                        while (carried <= -120) { carried += 120; Video.nudgeVolume(-1) }
                    }
                }
            }
        }

        // Red at the broadcast's present, grey behind it, and then a way back.
        Rectangle {
            objectName: "watchLiveMark"
            visible: controls.live
            anchors.verticalCenter: parent.verticalCenter
            width: liveWord.implicitWidth + 14
            height: controls.big ? 24 : 20
            radius: 4
            color: Video.behindLive > 0 ? Qt.rgba(1, 1, 1, 0.3) : "#e0283a"
            HoverHandler {
                enabled: Video.behindLive > 0
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                enabled: Video.behindLive > 0
                gesturePolicy: TapHandler.ReleaseWithinBounds
                onTapped: Video.goLive()
            }
            Label {
                id: liveWord
                anchors.centerIn: parent
                text: "LIVE"
                color: "white"
                font.pixelSize: controls.big ? 13 : 11
                font.weight: Font.Bold
                font.letterSpacing: 1
            }
        }

        Label {
            objectName: "watchWatching"
            visible: controls.live && text !== ""
            anchors.verticalCenter: parent.verticalCenter
            leftPadding: 4
            text: App.watchDetail.watchingExact ? App.watchDetail.watchingExact + " watching" : ""
            color: "#f2f2f2"
            font.pixelSize: controls.big ? 15 : 13
        }
        Label {
            objectName: "watchBehind"
            visible: controls.live && Video.behindLive > 0
            anchors.verticalCenter: parent.verticalCenter
            leftPadding: 6
            rightPadding: 4
            text: "·   " + controls.clock(Video.behindLive) + " behind"
            color: Qt.rgba(1, 1, 1, 0.72)
            font.pixelSize: controls.big ? 15 : 13
        }
        ControlButton {
            objectName: "watchGoLive"
            visible: controls.live && Video.behindLive > 0
            text: "Back to live"
            hint: "Skip to what is on air now"
            onPressed: Video.goLive()
        }
        Label {
            objectName: "watchClock"
            visible: !controls.live
            anchors.verticalCenter: parent.verticalCenter
            leftPadding: 4
            text: controls.clock(Video.seconds) + " / " + controls.clock(Video.length)
            color: "#f2f2f2"
            font.pixelSize: controls.big ? 15 : 13
        }
        Label {
            objectName: "watchChapterNow"
            visible: !controls.live && Video.currentChapter !== ""
            anchors.verticalCenter: parent.verticalCenter
            leftPadding: 10
            width: Math.min(implicitWidth, controls.width * 0.35)
            elide: Text.ElideRight
            text: "·   " + Video.currentChapter
            color: Qt.rgba(1, 1, 1, 0.72)
            font.pixelSize: controls.big ? 15 : 13
        }
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: controls.big ? 18 : 10
        y: parent.height - controls.rowHeight - (controls.big ? 18 : 10)
        height: controls.rowHeight
        spacing: 4

        ControlButton {
            id: speedButton
            objectName: "watchSpeed"
            visible: !controls.live
            text: controls.speedText(Video.speed)
            hint: "Speed"
            onPressed: speedMenu.open()

            PictureMenu {
                id: speedMenu
                objectName: "watchSpeedMenu"
                implicitWidth: 120

                Repeater {
                    model: Video.speeds

                    ThemedMenuItem {
                        required property var modelData
                        text: controls.speedText(modelData)
                              + (Math.abs(modelData - Video.speed) < 0.001 ? "   \u2713" : "")
                        onTriggered: {
                            var picked = modelData
                            speedMenu.dismiss()
                            Video.setSpeed(picked)
                        }
                    }
                }
            }
        }

        ControlButton {
            id: captionButton
            objectName: "watchCaptions"
            visible: Video.captions.length > 0
            text: "CC"
            hint: Video.captionShowing ? "Captions" : "Captions are off"
            on: Video.captionShowing
            onPressed: captionMenu.open()

            PictureMenu {
                id: captionMenu
                objectName: "watchCaptionMenu"
                implicitWidth: 240

                ThemedMenuItem {
                    objectName: "watchCaptionOff"
                    text: "Off" + (Video.captionShowing ? "" : "   \u2713")
                    onTriggered: {
                        captionMenu.dismiss()
                        Video.setCaption(-1)
                    }
                }
                Repeater {
                    model: Video.captions

                    ThemedMenuItem {
                        required property var modelData
                        required property int index
                        objectName: "watchCaptionEntry"
                        text: modelData.label + (modelData.chosen ? "   \u2713" : "")
                        // Shut first: what is picked changes the list, and
                        // the entry pressed is made again under the hand.
                        onTriggered: {
                            var picked = index
                            captionMenu.dismiss()
                            Video.setCaption(picked)
                        }
                    }
                }
            }
        }

        ControlButton {
            id: qualityButton
            objectName: "watchQuality"
            text: Video.qualityText
            hint: "Quality"
            onPressed: qualityMenu.open()

            PictureMenu {
                id: qualityMenu
                objectName: "watchQualityMenu"
                implicitWidth: 240

                Repeater {
                    model: Video.qualities

                    ThemedMenuItem {
                        required property var modelData
                        text: modelData.label + (modelData.playing ? "  \u00b7  playing" : "")
                              + (modelData.chosen ? "   \u2713" : "")
                        onTriggered: {
                            var picked = modelData.height
                            qualityMenu.dismiss()
                            Video.setQuality(picked)
                        }
                    }
                }
            }
        }

        // How the chat shows while the picture fills the screen, one press
        // to the next of the three.
        ControlButton {
            objectName: "watchChatMode"
            visible: controls.cinema && Chat.available
            text: "Chat: " + ({ "full": "Off", "beside": "Beside", "over": "Over" })[Chat.fullMode]
            hint: "Where the chat shows (F10)"
            onPressed: Chat.cycleFullMode()
        }

        ControlButton {
            objectName: "watchFullscreen"
            text: controls.cinema ? "Leave fullscreen" : "Fullscreen"
            onPressed: controls.fullscreenToggled()
        }
    }
}
