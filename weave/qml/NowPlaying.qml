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
    //
    // It is the window's own ground, held still against the window while the
    // page travels over it, so that what the page is painted at any height is
    // what the window is painted there. Painted in the page's own box instead,
    // it carried the colours of the arrived page the whole way up, and on a
    // washed theme, which is twelve of the fourteen shipped, that is a band of
    // the wrong colour crossing the window with a seam along its top edge.
    //
    // The clip is what keeps it to the page. The ground is the size of the
    // whole window and placed against the window rather than against the page,
    // so with nothing cutting it back to the page's own box it would go on
    // covering the view behind while the page is away.
    Item {
        objectName: "nowPlayingGroundClip"
        anchors.fill: parent
        clip: true
        z: -1

        ThemeBackground {
            objectName: "nowPlayingGround"
            // Where the page sits in the window, and the slide undone: the
            // transform above moves everything drawn inside the page along
            // with it, and this is the one thing that must not travel.
            x: -page.groundX
            y: -page.groundY - shift.y
            width: page.groundWidth
            height: page.groundHeight
        }
    }

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
    // Where this page sits in the window, and how big the window's own ground
    // is, so the ground drawn here can be held against the window rather than
    // against the page. Handed down for the same reason the three above are.
    property real groundX: 0
    property real groundY: 0
    property real groundWidth: width
    property real groundHeight: height
    // Asked of the window, which owns the shape. The page never calls
    // showFullScreen itself.
    signal fullscreenToggled()
    // The queue kept as a box of songs, named in the window's own popup.
    signal saveQueueRequested()

    // Whether the pointer is in the right fifth of the screen, which is what
    // brings the column beside the song back while the screen is filled. The
    // bar at the bottom answers to movement anywhere; this answers to being
    // near it, so the rest of the time there is nothing over the picture.
    property bool sideNear: false
    readonly property bool sideAwake: page.cinema && page.sideNear

    // Under this the queue does not fit beside a picture worth looking at at
    // its full width, so it narrows and draws small rows. Raising the window's
    // own minimum instead would be taking the size of the window away from the
    // person using it.
    readonly property bool roomForColumn: width >= 1100
    // The queue beside the song, as wide as the companion's: about a quarter
    // of the page, never so much that its rows run on past their words. A
    // narrow window gets a narrow column of small rows.
    readonly property int queueWidth: roomForColumn
        ? Math.max(420, Math.min(500, Math.round(width * 0.27))) : 300
    // Which tab the middle shows. The queue beside it is the same on all of
    // them.
    property string tab: "video"
    // Words without timing, which are read as one block beside the picture
    // rather than followed under it.
    readonly property bool wordsBlock: (App.nowWords.text || "") !== ""
                                       && !App.nowWords.synced
    // The Lyrics tab following the song: the picture at its full size and
    // the line being sung under it. Also while the words are still on their
    // way and when there are none, so the picture is not sent to a corner
    // to sit beside nothing.
    readonly property bool following: tab === "words" && !wordsBlock && !cinema
    // On every other tab but the video's the picture sits small in a corner,
    // so the song stays in sight while the rest of the page is about it.
    readonly property bool small: tab !== "video" && !following && !cinema

    // The window's menus, asked for from here: a tile's, and a queue row's.
    signal cardMenuRequested(int index, string key)
    signal queueMenuRequested(string key)

    // Asked every time the tab is opened. Whether that costs a request is not
    // decided here: this side cannot tell a press that started something from
    // one that was turned away because another tab was still loading, and
    // remembering the second kind as asked left that tab empty for good.
    function choose(name) {
        page.tab = name
        App.setNowTab(name)
        if (name === "words")
            App.readNowSide("words")
        else if (name === "comments")
            App.readNowComments()
    }

    // The screen filled is the picture and nothing else, so it is the video's
    // tab, never a corner of another one.
    onCinemaChanged: if (cinema && tab !== "video") choose("video")

    // A different song has different words beside it, and different videos
    // recommended for it. Asking for those is the other side's, which hears of
    // the new song after it has put the last one's answers away. Asked from
    // here, it was asked before that, while the last song's words still
    // counted as read, so nothing was asked and the tab stayed empty.

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

        // ---- the middle: the tabs, and what each of them shows -----------
        Item {
            id: stage
            objectName: "nowPlayingStage"
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Where the tabs leave off. The screen filled has none.
            readonly property real contentTop: page.cinema ? 0 : tabRow.height + 12

            Row {
                id: tabRow
                objectName: "nowPlayingTabs"
                visible: !page.cinema
                spacing: 6

                Repeater {
                    model: [{ name: "video", label: "Video" },
                            { name: "recommended", label: "Recommended" },
                            { name: "words", label: "Lyrics" },
                            { name: "comments", label: "Comments" }]
                    FlatButton {
                        required property var modelData
                        objectName: "nowPlayingTab_" + modelData.name
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
                objectName: "nowPlayingVideoPart"
                y: stage.contentTop
                width: stage.width
                height: stage.height - y
                opacity: 1 - Math.min(1, frame.glide * 2.5)
                visible: opacity > 0
                enabled: !page.small
                Column {
                    id: middle
                    // At the top, right under the tabs, rather than floating in
                    // the middle of the space under them. With the screen filled
                    // there are no tabs and nothing under the picture, so it sits
                    // in the middle of the screen instead of at the top of it with
                    // a black band below.
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
                    width: frameSlot.width
                    spacing: 12
                    // The room the picture rests in on this tab, sixteen by nine, as
                    // large as what is left once the words have taken their room.
                    // It is reserved whether or not there is a video, so a song and
                    // a music video do not resize the page between them. The
                    // picture itself is drawn over it, by the frame further down,
                    // which can leave it for a corner of another tab.
                    Item {
                        id: frameSlot
                        objectName: "nowPlayingFrameSlot"
                        // What is left once the words have taken their room, and
                        // the whole of it when there are no words.
                        //
                        // A description is not part of that: it has room of its own
                        // under the words and scrolls there, and the picture is
                        // sized as if two lines of it were all there is. So a long
                        // one never shrinks the picture, and scrolling it moves
                        // nothing above it.
                        readonly property real spare: words.visible
                            ? videoPart.height - words.height - middle.spacing - descriptionArea.reserve
                            : videoPart.height
                        readonly property real room: Math.min(videoPart.width,
                                                              Math.max(90, spare) * 16 / 9)
                        // With the screen filled there is nothing else on the
                        // screen to keep still for, so the box IS the screen and
                        // the picture inside it keeps its own shape, which is mpv's
                        // to hold.
                        width: page.cinema ? videoPart.width : Math.max(160, room)
                        height: page.cinema ? videoPart.height : width * 9 / 16
                    }

                    // ---- the words under the picture -------------------------
                    Column {
                        id: words
                        objectName: "nowPlayingWords"
                        // Nothing under the picture while the screen is filled.
                        visible: !page.cinema
                        // Out of sight while the Lyrics tab follows the song,
                        // but still there. The picture is sized by the room
                        // these take, and hiding them outright would make it
                        // grow and shrink with every switch between the two
                        // tabs.
                        opacity: page.following ? 0 : 1
                        enabled: !page.following
                        Behavior on opacity { NumberAnimation { duration: 150 } }
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
                                        id: nowTitle
                                        objectName: "nowPlayingTitle"
                                        // Markup only when a channel's handle in
                                        // it can be pressed. Plain text otherwise.
                                        readonly property string plain: Audio.track.title
                                                                        ? Audio.track.title : ""
                                        readonly property string marked: App.titleLinks(plain)
                                        width: parent.width - audioOnly.width
                                               - fillScreen.width - titleRow.spacing * 2
                                        text: marked !== "" ? marked : plain
                                        textFormat: marked !== "" ? Text.StyledText : Text.PlainText
                                        linkColor: Theme.colors.accent
                                        color: Theme.colors.text
                                        font.pixelSize: 19
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                        onLinkActivated: function (link) { App.openLink(link) }

                                        HoverHandler {
                                            enabled: nowTitle.marked !== ""
                                            cursorShape: nowTitle.linkAt(point.position.x,
                                                                         point.position.y) !== ""
                                                         ? Qt.PointingHandCursor : Qt.ArrowCursor
                                        }
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

                                // Which step of getting the picture up is being
                                // waited on. An address has to be found, which is
                                // a full extraction and takes seconds, the player
                                // then opens that stream, and a frame exists a
                                // couple of seconds after that. Until this line
                                // there was only the artwork sitting there, which
                                // reads the same whether something is happening
                                // or nothing is.
                                //
                                // Under the button rather than beside the words,
                                // because it is about the picture above it. It is
                                // empty whenever nothing is being waited on, and
                                // a Column leaves out a child that is not there.
                                //
                                // The last step is not a wait any more, so it is
                                // said for a few seconds and then fades.
                                //
                                // It takes no room of its own. It is drawn over
                                // the right hand end of the row under it, which
                                // leaves that end free for it, so nothing below
                                // moves when it comes, when it goes or while it
                                // is there. A row of its own made the whole
                                // description move up the moment it faded.
                                //
                                // One pixel tall, never none, and always there. A
                                // Column neither places nor draws a child whose
                                // height is 0, so a slot of nothing left the words
                                // at the top of the column, behind the title and
                                // the buttons, where nobody could see them.
                                Item {
                                    id: stageSlot
                                    objectName: "nowPlayingVideoStageSlot"
                                    width: parent.width
                                    height: 1
                                    z: 1

                                    Label {
                                        id: stageLine
                                        objectName: "nowPlayingVideoStage"
                                        // How long the picture arriving is said
                                        // before it goes. A property so the walk
                                        // need not wait the whole of it.
                                        property int restMs: 4000
                                        property bool rested: false
                                        // What was said last, so a report that
                                        // changes nothing about the words neither
                                        // brings a rested line back nor starts
                                        // its clock again.
                                        property string lastSaid: ""
                                        width: parent.width
                                        horizontalAlignment: Text.AlignRight
                                        visible: text !== ""
                                        text: Audio.videoStage
                                        color: Theme.colors.textMuted
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                        opacity: rested ? 0 : 1
                                        Behavior on opacity { NumberAnimation { duration: 400 } }

                                        Timer {
                                            id: stageRest
                                            interval: stageLine.restMs
                                            onTriggered: stageLine.rested = true
                                        }

                                        Connections {
                                            target: Audio
                                            function onVideoChanged() {
                                                if (Audio.videoStage === stageLine.lastSaid)
                                                    return
                                                stageLine.lastSaid = Audio.videoStage
                                                stageLine.rested = false
                                                // Only the picture being up is a
                                                // step that ends. Every other one
                                                // is something still being waited
                                                // on, and stays until it is done.
                                                if (Audio.videoShowing && Audio.videoStage !== "")
                                                    stageRest.restart()
                                                else
                                                    stageRest.stop()
                                            }
                                        }
                                    }
                                }

                                Label {
                                    id: artistLine
                                    objectName: "nowPlayingArtist"
                                    // Pressed, it goes to whoever made this, on
                                    // their channel. Only where the song carries an
                                    // address for them, which a song from an
                                    // ordinary video does not.
                                    readonly property string leadsTo:
                                        Audio.track.artistId ? Audio.track.artistId : ""
                                    // Short of the step line drawn over its right
                                    // hand end, while that line is there.
                                    width: parent.width - (stageLine.text !== "" && stageLine.opacity > 0
                                                           ? stageLine.implicitWidth + 12 : 0)
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
                                        onClicked: App.openArtistChannel(artistLine.leadsTo)
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

                // What was written under the video, in the same call that found
                // the address. All of it, in room of its own from under the words
                // to the foot of the page, scrolling there when there is more
                // than fits. The picture, the title and the facts stand still
                // while it scrolls, because none of them is inside it.
                // Three lines a notch. The page's own step is sized for a grid of
                // cards and sent a room this small past most of what it holds.
                SmoothScroll {
                    flickable: descriptionArea
                    step: Math.round(3 * descriptionLines.lineSpacing)
                }

                // In the same lighter box the panel beside the feed draws its
                // description in, so the two read as one thing. As tall as the
                // words and no taller, down to the foot of the page at most.
                Rectangle {
                    id: descriptionBox
                    objectName: "nowPlayingDescriptionBox"
                    readonly property real pad: 8
                    visible: descriptionArea.writing !== "" && words.visible
                    opacity: words.opacity
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
                    objectName: "nowPlayingDescriptionArea"
                    readonly property string writing: App.nowDetail.descriptionText
                                                      ? App.nowDetail.descriptionText : ""
                    // What the picture leaves for it however long it is: the gap
                    // above, the box's own edges and two lines, which is what it
                    // always had at rest.
                    readonly property real reserve: writing !== "" && words.visible
                        ? gap + 2 * descriptionBox.pad + 2 * descriptionLines.lineSpacing : 0
                    readonly property real gap: 8
                    visible: descriptionBox.visible
                    opacity: words.opacity
                    enabled: words.enabled
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

                    // A different song is a different description, read from the
                    // top rather than from wherever the last one was left.
                    Connections {
                        target: Audio
                        function onTrackChanged() { descriptionArea.contentY = 0 }
                    }

                    Label {
                        id: description
                        objectName: "nowPlayingDescription"
                        // Short of the scroll bar, so the last word of a line is
                        // never under it.
                        width: descriptionArea.width - 10
                        text: descriptionArea.writing
                        color: Theme.colors.text
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        // Already markup when it arrives, addresses and all, and
                        // always markup even when there is nothing in it to press.
                        // Told once rather than switched between two formats,
                        // which would lay the page out again on every song.
                        textFormat: Text.StyledText
                        linkColor: Theme.colors.accent

                        // An address opens in the browser and a time in the text
                        // goes to that point in the song, the way both do under a
                        // video on YouTube.
                        MouseArea {
                            id: descriptionPress
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
                                    Audio.seekTo(parseInt(here.slice(11)))
                                else if (here !== "")
                                    App.openLink(here)
                            }
                        }
                    }
                }

                // ---- the Lyrics tab, following the song --------------------
                //
                // The line being sung and the one after it, smaller, in the
                // middle under the picture. The picture keeps the size and
                // place it has on the Video tab, so going between the two
                // tabs changes nothing but the words under it.
                //
                // Under the picture rather than over it. A lyrics video has
                // the words drawn into the picture already, and words laid
                // over a bright picture need a dark band behind them that
                // covers part of it. Both were tried on real videos.
                Item {
                    id: sung
                    objectName: "nowPlayingSung"
                    x: middle.x
                    y: middle.y + frameSlot.height + 28
                    width: middle.width
                    height: Math.max(0, videoPart.height - y)
                    opacity: page.following ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 150 } }

                    readonly property bool timed: App.nowWords.synced === true
                    // Which line is up, as last drawn, so a step to the next
                    // line can be told from a seek somewhere else.
                    property int was: -2
                    // Where the line on its way up starts from: where the
                    // next line was standing.
                    property real startY: 0

                    // A step to the next line slides it up into place,
                    // growing as it goes, while the one sung goes up the
                    // same distance and fades, so the two move as one and
                    // never cross. It fades quickly, mostly gone before it
                    // reaches the picture, which is drawn over whatever is
                    // left of it, so nothing has to cut it off. Anything
                    // else, a seek or a new song, is put there at once.
                    function follow() {
                        var lyric = App.nowLyric
                        var at = lyric.at !== undefined ? lyric.at : -2
                        var now = lyric.now ? lyric.now : ""
                        var after = lyric.next ? lyric.next : ""
                        if (at === was && now === sungLine.text && after === sungNext.text)
                            return
                        var stepping = at === was + 1 && was > -2 && page.following
                        stepUp.complete()
                        if (stepping) {
                            leaving.text = sungLine.text
                            startY = sungLine.height + sungLines.gap
                        }
                        sungLine.text = now
                        sungNext.text = after
                        was = at
                        if (stepping)
                            stepUp.restart()
                    }

                    Connections {
                        target: App
                        function onNowLyricChanged() { sung.follow() }
                    }
                    Component.onCompleted: follow()

                    Item {
                        id: sungLines
                        readonly property int gap: 8
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: parent.width - 40
                        height: parent.height
                        visible: sung.timed

                        Label {
                            id: leaving
                            objectName: "nowPlayingSungLeaving"
                            width: parent.width
                            opacity: 0
                            color: Theme.colors.text
                            font.pixelSize: 30
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }

                        Label {
                            id: sungLine
                            objectName: "nowPlayingSungLine"
                            width: parent.width
                            transformOrigin: Item.Top
                            color: Theme.colors.text
                            font.pixelSize: 30
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }

                        Label {
                            id: sungNext
                            objectName: "nowPlayingSungNext"
                            y: sungLine.height + sungLines.gap
                            width: parent.width
                            color: Theme.colors.textMuted
                            font.pixelSize: 19
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                            transform: Translate { id: nextRise }
                        }
                    }

                    ParallelAnimation {
                        id: stepUp
                        NumberAnimation { target: leaving; property: "opacity"
                                          from: 1; to: 0; duration: 110
                                          easing.type: Easing.OutQuad }
                        NumberAnimation { target: leaving; property: "y"
                                          from: 0; to: -sung.startY
                                          duration: 260; easing.type: Easing.OutCubic }
                        NumberAnimation { target: sungLine; property: "y"
                                          from: sung.startY; to: 0
                                          duration: 260; easing.type: Easing.OutCubic }
                        NumberAnimation { target: sungLine; property: "scale"
                                          from: sungNext.font.pixelSize / sungLine.font.pixelSize
                                          to: 1; duration: 260; easing.type: Easing.OutCubic }
                        ColorAnimation { target: sungLine; property: "color"
                                         from: Theme.colors.textMuted; to: Theme.colors.text
                                         duration: 260 }
                        // The line after it comes in once the one before has
                        // moved out of its way.
                        SequentialAnimation {
                            PropertyAction { target: sungNext; property: "opacity"; value: 0 }
                            PauseAnimation { duration: 90 }
                            ParallelAnimation {
                                NumberAnimation { target: sungNext; property: "opacity"
                                                  to: 1; duration: 170 }
                                NumberAnimation { target: nextRise; property: "y"
                                                  from: 12; to: 0; duration: 170
                                                  easing.type: Easing.OutCubic }
                            }
                        }
                    }

                    // Where the words are from, as the block of them says
                    // too, at the foot of the room.
                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 6
                        visible: sung.timed && text !== ""
                        text: App.nowWords.source ? App.nowWords.source : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                    }

                    BusyWord {
                        objectName: "nowPlayingSungBusy"
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: 6
                        text: App.nowBusy === "words" ? "Reading the words" : ""
                    }

                    // A song with none is a normal answer, said plainly.
                    Label {
                        objectName: "nowPlayingSungNone"
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: 8
                        visible: App.nowBusy === "" && App.nowRead.indexOf("words") >= 0
                                 && !App.nowWords.text
                        text: "No words for this one"
                        color: Theme.colors.textMuted
                        font.pixelSize: 15
                    }
                }
            }

            // ---- every other tab: the picture small, and beside it what the
            // tab is about ---------------------------------------------------
            Item {
                id: tabPart
                objectName: "nowPlayingTabPart"
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
                            text: page.tab === "recommended" ? "Recommended for"
                                  : (page.tab === "words" ? "Lyrics of" : "Comments on")
                            color: Theme.colors.textMuted
                            font.pixelSize: 12
                        }

                        BusyWord {
                            objectName: "nowPlayingBusy"
                            visible: page.tab === "recommended" ? App.companionBusy
                                                                : App.nowBusy !== ""
                            text: page.tab === "recommended" ? "Asking YouTube"
                                  : (App.nowBusy === "comments" ? "Reading the comments"
                                                                : "Reading")
                        }
                    }

                    Label {
                        width: parent.width
                        text: Audio.track.title ? Audio.track.title : ""
                        color: Theme.colors.text
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        visible: text !== ""
                        text: Audio.track.artist ? Audio.track.artist : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    Item { width: 1; height: 6; visible: page.tab === "recommended" }

                    // The chips YouTube offers beside the video, the mix
                    // first. The one picked is remembered, the same one the
                    // companion page remembers.
                    Flow {
                        objectName: "nowPlayingChips"
                        visible: page.tab === "recommended"
                        width: parent.width
                        spacing: 8

                        Repeater {
                            model: App.nowRecommendedChips

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
                            objectName: "nowPlayingRefresh"
                            visible: App.nowRecommendedChips.length > 1
                            height: 30
                            text: "Refresh"
                            onClicked: App.refreshCompanion()
                        }
                    }
                }

                // Under the picture and the heading, whichever reaches lower.
                Item {
                    id: tabBody
                    objectName: "nowPlayingTabBody"
                    // Placed by hand, a top worked out and the rest of the
                    // height. A bottom anchor beside a y leaves the height at
                    // nothing, and every tab drawn into it empty.
                    y: Math.max(miniSlot.height, heading.y + heading.height) + 18
                    width: parent.width
                    height: Math.max(0, parent.height - y)

                    // ---- Recommended ------------------------------------
                    Rectangle {
                        objectName: "nowPlayingRecommendedNote"
                        visible: page.tab === "recommended" && App.nowRecommendedNote !== ""
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
                            text: App.nowRecommendedNote
                            color: Theme.colors.text
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }
                    }

                    GridView {
                        id: tileGrid
                        objectName: "nowPlayingRecommended"
                        visible: page.tab === "recommended"
                        anchors.fill: parent
                        anchors.topMargin: App.nowRecommendedNote !== "" ? 60 : 0
                        clip: true
                        model: App.nowRecommended
                        readonly property int gap: 12
                        readonly property int columns:
                            Math.max(2, Math.floor((width + gap) / (250 + gap)))
                        cellWidth: Math.floor(width / columns)
                        cellHeight: Math.round((cellWidth - gap) * 9 / 16) + gap
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Item {
                            id: cell
                            objectName: "nowPlayingTile"
                            required property var modelData
                            required property int index
                            width: tileGrid.cellWidth
                            height: tileGrid.cellHeight

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
                                onChosen: App.queueNowRecommended(cell.index, false)
                                onAskedFor: page.cardMenuRequested(cell.index, cell.modelData.key)
                            }
                        }
                    }

                    SmoothScroll {
                        flickable: tileGrid
                        step: tileGrid.cellHeight * App.scrollRowsPerNotch
                    }

                    // ---- Lyrics -----------------------------------------
                    // A column of reading width rather than the whole middle,
                    // since a line of words across a wide window is not read.
                    Flickable {
                        objectName: "nowPlayingLyrics"
                        visible: page.tab === "words"
                        width: Math.min(parent.width, 760)
                        height: parent.height
                        clip: true
                        contentWidth: width
                        contentHeight: wordsColumn.height
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        Column {
                            id: wordsColumn
                            width: parent.width - 14
                            spacing: 8

                            Label {
                                width: parent.width
                                // Whatever the music service returns for this
                                // song, as it returns it.
                                text: App.nowWords.text ? App.nowWords.text : ""
                                visible: text !== ""
                                color: Theme.colors.text
                                font.pixelSize: 14
                                lineHeight: 1.35
                                wrapMode: Text.Wrap
                            }
                            Label {
                                width: parent.width
                                visible: (App.nowWords.source || "") !== ""
                                text: App.nowWords.source ? App.nowWords.source : ""
                                color: Theme.colors.textMuted
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                            }
                            Label {
                                width: parent.width
                                // A song with none is a normal answer. The page
                                // says so plainly rather than sitting empty as
                                // if it had failed.
                                visible: App.nowBusy === ""
                                         && App.nowRead.indexOf("words") >= 0
                                         && !App.nowWords.text
                                text: "No words for this one"
                                color: Theme.colors.textMuted
                                font.pixelSize: 13
                            }
                        }
                    }

                    // ---- Comments ---------------------------------------
                    //
                    // A column rather than a list view, the way the panel
                    // beside the feed draws them. More comments arrive as a
                    // whole new answer, and a list view handed a new answer
                    // goes back to the top, away from the button that was
                    // just pressed at the bottom. A column only grows.
                    Flickable {
                        id: commentArea
                        objectName: "nowPlayingComments"
                        visible: page.tab === "comments"
                        width: Math.min(parent.width, 860)
                        height: parent.height
                        clip: true
                        contentWidth: width
                        contentHeight: commentColumn.height
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        // A different song's comments are read from the top.
                        Connections {
                            target: Audio
                            function onTrackChanged() { commentArea.contentY = 0 }
                        }

                        Column {
                            id: commentColumn
                            width: commentArea.width - 14
                            spacing: 12

                            Label {
                                visible: App.nowComments.length === 0 && App.nowBusy === ""
                                text: "Nothing here"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                            }

                            Repeater {
                                model: App.nowComments
                                CommentThread {
                                    required property var modelData
                                    width: commentColumn.width
                                    comment: modelData
                                    song: true
                                }
                            }

                            // Ten more threads a press. Gone once an answer
                            // brings fewer than were asked for, which is all
                            // of them.
                            FlatButton {
                                objectName: "nowPlayingMoreComments"
                                visible: App.nowCommentsMore
                                enabled: App.nowBusy === ""
                                text: App.nowBusy === "comments" ? "Loading" : "Show more"
                                onClicked: App.loadMoreNowComments()
                            }

                            Item { width: 1; height: 4 }
                        }
                    }

                }
            }

            // ---- the picture ---------------------------------------------
            //
            // Over the room kept for it on the Video tab, and small in the
            // corner of every other tab. Nothing is drawn for the box itself:
            // an empty bordered panel around a square picture reads as a
            // picture that failed to fill it.
            //
            // It travels between the two by being scaled and moved, never by
            // being resized on the way. The video is drawn into a framebuffer
            // the size of the box, and a box that changes size every frame is
            // a framebuffer made again every frame. Kept at its full size
            // while it moves, mpv draws exactly what it always draws, and the
            // box takes its small size once, when it gets there, which costs
            // what resizing the window once does. Measured in the real window
            // at 165 Hz with a 1080p picture and sound going out through the
            // sound server: no sound lost, no frame dropped, no stall.
            Item {
                id: frame
                objectName: "nowPlayingFrame"
                z: 3
                // Where it rests on the Video tab, and in the corner.
                readonly property real bigX: videoPart.x + middle.x
                readonly property real bigY: videoPart.y + middle.y
                readonly property real bigW: frameSlot.width
                readonly property real bigH: frameSlot.height
                readonly property real smallX: tabPart.x + miniSlot.x
                readonly property real smallY: tabPart.y + miniSlot.y
                // How far along the way to the corner it is, 0 at rest on the
                // Video tab and 1 in the corner.
                property real glide: page.small ? 1 : 0
                Behavior on glide {
                    // The screen being filled is no journey to watch.
                    enabled: !page.cinema
                    NumberAnimation {
                        id: glideStep
                        duration: 260
                        easing.type: Easing.OutCubic
                    }
                }
                // In the corner and done moving, the one time it is small for
                // real rather than drawn small.
                readonly property bool shrunk: glide === 1 && !glideStep.running
                x: bigX + (smallX - bigX) * glide
                y: bigY + (smallY - bigY) * glide
                width: shrunk ? miniSlot.width : bigW
                height: shrunk ? miniSlot.height : bigH
                transformOrigin: Item.TopLeft
                scale: shrunk ? 1 : 1 + (miniSlot.width / Math.max(1, bigW) - 1) * glide
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
                    cursorShape: page.cinema && !page.chromeAwake ? Qt.BlankCursor
                                 : (page.small ? Qt.PointingHandCursor : Qt.ArrowCursor)

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
                    // Small in the corner of another tab, a press is the way
                    // back to the video rather than a pause.
                    onClicked: {
                        if (page.small)
                            page.choose("video")
                        else
                            pressWait.restart()
                    }
                    onDoubleClicked: {
                        pressWait.stop()
                        if (!page.small)
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
                // Pressed in the corner, it takes the page back to the video.
                Rectangle {
                    objectName: "nowPlayingBackToVideo"
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
            }
        }

        // ---- everything that belongs beside the song ---------------------
        // The room the column takes beside the picture on the page. Empty, and
        // no width at all when the screen is filled, which is what lets the
        // picture have the whole of it.
        Item {
            id: sideCell
            objectName: "nowPlayingSideCell"
            Layout.preferredWidth: page.cinema ? 0 : page.queueWidth
            Layout.maximumWidth: Layout.preferredWidth
            Layout.fillHeight: true
            visible: !page.cinema
        }
    }

    // ---- the queue, the same beside every tab ------------------------------
    Rectangle {
        id: side
        objectName: "nowPlayingSide"
        // It sits in the room beside the middle on the page, and over the
        // picture when the screen is filled. ONE column either way: two would
        // have drifted apart the first time either of them grew.
        //
        // Both homes are plain items, never the row itself. A child of a
        // layout may not be anchored -- "Cannot anchor to an item that isn't
        // a parent or sibling" -- and anchoring to its own parent is the only
        // shape that is legal in both.
        parent: page.cinema ? sideSlot : sideCell
        anchors.fill: parent
        radius: 10
        // Thicker over a picture, so its rows can be read against anything.
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
                text: ("Queue" + (Audio.queue.length > 0 ? "  ·  " + Audio.queue.length : ""))
                      .toUpperCase()
                color: Theme.colors.textMuted
                font.pixelSize: 11
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }

            Item { Layout.fillWidth: true }

            FlatButton {
                objectName: "nowPlayingQueueSave"
                visible: Audio.queue.length > 0
                text: "Save as box"
                hint: "Keep the whole queue as a box of songs"
                onClicked: page.saveQueueRequested()
            }

            FlatButton {
                objectName: "nowPlayingQueueClear"
                visible: Audio.queue.length > 1
                text: "Clear"
                hint: "Take everything out of the queue except the song playing"
                onClicked: Audio.clearQueue()
            }
        }

        QueueList {
            objectName: "nowPlayingQueue"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: queueHead.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 8
            anchors.topMargin: 10
            onMenuRequested: (key) => page.queueMenuRequested(key)
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
