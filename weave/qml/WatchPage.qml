import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Weave 1.0

// The page a video plays on when videos play in the window rather than in mpv.
//
// The music's Now playing page, shape for shape: the picture in the middle with
// what is known about it underneath, the queue in a column on the right, the
// same slide out of the bottom and the same ground. What differs is what a
// video needs and a song does not: controls over the picture, and the picture
// always on.
Item {
    id: page
    objectName: "watchingView"

    readonly property bool wanted: App.viewKind === "watching"
    property bool everShown: false
    onWantedChanged: {
        if (wanted)
            everShown = true
        // The surface builds its render context on a paint and has no reason
        // of its own to paint, so it is asked, exactly as the music page asks
        // its own.
        if (wanted)
            watchSurface.update()
    }
    visible: true

    transform: Translate {
        id: shift
        y: page.wanted ? 0 : page.height
        Behavior on y {
            enabled: page.everShown
            NumberAnimation {
                id: slideStep
                duration: 190
                easing.type: Easing.OutCubic
            }
        }
    }

    // The window's own ground, held still against the window while the page
    // travels over it. The music page's reasons, word for word.
    Item {
        objectName: "watchingGroundClip"
        anchors.fill: parent
        clip: true
        z: -1

        ThemeBackground {
            objectName: "watchingGround"
            x: -page.groundX
            y: -page.groundY - shift.y
            width: page.groundWidth
            height: page.groundHeight
        }
    }

    readonly property bool sliding: slideStep.running
    onSlidingChanged: {
        if (!sliding && wanted)
            watchSurface.update()
    }

    property bool cinema: false
    property bool chromeAwake: true
    property real barRoom: 0
    property real groundX: 0
    property real groundY: 0
    property real groundWidth: width
    property real groundHeight: height
    signal fullscreenToggled()
    // A right press on the title, for the card menu of the video playing.
    signal cardMenuRequested(string key)
    signal queueMenuRequested(string key)

    // The screen the window is on decides how big a picture is worth fetching,
    // counted in its real pixels so a scaled screen counts what it really has.
    readonly property int screenPixels: Math.round(Screen.height * Screen.devicePixelRatio)
    onScreenPixelsChanged: Video.setScreenHeight(screenPixels)
    Component.onCompleted: Video.setScreenHeight(screenPixels)

    property bool sideNear: false
    readonly property bool sideAwake: page.cinema && page.sideNear
    readonly property bool roomForColumn: width >= 1100
    readonly property int queueWidth: roomForColumn
        ? Math.max(420, Math.min(500, Math.round(width * 0.27))) : 300

    // Whether the controls are up. While the picture is in a page, the
    // pointer being over it brings them and a still pointer takes them away
    // again after a moment; paused, or with nothing playing, they stay. While
    // the screen is filled the window decides, the way it does for the music.
    property bool pointerOverPicture: false
    property bool controlsRest: false
    readonly property bool controlsUp: !Video.playing || Video.ended
                                       || (page.cinema ? page.chromeAwake
                                                       : (page.pointerOverPicture
                                                          && !page.controlsRest))
    Timer {
        id: controlsNap
        interval: 2500
        onTriggered: page.controlsRest = true
    }
    function stirControls() {
        page.controlsRest = false
        controlsNap.restart()
    }

    // Every press on the page stays on the page. A press between its parts
    // was taken by nothing on it and went on to whatever lay underneath,
    // which was the cards of the view the page was opened from: a press
    // beside the picture played one of them or opened its channel.
    MouseArea {
        objectName: "watchingCatch"
        anchors.fill: parent
        enabled: page.wanted
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onWheel: function (wheel) { wheel.accepted = true }
    }

    RowLayout {
        id: pageRow
        anchors.fill: parent
        anchors.margins: page.cinema ? 0 : 16
        spacing: 16

        // ---- the middle: the picture and what is known about it ------------
        Item {
            id: stage
            objectName: "watchingStage"
            Layout.fillWidth: true
            Layout.fillHeight: true

            Item {
                id: videoPart
                objectName: "watchingVideoPart"
                width: stage.width
                height: stage.height

                Column {
                    id: middle
                    anchors.horizontalCenter: parent.horizontalCenter
                    // Placed by hand, never by swapping anchors: two vertical
                    // anchors at once make Qt write the height, and a height
                    // written once stays.
                    y: page.cinema ? Math.round((parent.height - height) / 2) : 0
                    width: frameSlot.width
                    spacing: 12

                    Item {
                        id: frameSlot
                        objectName: "watchingFrameSlot"
                        readonly property real spare: words.visible
                            ? videoPart.height - words.height - middle.spacing - descriptionArea.reserve
                            : videoPart.height
                        readonly property real room: Math.min(videoPart.width,
                                                              Math.max(90, spare) * 16 / 9)
                        width: page.cinema ? videoPart.width : Math.max(160, room)
                        height: page.cinema ? videoPart.height : width * 9 / 16
                    }

                    // ---- the words under the picture -----------------------
                    Column {
                        id: words
                        objectName: "watchingWords"
                        visible: !page.cinema
                        width: parent.width
                        spacing: 2

                        Row {
                            width: parent.width
                            spacing: 10

                            RoundedImage {
                                id: avatar
                                objectName: "watchingAvatar"
                                readonly property string face:
                                    App.watchDetail.channelAvatar ? App.watchDetail.channelAvatar : ""
                                width: height
                                height: Math.max(40, Math.min(96, titleRow.height
                                                 + channelLine.height + factsLine.height
                                                 + 2 * said.spacing))
                                circle: true
                                visible: face !== ""
                                source: face
                            }

                            Column {
                                id: said
                                width: parent.width - (avatar.visible
                                                       ? avatar.width + parent.spacing : 0)
                                spacing: 2

                                Row {
                                    id: titleRow
                                    width: parent.width
                                    spacing: 10

                                    Label {
                                        id: watchTitle
                                        objectName: "watchingTitle"
                                        width: parent.width - (toMpv.visible
                                                               ? toMpv.width + titleRow.spacing : 0)
                                        text: Video.track.title ? Video.track.title : ""
                                        color: Theme.colors.text
                                        font.pixelSize: 19
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight

                                        // A right press here is a right press on
                                        // the card this video came from.
                                        TapHandler {
                                            acceptedButtons: Qt.RightButton
                                            onTapped: page.cardMenuRequested(
                                                Video.track.key ? Video.track.key : "")
                                        }
                                    }

                                    // Where the music page has "Audio only": the
                                    // other way of playing it, from this second.
                                    FlatButton {
                                        id: toMpv
                                        objectName: "watchingPlayInMpv"
                                        visible: App.mpvFound
                                        text: "Play in mpv"
                                        hint: "Hand this video to mpv from where it is now"
                                        onClicked: App.watchInMpv()
                                    }
                                }

                                Label {
                                    id: channelLine
                                    objectName: "watchingChannel"
                                    readonly property string leadsTo:
                                        Video.track.channelKey ? Video.track.channelKey : ""
                                    width: parent.width
                                    visible: text !== ""
                                    text: Video.track.channel ? Video.track.channel
                                                              : (App.watchDetail.channelTitle
                                                                 ? App.watchDetail.channelTitle : "")
                                    color: leadsTo !== "" && channelHover.hovered
                                           ? Theme.colors.text : Theme.colors.textMuted
                                    font.pixelSize: 13
                                    font.underline: leadsTo !== "" && channelHover.hovered
                                    elide: Text.ElideRight

                                    HoverHandler {
                                        id: channelHover
                                        enabled: channelLine.leadsTo !== ""
                                        cursorShape: Qt.PointingHandCursor
                                    }
                                    TapHandler {
                                        enabled: channelLine.leadsTo !== ""
                                        onTapped: App.openChannel(channelLine.leadsTo)
                                    }
                                }

                                Label {
                                    id: factsLine
                                    objectName: "watchingFacts"
                                    width: parent.width
                                    visible: text !== ""
                                    text: {
                                        var bits = []
                                        var d = App.watchDetail
                                        if (Video.isLive) {
                                            bits.push("Live")
                                            if (d.viewersText)
                                                bits.push(d.viewersText + " watching")
                                        } else {
                                            if (d.viewsText)
                                                bits.push(d.viewsText + " views")
                                            if (d.likesText)
                                                bits.push(d.likesText + " likes")
                                            if (d.ageText)
                                                bits.push(d.ageText)
                                        }
                                        return bits.join("  ·  ")
                                    }
                                    color: Theme.colors.textMuted
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }

                SmoothScroll {
                    flickable: descriptionArea
                    step: Math.round(3 * descriptionLines.lineSpacing)
                }

                Rectangle {
                    id: descriptionBox
                    objectName: "watchingDescriptionBox"
                    readonly property real pad: 8
                    visible: descriptionArea.writing !== "" && words.visible
                    x: middle.x
                    y: middle.y + middle.height + descriptionArea.gap
                    width: middle.width
                    height: Math.min(Math.max(0, videoPart.height - y),
                                     description.height + 2 * pad)
                    radius: 8
                    color: Theme.wash(Theme.colors.text, 0.06)
                }

                Flickable {
                    id: descriptionArea
                    objectName: "watchingDescriptionArea"
                    readonly property string writing: App.watchDetail.descriptionText
                                                      ? App.watchDetail.descriptionText : ""
                    readonly property real reserve: writing !== "" && words.visible
                        ? gap + 2 * descriptionBox.pad + 2 * descriptionLines.lineSpacing : 0
                    readonly property real gap: 8
                    visible: descriptionBox.visible
                    x: descriptionBox.x + descriptionBox.pad
                    y: descriptionBox.y + descriptionBox.pad
                    width: descriptionBox.width - 2 * descriptionBox.pad
                    height: Math.max(0, descriptionBox.height - 2 * descriptionBox.pad)
                    contentWidth: width
                    contentHeight: description.height
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    FontMetrics {
                        id: descriptionLines
                        font.pixelSize: description.font.pixelSize
                    }

                    Connections {
                        target: Video
                        function onTrackChanged() { descriptionArea.contentY = 0 }
                    }

                    Label {
                        id: description
                        objectName: "watchingDescription"
                        width: descriptionArea.width - 10
                        text: descriptionArea.writing
                        color: Theme.colors.text
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        textFormat: Text.StyledText
                        linkColor: Theme.colors.accent

                        // An address opens in the browser and a time goes to
                        // that point in the video, as under a video on YouTube.
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton
                            property string link: ""
                            onPositionChanged: function (mouse) {
                                link = description.linkAt(mouse.x, mouse.y)
                            }
                            onExited: link = ""
                            cursorShape: link !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: function (mouse) {
                                var here = description.linkAt(mouse.x, mouse.y)
                                if (here.indexOf("weave-seek:") === 0)
                                    Video.seekTo(parseInt(here.slice(11)))
                                else if (here !== "")
                                    App.openLink(here)
                            }
                        }
                    }
                }
            }

            // ---- the picture ---------------------------------------------
            Item {
                id: frame
                objectName: "watchingFrame"
                z: 3
                x: videoPart.x + middle.x
                y: videoPart.y + middle.y
                width: frameSlot.width
                height: frameSlot.height
                clip: true

                Rectangle {
                    anchors.fill: parent
                    color: "black"
                }

                VideoSurface {
                    id: watchSurface
                    objectName: "watchingVideo"
                    player: "video"
                    anchors.fill: parent
                    // Never hidden, and drawing for as long as any of it can be
                    // seen. The music page's rule, for the music page's reason.
                    drawing: page.wanted || page.sliding
                }

                // The video's own picture until its first frame, so the press
                // lands on something rather than on black.
                Image {
                    objectName: "watchingPoster"
                    anchors.fill: parent
                    fillMode: Image.PreserveAspectFit
                    source: Video.track.thumbnail ? Video.track.thumbnail : ""
                    opacity: Video.videoShowing ? 0 : 1
                    visible: opacity > 0
                    Behavior on opacity {
                        NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
                    }
                }

                BusyWord {
                    objectName: "watchingOpening"
                    anchors.centerIn: parent
                    visible: Video.loading && !Video.videoShowing
                    text: "Opening the video"
                }

                // Whether the pointer is anywhere over the picture, the controls
                // on it included. A handler on the box rather than the press
                // area's own hover, which counted the pointer as gone the moment
                // it reached the controls drawn over it, and took them away from
                // under it.
                HoverHandler {
                    id: pictureHover
                    objectName: "watchingPictureHover"
                    cursorShape: page.cinema && !page.chromeAwake ? Qt.BlankCursor : Qt.ArrowCursor
                    onHoveredChanged: {
                        page.pointerOverPicture = hovered
                        if (hovered)
                            page.stirControls()
                    }
                    onPointChanged: if (hovered) page.stirControls()
                }

                // The left button does nothing on the picture: a press there is
                // how the window is brought forward to take keys. Two presses
                // fill the screen, and the right button pauses and plays.
                MouseArea {
                    objectName: "watchingSurface"
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function (mouse) {
                        if (mouse.button === Qt.RightButton)
                            Video.toggle()
                    }
                    onDoubleClicked: function (mouse) {
                        if (mouse.button === Qt.LeftButton)
                            page.fullscreenToggled()
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

                // The queue has run out and the last frame is held.
                FlatButton {
                    objectName: "watchingReplay"
                    anchors.centerIn: parent
                    visible: Video.ended
                    accent: true
                    text: "↻  Play again"
                    onClicked: Video.replay()
                }

                WatchControls {
                    id: controls
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    big: page.cinema
                    cinema: page.cinema
                    opacity: page.controlsUp ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity {
                        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
                    }
                    onFullscreenToggled: page.fullscreenToggled()
                }
            }
        }

        // ---- the queue beside it -------------------------------------------
        Item {
            id: sideCell
            objectName: "watchingSideCell"
            Layout.preferredWidth: page.cinema ? 0 : page.queueWidth
            Layout.maximumWidth: Layout.preferredWidth
            Layout.fillHeight: true
            visible: !page.cinema
        }
    }

    Rectangle {
        id: side
        objectName: "watchingSide"
        parent: page.cinema ? sideSlot : sideCell
        anchors.fill: parent
        radius: 10
        color: Theme.wash(Theme.colors.surface, page.cinema ? 0.9 : 0.78)
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
                text: ("Queue" + (Video.queue.length > 0 ? "  ·  " + Video.queue.length : ""))
                      .toUpperCase()
                color: Theme.colors.textMuted
                font.pixelSize: 11
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }

            Item { Layout.fillWidth: true }

            FlatButton {
                objectName: "watchingQueueClear"
                visible: Video.queue.length > 1
                text: "Clear"
                hint: "Take everything out of the queue except the video playing"
                onClicked: Video.clearQueue()
            }
        }

        QueueList {
            objectName: "watchingQueue"
            player: Video
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: queueHead.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 8
            anchors.topMargin: 10
            onMenuRequested: (key) => page.queueMenuRequested(key)
        }
    }

    Item {
        id: sideSlot
        objectName: "watchingSideSlot"
        z: 4
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 16
        anchors.bottomMargin: 16 + page.barRoom + controls.height
        width: Math.max(300, page.width / 5 - 32)
        visible: opacity > 0
        opacity: page.sideAwake ? 1 : 0
        enabled: page.sideAwake
        Behavior on opacity {
            NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
        }
    }

    HoverHandler {
        id: sideWatch
        objectName: "watchingSideWatch"
        enabled: page.cinema
        onPointChanged: {
            if (!sideWatch.hovered)
                return
            page.sideNear = point.position.x >= page.width * 0.8
        }
        property bool everHere: false
        onHoveredChanged: {
            if (hovered) {
                sideWatch.everHere = true
                return
            }
            if (!sideWatch.everHere)
                return
            sideWatch.everHere = false
            page.sideNear = false
        }
    }
}
