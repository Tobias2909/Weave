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

    // Whether the window is filled by this page, and whether the bar and the
    // corner button are up. Both are decided by the window and handed down: a
    // component in its own file cannot see an id declared in the one that
    // uses it.
    property bool cinema: false
    property bool chromeAwake: true
    // What the music bar takes at the foot of the screen. The column beside
    // the song stops above it rather than running under it, or the bottom
    // corner of the screen brings up both of them and they overlap. Handed
    // down for the same reason the two above are: this file cannot see an id
    // declared in the one that uses it.
    property real barRoom: 0
    // Asked of the window, which owns the shape. The page never calls
    // showFullScreen itself.
    signal fullscreenToggled()

    // Whether the pointer is in the right fifth of the screen, which is what
    // brings the column beside the song back while the screen is filled. The
    // bar at the bottom answers to movement anywhere; this answers to being
    // near it, so the rest of the time there is nothing over the picture.
    property bool sideNear: false
    readonly property bool sideAwake: page.cinema && page.sideNear

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
        // Not "row": a property somewhere else in this file is called that,
        // and a property that shares the name of an id loses to it. There is
        // a test that says so.
        id: pageRow
        anchors.fill: parent
        // Right to the edges when the screen is filled. A margin there is a
        // frame drawn around a picture that was asked to be the whole screen.
        anchors.margins: page.cinema ? 0 : 16
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
                // the middle of the space under them. With the screen filled
                // there are no tabs to be level with and nothing under the
                // picture, so it sits in the middle of the screen instead of
                // at the top of it with a black band below.
                //
                // Put where it goes by hand rather than by swapping one
                // anchor for another. Two vertical anchors at once, a top and
                // a centre, is a combination Qt answers by SETTING THE
                // HEIGHT, and two bindings are evaluated one after the other,
                // so the moment between them is exactly that combination. The
                // height written there stuck, because an item whose height
                // has been set once stops following what is inside it, and
                // every filled screen after the first drew the picture pushed
                // down with a band of nothing above it.
                anchors.horizontalCenter: parent.horizontalCenter
                y: page.cinema ? Math.round((parent.height - height) / 2) : 0
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
                    // What is left once the words have taken their room, and
                    // the whole of it when there are no words.
                    readonly property real spare: words.visible
                        ? stage.height - words.height - middle.spacing
                        : stage.height
                    readonly property real room: Math.min(stage.width,
                                                          Math.max(90, spare) * 16 / 9)
                    // Sixteen by nine on the page, because the box is reserved
                    // whether or not there is a video in it and a song and a
                    // music video must not resize the page between them. With
                    // the screen filled there is nothing else on the screen to
                    // keep still for, so the box IS the screen and the picture
                    // inside it keeps its own shape, which is mpv's to hold.
                    width: page.cinema ? stage.width : Math.max(160, room)
                    height: page.cinema ? stage.height : width * 9 / 16
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
                        // A fade is there to cover the couple of seconds a
                        // stream takes to put up its first frame. A picture
                        // kept on disk has one in a moment, so there is
                        // nothing to cover and the artwork simply goes.
                        Behavior on opacity {
                            NumberAnimation { duration: Audio.videoInstant ? 0 : 320
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
                        // Goes away with the bar. A pointer left sitting on a
                        // picture filling the screen is the one thing left
                        // saying this is a window.
                        cursorShape: page.cinema && !page.chromeAwake
                                     ? Qt.BlankCursor : Qt.ArrowCursor

                        // One press stops and starts the music, two fill the
                        // screen, and two never do both.
                        //
                        // Qt cannot know a second press is coming until it has
                        // been made, so the first press is held for as long as
                        // the system gives a double press to arrive in, and
                        // dropped if one does. Undoing the first press instead
                        // was tried and is wrong: the release of the second
                        // press is a press of its own, so the music stopped
                        // anyway.
                        onClicked: pressWait.restart()
                        onDoubleClicked: {
                            pressWait.stop()
                            page.fullscreenToggled()
                        }

                        Timer {
                            id: pressWait
                            interval: Qt.styleHints.mouseDoubleClickInterval
                            onTriggered: Audio.toggle()
                        }

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
                    objectName: "nowPlayingWords"
                    // Nothing under the picture while the screen is filled.
                    visible: !page.cinema
                    width: parent.width
                    spacing: 2

                    // The face of whoever made it stands beside what it is
                    // rather than over or under it. Three short rows read as
                    // one block when something holds them together on the
                    // left, and the switch that belongs to the picture sits
                    // at the far end of the first of them.
                    Row {
                        width: parent.width
                        spacing: 10

                        RoundedImage {
                            id: avatar
                            objectName: "nowPlayingAvatar"
                            // As tall as the three rows it stands beside.
                            // Measured from them rather than written down, so
                            // it still matches if any of those sizes change.
                            // None of their heights depends on how wide this
                            // is, since every one of them elides rather than
                            // wraps, so reading them here is not a circle.
                            width: height
                            height: Math.max(40, Math.min(96, titleRow.height
                                             + artistLine.height + factsLine.height
                                             + 2 * said.spacing))
                            // Round, the way a channel's face is drawn on
                            // every card in the window.
                            circle: true
                            // A channel Weave already follows has a face
                            // stored. One it does not has none anywhere short
                            // of a request, and gets none rather than a hole
                            // where a picture should be.
                            //
                            // Asked of the address as it arrives rather than
                            // of the picture's own source. That one is a URL
                            // by the time it is read back, and a URL is never
                            // equal to an empty string, so an empty one left
                            // this visible and held a round hole open beside
                            // every song whose channel is a stranger.
                            readonly property string face:
                                App.nowDetail.channelAvatar
                                ? App.nowDetail.channelAvatar : ""
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
                                    objectName: "nowPlayingTitle"
                                    width: parent.width - audioOnly.width
                                           - fillScreen.width - titleRow.spacing * 2
                                    text: Audio.track.title ? Audio.track.title : ""
                                    color: Theme.colors.text
                                    font.pixelSize: 19
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }

                                // Sound alone, and remembered. On, no picture
                                // is ever resolved and none is decoded, which
                                // measured at 0 KiB and a fifth of a percent
                                // of a core against 2411 kbit/s and nine
                                // percent with one. Up here because it is
                                // about the picture above it rather than
                                // about the words it used to sit under.
                                FlatButton {
                                    id: audioOnly
                                    objectName: "nowPlayingAudioOnly"
                                    text: "Audio only"
                                    accent: Audio.audioOnly
                                    onClicked: Audio.setAudioOnly(!Audio.audioOnly)
                                }

                                // The way in that can be found by looking. The
                                // ways out are the corner button, Escape, F
                                // and another double press, and this row is
                                // not drawn while the screen is filled.
                                FlatButton {
                                    id: fillScreen
                                    objectName: "nowPlayingFullscreen"
                                    text: "Fullscreen"
                                    onClicked: page.fullscreenToggled()
                                }
                            }

                            Label {
                                id: artistLine
                                objectName: "nowPlayingArtist"
                                // Pressed, it goes to whoever made this, on
                                // their music. Only where the song carries an
                                // address for them, which a song from an
                                // ordinary video does not.
                                readonly property string leadsTo:
                                    Audio.track.artistId ? Audio.track.artistId : ""
                                width: parent.width
                                visible: text !== ""
                                // What the music service filed it under, or
                                // failing that what the extraction named,
                                // which is how an ordinary video played as
                                // music gets a line here.
                                text: Audio.track.artist ? Audio.track.artist
                                                         : (App.nowDetail.artistText
                                                            ? App.nowDetail.artistText : "")
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

                                // Only as wide as the words, so the empty half
                                // of the line is not a target for something
                                // invisible.
                                MouseArea {
                                    enabled: artistLine.leadsTo !== ""
                                    width: Math.min(artistLine.implicitWidth, parent.width)
                                    height: parent.height
                                    onClicked: App.openArtistMusic(artistLine.leadsTo)
                                }
                            }

                            // Who made it and how it has been received. A song
                            // that is also a video Weave follows answers from
                            // what is stored; for every other one the resolve
                            // that found the address answers, since it is a
                            // full extraction whatever is printed and so costs
                            // nothing to ask. Empty only until that resolve
                            // comes back, a few seconds after the press.
                            Label {
                                id: factsLine
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

                            // The rest of what the same call carried. Its own
                            // line and a size smaller, because an album and a
                            // category are what you read second, and one line
                            // of eight things separated by dots is a line
                            // nobody reads at all.
                            Label {
                                objectName: "nowPlayingMoreFacts"
                                width: parent.width
                                visible: text !== ""
                                text: {
                                    var bits = []
                                    var d = App.nowDetail
                                    if (d.albumText)
                                        bits.push(d.albumText)
                                    if (d.commentsText)
                                        bits.push(d.commentsText + " comments")
                                    if (d.followersText)
                                        bits.push(d.followersText + " subscribers")
                                    if (d.categoryText)
                                        bits.push(d.categoryText)
                                    return bits.join("  ·  ")
                                }
                                color: Theme.colors.textMuted
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }
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

                    Item { width: 1; height: 4 }

                    // What was written under the video, in the same call that
                    // found the address. Two lines at rest and eight when it
                    // is pressed, because the picture is given whatever room
                    // the words leave and a long description would shrink it
                    // to nothing. Anything past eight lines belongs on a page
                    // of its own rather than under a song.
                    Label {
                        id: description
                        objectName: "nowPlayingDescription"
                        property bool open: false
                        width: parent.width
                        visible: text !== ""
                        text: App.nowDetail.descriptionText
                              ? App.nowDetail.descriptionText : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        maximumLineCount: open ? 8 : 2
                        elide: Text.ElideRight
                        // Already markup when it arrives, addresses and all,
                        // and always markup even when there is nothing in it
                        // to press. Told once rather than switched between
                        // two formats, which would lay the page out again on
                        // every song.
                        textFormat: Text.StyledText
                        linkColor: Theme.colors.accent

                        // A different song is a different description, and one
                        // left open would open the next one at whatever length
                        // it happens to be.
                        Connections {
                            target: Audio
                            function onTrackChanged() { description.open = false }
                        }

                        // One handler for both things the words do, because
                        // two would fight over the press. An address under the
                        // pointer wins: opening it is what somebody aiming at
                        // it meant, and the rest of the words still open and
                        // close the paragraph.
                        MouseArea {
                            id: descriptionPress
                            anchors.fill: parent
                            hoverEnabled: true
                            property string link: ""
                            property bool foldable: description.truncated
                                                    || description.open
                            onPositionChanged: function (mouse) {
                                link = description.linkAt(mouse.x, mouse.y)
                            }
                            onExited: link = ""
                            cursorShape: (link !== "" || foldable)
                                         ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: function (mouse) {
                                var here = description.linkAt(mouse.x, mouse.y)
                                if (here !== "") {
                                    App.openLink(here)
                                    return
                                }
                                if (foldable)
                                    description.open = !description.open
                            }
                        }
                    }

                    Item { width: 1; height: 6 }

                    // A track that is really several songs says so, and the
                    // whole list of them is one press away.
                    FlatButton {
                        objectName: "nowPlayingChaptersButton"
                        visible: Audio.chapters.length > 0
                        text: (chapterList.visible ? "Hide the chapters  ·  "
                                                   : "Chapters  ·  ")
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
                        // A chapter is a place in the track, so pressing one
                        // goes there. The list already knows where each one
                        // begins as a fraction of the whole, which is what the
                        // marks on the bar are drawn from and what a seek
                        // takes, so the two can never disagree.
                        delegate: Label {
                            required property var modelData
                            required property int index
                            width: chapterList.width
                            padding: 3
                            text: modelData.title ? modelData.title : ""
                            // The one being played is named in its own colour,
                            // so the list says where you are as well as where
                            // you can go.
                            color: hereNow ? Theme.colors.accent
                                           : (chapterHover.hovered ? Theme.colors.text
                                                                   : Theme.colors.textMuted)
                            readonly property bool hereNow:
                                Audio.currentChapter !== ""
                                && Audio.currentChapter === modelData.title
                            font.pixelSize: 11
                            elide: Text.ElideRight

                            HoverHandler {
                                id: chapterHover
                                cursorShape: Qt.PointingHandCursor
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: Audio.seek(modelData.at)
                            }
                        }
                    }
                }
            }
        }

        // ---- everything that belongs beside the song ---------------------
        // The room the column takes beside the picture on the page. Empty, and
        // no width at all when the screen is filled, which is what lets the
        // picture have the whole of it.
        Item {
            id: sideCell
            objectName: "nowPlayingSideCell"
            Layout.preferredWidth: page.cinema ? 0
                                               : (page.roomForColumn ? 360 : 190)
            Layout.maximumWidth: Layout.preferredWidth
            Layout.fillHeight: true
            visible: !page.cinema
        }
    }

    ColumnLayout {
        id: side
        objectName: "nowPlayingSide"
        // It sits in the room beside the picture on the page, and over the
        // picture when the screen is filled. ONE column either way: two would
        // have drifted apart the first time either of them grew.
        //
        // Both homes are plain items, never the row itself. A child of a
        // layout may not be anchored -- "Cannot anchor to an item that isn't
        // a parent or sibling" -- and anchoring to its own parent is the only
        // shape that is legal in both.
        parent: page.cinema ? sideSlot : sideCell
        anchors.fill: parent
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

    // Where the column beside the song is drawn when the screen is filled.
    // Empty on the page itself: the column is a cell of the row there and
    // comes here only while there is a screen to draw it over.
    Item {
        id: sideSlot
        objectName: "nowPlayingSideSlot"
        z: 4
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 16
        // Clear of the bar at the bottom, which is drawn over this and comes
        // up at the same movement that brings this back. The room is kept
        // whether the bar is awake or not, so the column does not lay itself
        // out again every time the bar goes to sleep under it.
        anchors.bottomMargin: 16 + page.barRoom
        // The right fifth of the screen, which is the strip that brings it
        // back, so what appears is exactly where the hand already is.
        width: Math.max(300, page.width / 5 - 32)
        visible: opacity > 0
        opacity: page.sideAwake ? 1 : 0
        // Nothing to press while it is not there, so a column nobody can see
        // cannot take a press meant for the picture behind it.
        enabled: page.sideAwake
        Behavior on opacity {
            NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
        }

        // Something to read the words against. First here, so the column
        // itself, which arrives as a child later, is drawn over it.
        Rectangle {
            anchors.fill: parent
            anchors.margins: -12
            radius: 12
            readonly property color panel: Qt.color(Theme.colors.surface)
            color: Qt.rgba(panel.r, panel.g, panel.b, 0.88)
            border.width: 1
            border.color: Theme.colors.border
        }
    }

    // Which fifth of the screen the pointer is in. The place on the screen is
    // read rather than trusted to the signal: onPointChanged is raised by
    // anything about the point changing, a layout settling included, and the
    // position is reported relative to this item, so it is recomputed every
    // time rather than treated as a report that the hand moved.
    HoverHandler {
        id: sideWatch
        objectName: "nowPlayingSideWatch"
        enabled: page.cinema
        onPointChanged: {
            // Only while something is actually over the page. The signal is
            // raised by anything about the point changing, a layout settling
            // included, and a point reported while nothing is hovering says
            // nothing about where a hand is.
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
            // A hand that was here and has gone takes the column with it.
            // Hover reported as lost when nothing was ever over the page is
            // not a hand leaving: it happens whenever the scene recomputes,
            // which this does the moment the column itself appears.
            if (!sideWatch.everHere)
                return
            sideWatch.everHere = false
            page.sideNear = false
        }
    }

    // The way back, in the corner, up and away with the bar at the other end
    // of the screen. Last in the file and with a z of its own, so it is over
    // the picture whatever else is drawn: the picture is the whole page here.
    FlatButton {
        objectName: "nowPlayingLeaveFullscreen"
        z: 5
        anchors.top: parent.top
        // Out of the right fifth, where the column comes back, so the two are
        // never in each other's way.
        anchors.right: sideSlot.left
        anchors.margins: 16
        text: "Leave fullscreen"
        visible: opacity > 0
        opacity: page.cinema && page.chromeAwake ? 1 : 0
        onClicked: page.fullscreenToggled()
        Behavior on opacity {
            NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
        }
    }
}
