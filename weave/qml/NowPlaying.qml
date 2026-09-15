import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Weave 1.0

// The page about the song that is playing. The picture in the middle, what is
// known about it underneath, and everything that belongs beside it in one
// column on the right.
//
// The middle keeps the shape a video will have even when there is no video, so
// that a station of songs and a station of music videos do not shuffle the page
// between them every time the track changes.
Item {
    id: page
    objectName: "nowPlayingView"

    // Wanted, rather than shown. The page stays drawn for as long as it takes
    // to drop back into the bar, or leaving it would be a disappearance rather
    // than a movement.
    readonly property bool wanted: App.viewKind === "nowplaying"
    // Only after it has been opened once. The height arrives after the first
    // layout, and that first change of it animates the offset from nothing to
    // a full page down, which would show the page sliding past on the way to
    // somewhere nobody asked it to go.
    property bool everShown: false
    onWantedChanged: {
        if (wanted)
            everShown = true
        // Nothing is fetched and nothing decoded until this is true, so the
        // page being open is the whole cost of being able to show a picture.
        Audio.setVideoWanted(wanted)
        // And ask the surface to draw once. It builds its render context on a
        // paint, and it has no reason of its own to paint again: the only one
        // it gets is at startup, before there is a player, where it correctly
        // gives up. Without this nudge it never draws again, the context is
        // never built, and mpv says only "No render context set" for ever.
        if (wanted)
            videoSurface.update()
    }
    // Never hidden, only moved out of sight and clipped away by the wrapper
    // around it.
    //
    // Hiding it takes the whole page out of the scene, and the video surface
    // with it, whose renderer Qt then destroys and whose graphics resources it
    // hands back. Building those again is a cost paid at exactly the moment
    // the page is moving, in both directions, which is what was felt as the
    // whole window catching. Left in the scene it is laid out once and drawn
    // only when something changes, which while it is away is never.
    visible: true

    // A transform rather than a real move, so nothing is laid out again while
    // it travels and whatever is drawn inside is only offset. The clipping is
    // done by the wrapper around this, which is what makes it come out from
    // behind the music bar rather than over it.
    transform: Translate {
        id: shift
        y: page.wanted ? 0 : page.height
        Behavior on y {
            // Not before it has been opened once. The height arrives after the
            // first layout, and animating that first change would slide the
            // page up from nowhere on the way to somewhere nobody asked it to
            // go, which is what the flag below was always guarding against.
            enabled: page.everShown
            NumberAnimation {
                id: slideStep
                duration: 190
                easing.type: Easing.OutCubic
            }
        }
    }

    // Its own ground, because the page travels over whatever it was opened
    // from. Left transparent, the view behind shows through for the length of
    // the slide, which is half of every close.
    ThemeBackground {
        anchors.fill: parent
        z: -1
    }

    // Under this the column on the right does not fit beside a picture worth
    // looking at, so it keeps only its tabs. Raising the window's own minimum
    // instead would be taking the size of the window away from the person
    // using it.
    // Travelling. The picture is drawn throughout, and rides along with the
    // page. Drawing it costs one draw a frame now that the player's render
    // call no longer waits for the frame's display time; what used to be felt
    // as the whole window catching was that wait, and then the player's own
    // thread waiting on frames nobody collected while the surface was quiet.
    readonly property bool sliding: slideStep.running
    onSlidingChanged: {
        // Back to drawing once it has settled. The surface has no reason of
        // its own to paint again, so it is asked, exactly as it is on opening.
        if (!sliding && wanted)
            videoSurface.update()
    }

    readonly property bool roomForColumn: width >= 1100
    property string tab: "next"

    // Asked every time the tab is opened. Whether that costs a request is not
    // decided here: this side cannot tell a press that started something from
    // one that was turned away because another tab was still loading, and
    // remembering the second kind as asked left that tab empty for good.
    function choose(name) {
        page.tab = name
        if (name === "words")
            App.readNowSide("words")
        else if (name === "related")
            App.readNowSide("related")
        else if (name === "comments")
            App.readNowComments()
    }

    // A different song has different words beside it, so whatever was open is
    // asked for again rather than showing the last song's answer.
    Connections {
        target: Audio
        function onTrackChanged() {
            if (page.tab !== "next")
                page.choose(page.tab)
        }

        // A whole list put on is a fresh start, and what is beside a song from
        // the list before it is not worth keeping open. The queue is what
        // somebody wants to see at that moment anyway.
        function onQueueReplaced() {
            page.tab = "next"
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 16

        // ---- the picture and what is known about it ----------------------
        Item {
            id: stage
            objectName: "nowPlayingStage"
            Layout.fillWidth: true
            Layout.fillHeight: true

            // The picture and the words about it move together, so the words
            // sit under the picture rather than at the foot of the window with
            // a field of nothing between them.
            Column {
                id: middle
                // Level with the row of tabs beside it rather than floating in
                // the middle of the space under them.
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                width: frame.width
                spacing: 12

                // The box a video will fill, sixteen by nine, as large as what
                // is left once the words have taken their room. It is reserved
                // whether or not there is a video, so a song and a music video
                // do not resize the page between them.
                //
                // Nothing is drawn for the box itself. An empty bordered panel
                // around a square picture reads as a picture that failed to
                // fill it, which is what the first drawing of this looked like.
                Item {
                    id: frame
                    objectName: "nowPlayingFrame"
                    readonly property real spare: stage.height - words.height
                                                  - middle.spacing
                    readonly property real room: Math.min(stage.width,
                                                          Math.max(90, spare) * 16 / 9)
                    width: Math.max(160, room)
                    height: width * 9 / 16
                    clip: true

                    // The video, underneath, and drawing from the moment the
                    // page opens rather than from the moment there is
                    // something to see.
                    //
                    // That order is load bearing. The surface builds its
                    // render context on its first paint, mpv refuses to decode
                    // video until that context exists, and a frame is what the
                    // page would otherwise be waiting for before drawing the
                    // surface at all. Shown only once a frame existed, nothing
                    // would ever paint, nothing would build, and no frame would
                    // ever come.
                    VideoSurface {
                        id: videoSurface
                        objectName: "nowPlayingVideo"
                        anchors.fill: parent
                        // Never hidden. Hiding a framebuffer item makes Qt
                        // destroy its renderer and hand the graphics resources
                        // back, and building them again is a cost paid exactly
                        // when the page is moving. It stays, and draws for as
                        // long as any of it can be seen, which includes the
                        // slide out. Frames keep being collected either way.
                        drawing: page.wanted || page.sliding
                    }

                    // Square cover art over it, at its own shape, until there
                    // is a picture underneath worth uncovering. Stretching it
                    // to the corners would be inventing picture that was never
                    // there, and swapping sooner shows a black box for the two
                    // and a half seconds a frame takes to exist.
                    Rectangle {
                        anchors.fill: parent
                        color: Theme.colors.background
                        // Out of the way once there is a picture underneath.
                        // Faded rather than switched, since the picture arrives
                        // a couple of seconds in and a hard cut draws the eye
                        // to exactly the wrong moment. It stays out of the way
                        // while the page moves, so the picture travels with it.
                        opacity: Audio.videoShowing ? 0 : 1
                        visible: opacity > 0
                        Behavior on opacity {
                            NumberAnimation { duration: 320
                                              easing.type: Easing.InOutQuad }
                        }

                        RoundedImage {
                            objectName: "nowPlayingArtwork"
                            anchors.centerIn: parent
                            height: parent.height
                            width: height
                            radius: 8
                            visible: (Audio.track.thumbnail || "") !== ""
                            source: Audio.track.thumbnail ? Audio.track.thumbnail : ""
                        }

                        Label {
                            anchors.centerIn: parent
                            visible: (Audio.track.thumbnail || "") === ""
                            text: "No picture"
                            color: Theme.colors.textMuted
                            font.pixelSize: 12
                        }
                    }

                    // The picture is where the pointer already is, so it takes
                    // the two things worth doing without moving it. Either
                    // button, because reaching for the wrong one and having
                    // nothing happen is worse than both doing the same thing.
                    MouseArea {
                        objectName: "nowPlayingSurface"
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: Audio.toggle()

                        // A notch is five, the same as the bar's own slider,
                        // so the two do not disagree about what a notch means.
                        WheelHandler {
                            acceptedDevices: PointerDevice.Mouse
                                             | PointerDevice.TouchPad
                            property real carried: 0
                            onWheel: function (event) {
                                carried += event.angleDelta.y
                                while (carried >= 120) {
                                    carried -= 120
                                    Audio.nudgeVolume(1)
                                }
                                while (carried <= -120) {
                                    carried += 120
                                    Audio.nudgeVolume(-1)
                                }
                            }
                        }
                    }
                }

                // ---- the words under the picture -------------------------
                Column {
                    id: words
                    width: parent.width
                    spacing: 2

                    Label {
                        objectName: "nowPlayingTitle"
                        width: parent.width
                        text: Audio.track.title ? Audio.track.title : ""
                        color: Theme.colors.text
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Label {
                        id: artistLine
                        objectName: "nowPlayingArtist"
                        // Pressed, it goes to whoever made this, on their
                        // music. Only where the song carries an address for
                        // them, which a song from an ordinary video does not.
                        readonly property string leadsTo:
                            Audio.track.artistId ? Audio.track.artistId : ""
                        width: parent.width
                        visible: text !== ""
                        text: Audio.track.artist ? Audio.track.artist : ""
                        color: leadsTo !== "" && artistHover.hovered
                               ? Theme.colors.text : Theme.colors.textMuted
                        font.pixelSize: 13
                        font.underline: leadsTo !== "" && artistHover.hovered
                        elide: Text.ElideRight

                        HoverHandler {
                            id: artistHover
                            enabled: artistLine.leadsTo !== ""
                            cursorShape: Qt.PointingHandCursor
                        }

                        // Only as wide as the words, so the empty half of the
                        // line is not a target for something invisible.
                        MouseArea {
                            enabled: artistLine.leadsTo !== ""
                            width: Math.min(artistLine.implicitWidth, parent.width)
                            height: parent.height
                            onClicked: App.openArtistMusic(artistLine.leadsTo)
                        }
                    }

                    Item { width: 1; height: 4 }

                    // Views and the date are known only for a song that is also
                    // a video here. A song that exists only in the music service
                    // has no row among the videos and so says nothing, which is
                    // the ordinary case rather than a failure.
                    Label {
                        objectName: "nowPlayingFacts"
                        width: parent.width
                        visible: text !== ""
                        text: {
                            var bits = []
                            var d = App.nowDetail
                            if (d.channelTitle)
                                bits.push(d.channelTitle)
                            if (d.viewsText)
                                bits.push(d.viewsText + " views")
                            // Likes arrive with the comments call, so the line
                            // grows once that tab has been opened and never
                            // asks for them on its own.
                            if (d.likesText)
                                bits.push(d.likesText + " likes")
                            if (d.ageText)
                                bits.push(d.ageText)
                            return bits.join("  ·  ")
                        }
                        color: Theme.colors.textMuted
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Label {
                        objectName: "nowPlayingVideoNote"
                        width: parent.width
                        visible: text !== "" && !Audio.videoShowing
                        text: Audio.videoNote
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }

                    Item { width: 1; height: 6 }

                    // A track that is really several songs says so, and the
                    // whole list of them is one press away.
                    FlatButton {
                        objectName: "nowPlayingChaptersButton"
                        visible: Audio.chapters.length > 0
                        text: (chapterList.visible ? "Hide the songs in it  ·  "
                                                   : "Songs in it  ·  ")
                              + Audio.chapters.length
                        onClicked: chapterList.visible = !chapterList.visible
                    }

                    ListView {
                        id: chapterList
                        objectName: "nowPlayingChapters"
                        visible: false
                        width: parent.width
                        height: visible ? Math.min(150, contentHeight) : 0
                        clip: true
                        model: Audio.chapters
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Label {
                            required property var modelData
                            width: chapterList.width
                            padding: 3
                            text: modelData.title ? modelData.title : ""
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        // ---- everything that belongs beside the song ---------------------
        ColumnLayout {
            id: side
            objectName: "nowPlayingSide"
            Layout.preferredWidth: page.roomForColumn ? 360 : 190
            Layout.maximumWidth: page.roomForColumn ? 360 : 190
            Layout.fillHeight: true
            spacing: 10

            // The tabs themselves are always there. In a narrow window they are
            // most of what is there, which is what keeps the picture worth
            // looking at on a small screen.
            Flow {
                Layout.fillWidth: true
                spacing: 6

                Repeater {
                    model: [{ name: "next", label: "Next" },
                            { name: "words", label: "Lyrics" },
                            { name: "comments", label: "Comments" },
                            { name: "related", label: "Related" }]
                    FlatButton {
                        required property var modelData
                        objectName: "nowPlayingTab_" + modelData.name
                        text: modelData.label
                        accent: page.tab === modelData.name
                        onClicked: page.choose(modelData.name)
                    }
                }
            }

            Label {
                objectName: "nowPlayingBusy"
                Layout.fillWidth: true
                visible: App.nowBusy !== ""
                text: App.nowBusy === "comments" ? "Reading the comments"
                                                 : "Reading"
                color: Theme.colors.textMuted
                font.pixelSize: 11
            }

            // ---- Next ----------------------------------------------------
            QueueList {
                objectName: "nowPlayingQueue"
                visible: page.tab === "next"
                Layout.fillWidth: true
                Layout.fillHeight: true
                rowHeight: 48
            }

            // ---- Lyrics --------------------------------------------------
            Flickable {
                objectName: "nowPlayingWords"
                visible: page.tab === "words"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: width
                contentHeight: wordsColumn.height
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Column {
                    id: wordsColumn
                    width: parent.width
                    spacing: 8

                    Label {
                        width: parent.width
                        // Whatever the music service returns for this song, as
                        // it returns it.
                        text: App.nowWords.text ? App.nowWords.text : ""
                        visible: text !== ""
                        color: Theme.colors.text
                        font.pixelSize: 12
                        lineHeight: 1.35
                        wrapMode: Text.Wrap
                    }
                    Label {
                        width: parent.width
                        visible: (App.nowWords.source || "") !== ""
                        text: App.nowWords.source ? App.nowWords.source : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                    Label {
                        width: parent.width
                        // A song with none is a normal answer. The page says so
                        // plainly rather than sitting empty as if it had failed.
                        visible: App.nowBusy === ""
                                 && App.nowRead.indexOf("words") >= 0
                                 && !App.nowWords.text
                        text: "No words for this one"
                        color: Theme.colors.textMuted
                        font.pixelSize: 12
                    }
                }
            }

            // ---- Comments ------------------------------------------------
            ListView {
                id: commentList
                objectName: "nowPlayingComments"
                visible: page.tab === "comments"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 12
                model: App.nowComments
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: CommentThread {
                    required property var modelData
                    width: ListView.view.width
                    comment: modelData
                }

                Label {
                    anchors.centerIn: parent
                    visible: commentList.count === 0 && App.nowBusy === ""
                    text: "Nothing here"
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                }
            }

            // ---- Related -------------------------------------------------
            ListView {
                id: relatedList
                objectName: "nowPlayingRelated"
                visible: page.tab === "related"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 2
                model: App.nowRelated
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // Handed down, because a delegate cannot see an id declared
                // around it and reaching for one raises a reference error.
                property var owner: relatedMenu

                delegate: Rectangle {
                    id: relatedRow
                    required property var modelData
                    required property int index
                    width: relatedList.width
                    height: 48
                    radius: 5
                    color: relatedHover.hovered ? Theme.colors.surface : "transparent"

                    HoverHandler { id: relatedHover }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: function (mouse) {
                            if (mouse.button === Qt.RightButton) {
                                var menu = relatedRow.ListView.view.owner
                                menu.row = relatedRow.index
                                menu.popup()
                                return
                            }
                            App.playNowRelated(relatedRow.index)
                        }
                    }

                    Row {
                        anchors.fill: parent
                        anchors.margins: 4
                        spacing: 8

                        RoundedImage {
                            width: 38
                            height: 38
                            radius: 4
                            anchors.verticalCenter: parent.verticalCenter
                            visible: (relatedRow.modelData.thumbnail || "") !== ""
                            source: relatedRow.modelData.thumbnail
                                    ? relatedRow.modelData.thumbnail : ""
                        }

                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 50
                            spacing: 1
                            Label {
                                width: parent.width
                                text: relatedRow.modelData.title
                                color: Theme.colors.text
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            Label {
                                id: relatedArtist
                                readonly property string leadsTo:
                                    relatedRow.modelData.artistId
                                    ? relatedRow.modelData.artistId : ""
                                width: parent.width
                                visible: (relatedRow.modelData.artist || "") !== ""
                                text: relatedRow.modelData.artist
                                color: leadsTo !== "" && relatedArtistHover.hovered
                                       ? Theme.colors.text : Theme.colors.textMuted
                                font.pixelSize: 10
                                font.underline: leadsTo !== ""
                                                && relatedArtistHover.hovered
                                elide: Text.ElideRight

                                HoverHandler {
                                    id: relatedArtistHover
                                    enabled: relatedArtist.leadsTo !== ""
                                    cursorShape: Qt.PointingHandCursor
                                }

                                // A MouseArea, because the row's own press is
                                // underneath and a handler would not consume
                                // this one, so both would fire.
                                MouseArea {
                                    enabled: relatedArtist.leadsTo !== ""
                                    width: Math.min(relatedArtist.implicitWidth,
                                                    parent.width)
                                    height: parent.height
                                    onClicked: App.openArtistMusic(relatedArtist.leadsTo)
                                }
                            }
                        }
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: relatedList.count === 0 && App.nowBusy === ""
                    // Not asked yet reads differently from asked and empty,
                    // and saying the wrong one of those is how a tab that was
                    // never fetched looked like an answer.
                    text: App.nowRead.indexOf("related") >= 0
                          ? "Nothing like this one" : "Reading"
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                }
            }

            ThemedMenu {
                id: relatedMenu
                objectName: "nowPlayingRelatedMenu"
                property int row: -1

                ThemedMenuItem {
                    text: "Play next"
                    onTriggered: {
                        App.queueNowRelated(relatedMenu.row, true)
                        relatedMenu.dismiss()
                    }
                }
                ThemedMenuItem {
                    text: "Add to the queue"
                    onTriggered: {
                        App.queueNowRelated(relatedMenu.row, false)
                        relatedMenu.dismiss()
                    }
                }
            }
        }
    }
}
