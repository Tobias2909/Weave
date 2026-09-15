import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

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

    // Under this the column on the right does not fit beside a picture worth
    // looking at, so it keeps only its tabs. Raising the window's own minimum
    // instead would be taking the size of the window away from the person
    // using it.
    readonly property bool roomForColumn: width >= 1100
    property string tab: "next"
    // Tabs are asked for once each, when they are first opened, rather than on
    // the way into the page. Comments alone are seven to twelve seconds.
    property var asked: ({})

    function choose(name) {
        page.tab = name
        if (page.asked[name])
            return
        // A fresh object every time. Putting the same one back changes nothing,
        // because QML compares the reference and emits no change.
        var seen = {}
        for (var key in page.asked)
            seen[key] = page.asked[key]
        seen[name] = true
        page.asked = seen
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
            page.asked = ({})
            if (page.tab !== "next")
                page.choose(page.tab)
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
                anchors.centerIn: parent
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

                    // Square cover art in a wide box, centred, at its own
                    // shape. Stretching it to the corners would be inventing
                    // picture that was never there.
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
                        objectName: "nowPlayingArtist"
                        width: parent.width
                        visible: text !== ""
                        text: Audio.track.artist ? Audio.track.artist : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 13
                        elide: Text.ElideRight
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
                        visible: App.nowBusy === "" && App.nowWords.read === true
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
                                width: parent.width
                                visible: (relatedRow.modelData.artist || "") !== ""
                                text: relatedRow.modelData.artist
                                color: Theme.colors.textMuted
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: relatedList.count === 0 && App.nowBusy === ""
                    text: "Nothing here"
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
