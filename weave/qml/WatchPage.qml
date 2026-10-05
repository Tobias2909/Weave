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
    // A right press on a tile of the Recommended tab.
    signal tileMenuRequested(int index, string key)

    // Which tab the middle shows; the queue beside it is the same on all of
    // them. A Twitch stream has only its picture. A stream on YouTube has no
    // comments to read while it is on, only its chat.
    property string tab: "video"
    readonly property bool twitch: (Video.track.login || "") !== ""
    readonly property var tabs: twitch ? []
        : [{ name: "video", label: "Video" }, { name: "recommended", label: "Recommended" }]
          .concat(Video.isLive ? [] : [{ name: "comments", label: "Comments" }])
    // On every tab but the video's the picture sits small in a corner, so the
    // video stays in sight while the rest of the page is about it.
    readonly property bool small: tab !== "video" && !cinema

    // How long a broadcast has been on air, counted on from the moment it
    // started while the page is open.
    property real now: Date.now()
    Timer {
        running: page.wanted && Video.isLive
        interval: 1000
        repeat: true
        triggeredOnStart: true
        onTriggered: page.now = Date.now()
    }
    function onAir(since) {
        var seconds = Math.max(0, Math.floor(page.now / 1000 - since))
        var h = Math.floor(seconds / 3600)
        var m = Math.floor((seconds % 3600) / 60)
        var s = seconds % 60
        return "on air " + h + ":" + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }

    // ---- the chat ---------------------------------------------------------
    //
    // Beside the picture in the column the queue is in, switched between the
    // two at its top. With the screen filled, how it shows is the chat's own
    // choice, kept between runs: not at all, in a column beside a smaller
    // picture, or in a panel over the picture that can be moved and sized.
    readonly property bool chatHere: Chat.available
    readonly property string chatMode: chatHere ? Chat.fullMode : "full"
    readonly property bool beside: page.cinema && page.chatMode === "beside"
    readonly property bool over: page.cinema && page.chatMode === "over"
    readonly property bool chatOnScreen: page.wanted && page.chatHere
        && (page.cinema ? page.chatMode !== "full" : Chat.column === "chat")
    // Told once the change has settled: starting to read changes what the
    // chat says about itself, which this is worked out from.
    onChatOnScreenChanged: Qt.callLater(page.tellChat)
    function tellChat() { Chat.setShown(page.chatOnScreen) }

    // Asked every time the tab is opened, the way the music page does.
    function choose(name) {
        page.tab = name
        App.setWatchTab(name)
        if (name === "comments")
            App.readWatchComments()
    }

    // The screen filled is the picture and nothing else.
    onCinemaChanged: if (cinema && tab !== "video") choose("video")
    // A tab the next video does not have leaves for its picture.
    onTabsChanged: {
        for (var i = 0; i < tabs.length; ++i)
            if (tabs[i].name === tab)
                return
        if (tab !== "video")
            choose("video")
    }

    // The screen the window is on decides how big a picture is worth fetching,
    // counted in its real pixels so a scaled screen counts what it really has.
    readonly property int screenPixels: Math.round(Screen.height * Screen.devicePixelRatio)
    onScreenPixelsChanged: Video.setScreenHeight(screenPixels)
    Component.onCompleted: {
        Video.setScreenHeight(screenPixels)
        Chat.setShown(page.chatOnScreen)
    }

    property bool sideNear: false
    readonly property bool sideAwake: page.cinema && page.sideNear && page.chatMode === "full"
    readonly property bool roomForColumn: width >= 1100
    readonly property int queueWidth: roomForColumn
        ? Math.max(420, Math.min(500, Math.round(width * 0.27))) : 300

    // Whether the controls are up. While the picture is in a page, the
    // pointer being over it brings them and a still pointer takes them away
    // again after a moment; paused, or with nothing playing, they stay. While
    // the screen is filled the window decides, the way it does for the music.
    property bool pointerOverPicture: false
    property bool controlsRest: false
    readonly property bool controlsUp: !Video.playing || Video.ended || controls.menuOpen
                                       || (page.cinema ? page.chromeAwake
                                                       : (page.pointerOverPicture
                                                          && !page.controlsRest))
    // Captions rise over the controls while they are up, rather than being
    // read through the bar, and settle back as the controls go.
    property real captionLift: page.controlsUp && !page.small
                               ? controls.reach / Math.max(1, frame.height) : 0
    Behavior on captionLift {
        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
    onCaptionLiftChanged: Video.setCaptionLift(captionLift)

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
        // Filling the screen there is no gap: the chat's black column meets
        // the black around the picture.
        spacing: page.cinema ? 0 : 16

        // ---- the middle: the picture and what is known about it ------------
        Item {
            id: stage
            objectName: "watchingStage"
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Where the tabs leave off. The screen filled has none, and
            // neither has a video with only its picture to show.
            readonly property real contentTop: page.cinema || page.tabs.length === 0
                                               ? 0 : tabRow.height + 12

            Row {
                id: tabRow
                objectName: "watchingTabs"
                visible: !page.cinema && page.tabs.length > 0
                spacing: 6

                Repeater {
                    model: page.tabs
                    FlatButton {
                        required property var modelData
                        objectName: "watchingTab_" + modelData.name
                        text: modelData.label
                        accent: page.tab === modelData.name
                        onClicked: page.choose(modelData.name)
                    }
                }
            }

            // ---- the Video tab: the picture and what is known about it ----
            //
            // Gone quickly as the picture leaves for its corner, so the words
            // are never seen sliding about under it.
            Item {
                id: videoPart
                objectName: "watchingVideoPart"
                y: stage.contentTop
                width: stage.width
                height: stage.height - y
                opacity: 1 - Math.min(1, frame.glide * 2.5)
                visible: opacity > 0
                enabled: !page.small

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
                                            if (d.watchingExact)
                                                bits.push(d.watchingExact + " watching")
                                            if (d.liveSince)
                                                bits.push(page.onAir(d.liveSince))
                                            if (d.gameText)
                                                bits.push(d.gameText)
                                            if (bits.length === 0)
                                                bits.push("Live")
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

            // ---- every other tab: the picture small, and beside it what the
            // tab is about ---------------------------------------------------
            Item {
                id: tabPart
                objectName: "watchingTabPart"
                y: stage.contentTop
                width: stage.width
                height: stage.height - y
                // In as the picture arrives, a little after it set off.
                opacity: Math.max(0, (frame.glide - 0.25) / 0.75)
                visible: opacity > 0 && !page.cinema
                enabled: page.small

                // Where the picture comes to rest.
                Item {
                    id: miniSlot
                    width: 320
                    height: 180
                }

                Column {
                    id: heading
                    anchors.left: miniSlot.right
                    anchors.leftMargin: 18
                    anchors.right: parent.right
                    y: 4
                    spacing: 6

                    Row {
                        spacing: 10

                        Label {
                            text: page.tab === "recommended" ? "Recommended for" : "Comments on"
                            color: Theme.colors.textMuted
                            font.pixelSize: 12
                        }

                        BusyWord {
                            objectName: "watchingBusy"
                            visible: page.tab === "recommended" ? App.companionBusy
                                                                : App.watchBusy !== ""
                            text: page.tab === "recommended" ? "Asking YouTube"
                                                             : "Reading the comments"
                        }
                    }

                    Label {
                        width: parent.width
                        text: Video.track.title ? Video.track.title : ""
                        color: Theme.colors.text
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        visible: text !== ""
                        text: Video.track.channel ? Video.track.channel : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    Item { width: 1; height: 6; visible: page.tab === "recommended" }

                    // The chips YouTube offers beside the video, the mix
                    // first. The one picked is the same one the companion
                    // page and the music page remember.
                    Flow {
                        objectName: "watchingChips"
                        visible: page.tab === "recommended"
                        width: parent.width
                        spacing: 8

                        Repeater {
                            model: App.watchRecommendedChips

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
                                              ? Theme.wash(Theme.colors.accent, 0.6)
                                              : Theme.colors.border

                                Label {
                                    id: chipWords
                                    anchors.centerIn: parent
                                    text: chip.modelData.label
                                    color: Theme.colors.text
                                    font.pixelSize: 12
                                    font.weight: chip.modelData.chosen ? Font.DemiBold
                                                                       : Font.Normal
                                }

                                HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: App.chooseCompanionChip(chip.modelData.label) }
                            }
                        }

                        FlatButton {
                            objectName: "watchingRefresh"
                            visible: App.watchRecommendedChips.length > 1
                            height: 30
                            text: "Refresh"
                            onClicked: App.refreshCompanion()
                        }
                    }
                }

                // Under the picture and the heading, whichever reaches lower.
                Item {
                    id: tabBody
                    objectName: "watchingTabBody"
                    y: Math.max(miniSlot.height, heading.y + heading.height) + 18
                    width: parent.width
                    height: Math.max(0, parent.height - y)

                    // ---- Recommended ------------------------------------
                    Rectangle {
                        objectName: "watchingRecommendedNote"
                        visible: page.tab === "recommended" && App.watchRecommendedNote !== ""
                        width: parent.width
                        height: visible ? noteWords.implicitHeight + 16 : 0
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
                            text: App.watchRecommendedNote
                            color: Theme.colors.text
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }
                    }

                    GridView {
                        id: tileGrid
                        objectName: "watchingRecommended"
                        visible: page.tab === "recommended"
                        anchors.fill: parent
                        anchors.topMargin: App.watchRecommendedNote !== "" ? 60 : 0
                        clip: true
                        model: App.watchRecommended
                        readonly property int gap: 12
                        readonly property int columns:
                            Math.max(2, Math.floor((width + gap) / (250 + gap)))
                        cellWidth: Math.floor(width / columns)
                        cellHeight: Math.round((cellWidth - gap) * 9 / 16) + gap
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Item {
                            id: cell
                            objectName: "watchingTile"
                            required property var modelData
                            required property int index
                            width: tileGrid.cellWidth
                            height: tileGrid.cellHeight

                            // A press plays it now, the way a card pressed
                            // while a video plays does: straight after this
                            // one, which stays above it as played.
                            VideoTile {
                                width: cell.width - tileGrid.gap
                                height: cell.height - tileGrid.gap
                                title: cell.modelData.title
                                channel: cell.modelData.channel
                                picture: cell.modelData.picture
                                duration: cell.modelData.duration
                                queued: cell.modelData.queued
                                channelLeads: cell.modelData.channelId !== ""
                                onChannelChosen: App.openChannel("yt:" + cell.modelData.channelId)
                                onChosen: App.playWatchRecommended(cell.index)
                                onAskedFor: page.tileMenuRequested(cell.index, cell.modelData.key)
                            }
                        }
                    }

                    SmoothScroll {
                        flickable: tileGrid
                        step: tileGrid.cellHeight * App.scrollRowsPerNotch
                    }

                    // ---- Comments ---------------------------------------
                    //
                    // A column rather than a list view, the way the music
                    // page draws them: more comments arrive as a whole new
                    // answer, and a list view goes back to its top for one.
                    Flickable {
                        id: commentArea
                        objectName: "watchingComments"
                        visible: page.tab === "comments"
                        width: Math.min(parent.width, 860)
                        height: parent.height
                        clip: true
                        contentWidth: width
                        contentHeight: commentColumn.height
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        // A different video's comments are read from the top.
                        Connections {
                            target: Video
                            function onTrackChanged() { commentArea.contentY = 0 }
                        }

                        Column {
                            id: commentColumn
                            width: commentArea.width - 14
                            spacing: 12

                            Label {
                                visible: App.watchComments.length === 0 && App.watchBusy === ""
                                text: "Nothing here"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                            }

                            Repeater {
                                model: App.watchComments
                                CommentThread {
                                    required property var modelData
                                    width: commentColumn.width
                                    comment: modelData
                                    watching: true
                                }
                            }

                            FlatButton {
                                objectName: "watchingMoreComments"
                                visible: App.watchCommentsMore
                                enabled: App.watchBusy === ""
                                text: App.watchBusy === "comments" ? "Loading" : "Show more"
                                onClicked: App.loadMoreWatchComments()
                            }

                            Item { width: 1; height: 4 }
                        }
                    }

                }
            }

            // ---- the picture ---------------------------------------------
            //
            // Over the room kept for it on the Video tab, and small in the
            // corner of every other tab. It travels by being scaled and moved,
            // never resized on the way, the music page's rule for the music
            // page's reason: a box that changes size every frame is a
            // framebuffer made again every frame.
            Item {
                id: frame
                objectName: "watchingFrame"
                z: 3
                readonly property real bigX: videoPart.x + middle.x
                readonly property real bigY: videoPart.y + middle.y
                readonly property real bigW: frameSlot.width
                readonly property real bigH: frameSlot.height
                readonly property real smallX: tabPart.x + miniSlot.x
                readonly property real smallY: tabPart.y + miniSlot.y
                // 0 at rest on the Video tab and 1 in the corner.
                property real glide: page.small ? 1 : 0
                Behavior on glide {
                    enabled: !page.cinema
                    NumberAnimation {
                        id: glideStep
                        duration: 260
                        easing.type: Easing.OutCubic
                    }
                }
                readonly property bool shrunk: glide === 1 && !glideStep.running
                x: bigX + (smallX - bigX) * glide
                y: bigY + (smallY - bigY) * glide
                width: shrunk ? miniSlot.width : bigW
                height: shrunk ? miniSlot.height : bigH
                transformOrigin: Item.TopLeft
                scale: shrunk ? 1 : 1 + (miniSlot.width / Math.max(1, bigW) - 1) * glide
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
                    cursorShape: page.cinema && !page.chromeAwake ? Qt.BlankCursor
                                 : (page.small ? Qt.PointingHandCursor : Qt.ArrowCursor)
                    onHoveredChanged: {
                        page.pointerOverPicture = hovered
                        if (hovered)
                            page.stirControls()
                    }
                    onPointChanged: if (hovered) page.stirControls()
                }

                // A left press pauses and plays, and two fill the screen. The
                // right button does nothing here, though it is taken so that
                // nothing under the picture gets it. Small in the corner of
                // another tab, a press is the way back to the video.
                MouseArea {
                    objectName: "watchingSurface"
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    // Whether the first press of a pair paused or played, so
                    // the second can take that back and only fill the screen,
                    // and whether it was on the big picture at all.
                    property bool tookPause: false
                    property bool onBig: false
                    onClicked: function (mouse) {
                        tookPause = false
                        onBig = false
                        if (mouse.button !== Qt.LeftButton)
                            return
                        if (page.small) {
                            page.choose("video")
                            return
                        }
                        onBig = true
                        // An ended video starts again on a press, which a
                        // second press would only stop.
                        tookPause = !Video.ended && Video.videoShowing
                        Video.toggle()
                    }
                    onDoubleClicked: function (mouse) {
                        if (mouse.button !== Qt.LeftButton || !onBig)
                            return
                        if (tookPause)
                            Video.toggle()
                        tookPause = false
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

                // Pressed in the corner, it takes the page back to the video.
                Rectangle {
                    objectName: "watchingBackToVideo"
                    visible: frame.shrunk
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: 6
                    width: backWords.implicitWidth + 14
                    height: 20
                    radius: 4
                    color: "#c0000000"

                    Label {
                        id: backWords
                        anchors.centerIn: parent
                        text: "▲  Back to the video"
                        color: "#ffffff"
                        font.pixelSize: 10
                    }
                }

                // The queue has run out and the last frame is held.
                FlatButton {
                    objectName: "watchingReplay"
                    anchors.centerIn: parent
                    visible: Video.ended && !page.small
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
                    opacity: page.controlsUp && !page.small ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity {
                        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
                    }
                    onFullscreenToggled: page.fullscreenToggled()
                }

                // SponsorBlock over the picture: a button past the marked part
                // playing, or the word that one was skipped and the way back.
                // Up whether the controls are or not, and above them when they
                // are.
                Rectangle {
                    id: segmentPill
                    objectName: "watchingSegmentPill"
                    readonly property bool skipped: Video.skipNotice !== ""
                    // Named apart from every id on the page, and asked for by the
                    // pill's own name: an id is found before a property of the
                    // item asking, and a bare `words` here read the page's item
                    // of that name, so the pill never went away.
                    readonly property string pillText: segmentPill.skipped
                                                       ? Video.skipNotice : Video.segmentButton
                    visible: segmentPill.pillText !== "" && !page.small
                    anchors.right: parent.right
                    anchors.rightMargin: page.cinema ? 28 : 18
                    y: parent.height - height - (page.controlsUp ? controls.reach + 10 : 18)
                    Behavior on y {
                        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
                    }
                    width: pillWords.implicitWidth + 28
                    height: page.cinema ? 40 : 34
                    radius: 6
                    color: "#d8000000"
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.2)

                    Row {
                        id: pillWords
                        anchors.centerIn: parent
                        spacing: 8

                        Label {
                            objectName: "watchingSegmentWords"
                            text: segmentPill.pillText
                            color: "#f2f2f2"
                            font.pixelSize: page.cinema ? 15 : 13
                            font.weight: Font.DemiBold
                        }
                        Label {
                            visible: segmentPill.skipped
                            text: "\u00b7"
                            color: Qt.rgba(1, 1, 1, 0.6)
                            font.pixelSize: page.cinema ? 15 : 13
                        }
                        // White rather than the accent, which on some themes is
                        // too dark to read on black.
                        Label {
                            visible: segmentPill.skipped
                            text: "Undo"
                            color: "#ffffff"
                            font.pixelSize: page.cinema ? 15 : 13
                            font.weight: Font.DemiBold
                            font.underline: true
                        }
                    }

                    MouseArea {
                        objectName: "watchingSegmentPress"
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: segmentPill.skipped ? Video.undoSkip() : Video.skipSegment()
                    }
                }
            }
        }

        // ---- the queue beside it -------------------------------------------
        Item {
            id: sideCell
            objectName: "watchingSideCell"
            Layout.preferredWidth: page.cinema ? (page.beside ? Math.round(page.width / 6) : 0)
                                               : page.queueWidth
            Layout.maximumWidth: Layout.preferredWidth
            Layout.fillHeight: true
            visible: !page.cinema || page.beside

            // The chat's column beside a picture filling the screen, black
            // like the screen around the picture, whatever the theme.
            Rectangle {
                id: besideHolder
                objectName: "watchingChatBeside"
                anchors.fill: parent
                visible: page.beside
                color: "#000000"
            }
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

        // What the column shows. Filling the screen, the column at the edge
        // is the queue alone; the chat has places of its own there.
        readonly property bool showsChat: page.chatHere && Chat.column === "chat" && !page.cinema

        RowLayout {
            id: queueHead
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 12
            spacing: 8

            Label {
                visible: !page.chatHere || page.cinema
                text: ("Queue" + (Video.queue.length > 0 ? "  ·  " + Video.queue.length : ""))
                      .toUpperCase()
                color: Theme.colors.textMuted
                font.pixelSize: 11
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }

            // A broadcast has a chat as well as a queue, and the column shows
            // one or the other.
            FlatButton {
                objectName: "watchingShowQueue"
                visible: page.chatHere && !page.cinema
                text: "Queue" + (Video.queue.length > 0 ? "  ·  " + Video.queue.length : "")
                accent: !side.showsChat
                onClicked: Chat.setColumn("queue")
            }
            FlatButton {
                objectName: "watchingShowChat"
                visible: page.chatHere && !page.cinema
                text: "Chat"
                accent: side.showsChat
                onClicked: Chat.setColumn("chat")
            }

            Item { Layout.fillWidth: true }

            FlatButton {
                objectName: "watchingQueueClear"
                visible: Video.queue.length > 1 && !side.showsChat
                text: "Clear"
                hint: "Take everything out of the queue except the video playing"
                onClicked: Video.clearQueue()
            }
        }

        // Where the chat sits in the column.
        Item {
            id: chatHolder
            objectName: "watchingChatHolder"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: queueHead.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 8
            anchors.topMargin: 10
            visible: side.showsChat
        }

        QueueList {
            objectName: "watchingQueue"
            visible: !side.showsChat
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

    // ---- the chat, wherever it is shown ------------------------------------
    //
    // One list, moved between its places rather than made again in each, so
    // it keeps what it holds and where it was scrolled to.
    ChatList {
        id: chatView
        parent: page.over ? overBody : (page.beside ? besideHolder : chatHolder)
        anchors.fill: parent
        anchors.margins: page.beside ? 10 : 0
        big: page.cinema
        dark: page.over || page.beside
        animate: page.chatOnScreen
    }

    // ---- the chat over the picture -----------------------------------------
    //
    // A panel inside the filled screen, never a window of its own. Carried by
    // its top, sized by its corners, and kept in shares of the screen, so a
    // screen of another size puts it in the same place.
    Rectangle {
        id: overPanel
        objectName: "watchingChatOver"
        z: 5
        visible: page.over
        readonly property var box: Chat.overBox
        // While the hand holds it, the hand's numbers; the chat's own when let go.
        property bool handled: false
        property real handX: 0
        property real handY: 0
        property real handW: 0
        property real handH: 0
        readonly property real leastW: page.width * 0.08
        readonly property real leastH: page.height * 0.12
        x: handled ? handX : box[0] * page.width
        y: handled ? handY : box[1] * page.height
        width: handled ? handW : box[2] * page.width
        height: handled ? handH : box[3] * page.height
        radius: 4
        color: Qt.rgba(0, 0, 0, 0.6)
        border.width: 1
        border.color: lit ? Theme.colors.accent : "transparent"
        Behavior on border.color { ColorAnimation { duration: 180 } }

        // What carries and sizes it shows while the pointer moves, and goes
        // with the controls when it is still, leaving the chat on its panel.
        readonly property bool lit: page.chromeAwake || handled

        function take() {
            handX = x; handY = y; handW = width; handH = height
            handled = true
        }
        function letGo() {
            Chat.setOverBox(handX / page.width, handY / page.height,
                            handW / page.width, handH / page.height)
            handled = false
        }

        Item {
            id: overHead
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 22
            opacity: overPanel.lit ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 180 } }

            Label {
                anchors.centerIn: parent
                text: "\u22ee\u22ee   Chat   \u22ee\u22ee"
                color: Qt.rgba(1, 1, 1, 0.7)
                font.pixelSize: 11
            }

            MouseArea {
                objectName: "watchingChatOverCarry"
                anchors.fill: parent
                anchors.rightMargin: 26
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                property point from
                property point started
                onPressed: function (mouse) {
                    overPanel.take()
                    from = mapToItem(page, mouse.x, mouse.y)
                    started = Qt.point(overPanel.handX, overPanel.handY)
                }
                onPositionChanged: function (mouse) {
                    var here = mapToItem(page, mouse.x, mouse.y)
                    overPanel.handX = Math.max(0, Math.min(page.width - overPanel.handW,
                                                           started.x + here.x - from.x))
                    overPanel.handY = Math.max(0, Math.min(page.height - overPanel.handH,
                                                           started.y + here.y - from.y))
                }
                onReleased: overPanel.letGo()
                onCanceled: overPanel.letGo()
            }

            Label {
                objectName: "watchingChatOverClose"
                anchors.right: parent.right
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: "\u2715"
                color: closeHover.hovered ? "#ffffff" : Qt.rgba(1, 1, 1, 0.7)
                font.pixelSize: 12
                HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -5
                    onClicked: Chat.setFullMode("full")
                }
            }
        }

        Item {
            id: overBody
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: overHead.bottom
            anchors.bottom: parent.bottom
            anchors.leftMargin: 8
            anchors.rightMargin: 4
            anchors.bottomMargin: 6
        }

        // A corner, which sizes the panel from the other one.
        component Grip: MouseArea {
            id: grip
            // Which corner: -1 for the left or top edge, 1 for the right or
            // bottom one.
            property int across: 1
            property int down: 1
            width: 16
            height: 16
            x: across < 0 ? -4 : overPanel.width - width + 4
            y: down < 0 ? -4 : overPanel.height - height + 4
            cursorShape: across * down > 0 ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
            property point from
            property rect started
            onPressed: function (mouse) {
                overPanel.take()
                from = mapToItem(page, mouse.x, mouse.y)
                started = Qt.rect(overPanel.handX, overPanel.handY, overPanel.handW,
                                  overPanel.handH)
            }
            onPositionChanged: function (mouse) {
                var here = mapToItem(page, mouse.x, mouse.y)
                var dx = here.x - from.x
                var dy = here.y - from.y
                if (across > 0) {
                    overPanel.handW = Math.max(overPanel.leastW,
                                               Math.min(page.width - started.x, started.width + dx))
                } else {
                    var left = Math.max(0, Math.min(started.x + started.width - overPanel.leastW,
                                                    started.x + dx))
                    overPanel.handX = left
                    overPanel.handW = started.x + started.width - left
                }
                if (down > 0) {
                    overPanel.handH = Math.max(overPanel.leastH,
                                               Math.min(page.height - started.y, started.height + dy))
                } else {
                    var top = Math.max(0, Math.min(started.y + started.height - overPanel.leastH,
                                                   started.y + dy))
                    overPanel.handY = top
                    overPanel.handH = started.y + started.height - top
                }
            }
            onReleased: overPanel.letGo()
            onCanceled: overPanel.letGo()

            Rectangle {
                width: 8
                height: 8
                x: grip.across < 0 ? 4 : grip.width - width - 4
                y: grip.down < 0 ? 4 : grip.height - height - 4
                color: Theme.colors.accent
                opacity: grip.containsMouse || grip.pressed ? 1 : (overPanel.lit ? 0.6 : 0)
                Behavior on opacity { NumberAnimation { duration: 180 } }
            }
            hoverEnabled: true
        }

        Grip { objectName: "watchingChatOverGrip"; across: -1; down: -1 }
        Grip { across: 1; down: -1 }
        Grip { across: -1; down: 1 }
        Grip { across: 1; down: 1 }
    }
}
