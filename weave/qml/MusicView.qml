import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Listening rather than watching. It opens on what YouTube Music opens on,
// because a library that is empty is not a place to start from.
Item {
    id: view

    // A tile and the gap after it. The two row band has to count how many fit
    // across, so the size lives here rather than being left to each tile.
    readonly property int tileSize: 132
    readonly property int tileSpacing: 10

    // The one section opened in full, empty when the page is not on one. The
    // shelves, one section in full and a track list are the three things this
    // view shows, and exactly one of them is up at a time.
    readonly property var openShelf: App.musicShelfPage

    // Right pressing a song offers to keep it. One menu for both the two rows
    // and the whole section page, told which tile it was opened on.
    property int askedShelf: -1
    property int askedItem: -1
    property int askedResult: -1

    function askAboutResult(resultIndex) {
        view.askedShelf = -1
        view.askedItem = -1
        view.askedResult = resultIndex
        songMenu.popup()
    }

    function askAbout(shelfIndex, itemIndex) {
        view.askedResult = -1
        view.askedShelf = shelfIndex
        view.askedItem = itemIndex
        songMenu.popup()
    }

    ThemedMenu {
        id: songMenu
        objectName: "songMenu"

        // Queueing comes first, since it is about what happens next and that
        // is the reason to press a song rather than play it. Only while
        // something is playing, because with an empty player there is no
        // queue to add to and no next to be.
        ThemedMenuItem {
            objectName: "songPlayNextEntry"
            visible: Audio.hasQueue
            height: visible ? implicitHeight : 0
            text: "Play it next"
            onTriggered: {
                if (view.askedResult >= 0)
                    App.queueResult(view.askedResult, true)
                else
                    App.queueShelfItem(view.askedShelf, view.askedItem, true)
                songMenu.dismiss()
            }
        }

        ThemedMenuItem {
            objectName: "songQueueEntry"
            visible: Audio.hasQueue
            height: visible ? implicitHeight : 0
            text: "Add to the queue"
            onTriggered: {
                if (view.askedResult >= 0)
                    App.queueResult(view.askedResult, false)
                else
                    App.queueShelfItem(view.askedShelf, view.askedItem, false)
                songMenu.dismiss()
            }
        }

        // One entry for both, since keeping a song is the same act whether it
        // was drawn as a tile or as a row in a list that was opened.
        ThemedMenuItem {
            objectName: "songFavoriteEntry"
            readonly property bool kept: view.askedResult >= 0
                                         ? App.resultIsFavorite(view.askedResult)
                                         : App.shelfItemIsFavorite(view.askedShelf,
                                                                   view.askedItem)
            text: kept ? "Remove from favorites" : "Add to favorites"
            onTriggered: {
                if (view.askedResult >= 0)
                    App.favoriteResult(view.askedResult)
                else
                    App.favoriteShelfItem(view.askedShelf, view.askedItem)
                songMenu.dismiss()
            }
        }
    }
    readonly property var openShelfItems: openShelf.items ? openShelf.items : []
    readonly property bool onShelfPage: openShelfItems.length > 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            TextField {
                id: query
                Layout.fillWidth: true
                placeholderText: "Search YouTube Music"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: query.activeFocus ? Theme.colors.accent : Theme.colors.border
                }
                onAccepted: App.musicSearch(text)

                // Walking back to the shelves with the mouse buttons leaves
                // no list behind, so the words that opened it should go too.
                // Only while the box is not being typed in, since a search
                // that has not been sent yet is still wanted.
                Connections {
                    target: App
                    function onMusicChanged() {
                        if (App.musicResults.length === 0 && !query.activeFocus)
                            query.text = ""
                    }
                }
            }

            FlatButton {
                text: App.musicSearching ? "Working" : "Search"
                accent: true
                enabled: !App.musicSearching
                onClicked: App.musicSearch(query.text)
            }

            FlatButton {
                // These are YouTube likes rather than YouTube Music likes. The
                // two lists are separate and this is the one with anything in.
                text: "Liked"
                enabled: !App.musicSearching
                onClicked: App.playLiked()
            }

            FlatButton {
                visible: App.musicResults.length > 0 || view.onShelfPage
                // Read from the back history, so it names where it really
                // goes. Written by hand it said recommended, which is one of
                // several ways into a list and was wrong from every other one.
                text: App.backLabel !== "" ? App.backLabel : "Back to music"
                onClicked: {
                    query.text = ""
                    if (App.canGoBack) App.goBack()
                    else App.clearResults()
                }
            }

            FlatButton {
                visible: App.musicResults.length === 0 && !view.onShelfPage
                text: "Refresh"
                onClicked: App.refreshMusic()
            }

            FlatButton {
                visible: App.musicResults.length === 0 && !view.onShelfPage
                text: "Reset order"
                onClicked: App.resetShelfOrder()
            }
        }

        // ---- what is showing --------------------------------------------

        Flickable {
            id: shelfArea
            objectName: "shelfArea"
            visible: App.musicResults.length === 0 && !view.onShelfPage
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: shelfColumn.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                id: shelfColumn
                width: shelfArea.width
                spacing: 16

                Repeater {
                    model: App.musicShelves
                    ColumnLayout {
                        id: shelf
                        required property var modelData
                        required property int index
                        // Named, so a tile inside can say which shelf it is in
                        // without colliding with its own index.
                        readonly property int shelfIndex: index
                        readonly property bool saved: modelData.kind === "saved"
                        // Two rows and no more, so a section stays something
                        // glanced at rather than a page in its own right. How
                        // many fit across is worked out rather than assumed,
                        // since the window is resized and the tiles are not.
                        readonly property int columns:
                            Math.max(1, Math.floor((width + view.tileSpacing)
                                                   / (view.tileSize + view.tileSpacing)))
                        readonly property int total: modelData.items.length
                        readonly property bool overflowing: total > columns * 2
                        // The last place of the two rows belongs to the tile
                        // that opens the whole section, so what does not fit
                        // is still reachable rather than quietly gone.
                        readonly property int shown: overflowing ? columns * 2 - 1 : total
                        Layout.fillWidth: true
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Label {
                                text: shelf.modelData.title.toUpperCase()
                                color: Theme.colors.textMuted
                                font.pixelSize: 10
                                font.letterSpacing: 1.2
                                font.weight: Font.DemiBold
                            }

                            // Sections are arranged by hand and the order is
                            // kept, so the ones that matter can sit at the top.
                            Label {
                                text: "▲"
                                color: upHover.hovered ? Theme.colors.accent : Theme.colors.border
                                font.pixelSize: 10
                                HoverHandler { id: upHover }
                                TapHandler { onTapped: App.moveShelf(shelf.modelData.title, -1) }
                            }
                            Label {
                                text: "▼"
                                color: downHover.hovered ? Theme.colors.accent : Theme.colors.border
                                font.pixelSize: 10
                                HoverHandler { id: downHover }
                                TapHandler { onTapped: App.moveShelf(shelf.modelData.title, 1) }
                            }

                            Item { Layout.fillWidth: true }
                        }

                        Flow {
                            objectName: "shelfRow" + shelf.shelfIndex
                            Layout.fillWidth: true
                            spacing: view.tileSpacing
                            Repeater {
                                model: shelf.modelData.items
                                MusicTile {
                                    required property var modelData
                                    required property int index
                                    // A Flow skips what is not visible, so the
                                    // rows beyond the second cost a delegate
                                    // and no space.
                                    visible: index < shelf.shown
                                    width: view.tileSize
                                    height: view.tileSize
                                    title: modelData.title
                                    subtitle: modelData.subtitle
                                    picture: modelData.thumbnail
                                    removable: shelf.saved
                                    onChosen: shelf.saved ? App.playSource(modelData.sourceId)
                                                          : App.playShelfItem(shelf.shelfIndex, index)
                                    onAskedFor: if (!shelf.saved)
                                                    view.askAbout(shelf.shelfIndex, index)
                                    onRemoveRequested: App.removeSource(modelData.sourceId)
                                }
                            }

                            Rectangle {
                                objectName: "seeAll" + shelf.shelfIndex
                                visible: shelf.overflowing
                                width: view.tileSize
                                height: view.tileSize
                                radius: 8
                                color: seeAllHover.hovered ? Theme.colors.surfaceRaised
                                                           : Theme.colors.surface
                                border.width: 1
                                border.color: seeAllHover.hovered ? Theme.colors.accent
                                                                  : Theme.colors.border

                                HoverHandler { id: seeAllHover }

                                Column {
                                    anchors.centerIn: parent
                                    spacing: 3
                                    Label {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: "See all"
                                        color: Theme.colors.text
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: shelf.total + " in all"
                                        color: Theme.colors.textMuted
                                        font.pixelSize: 10
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: App.openShelf(shelf.shelfIndex)
                                }
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: App.musicShelves.length === 0
                    text: App.musicSearching ? "Loading"
                                             : "Nothing to show yet. Search, or press Liked."
                    color: Theme.colors.textMuted
                    font.pixelSize: 13
                }

                Item { Layout.preferredHeight: 4 }
            }
        }

        // ---- one section in full -----------------------------------------

        RowLayout {
            visible: view.onShelfPage
            Layout.fillWidth: true
            Label {
                text: (view.openShelf.title ? view.openShelf.title : "").toUpperCase()
                color: Theme.colors.textMuted
                font.pixelSize: 10
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            Label {
                text: view.openShelfItems.length + " entries"
                color: Theme.colors.textMuted
                font.pixelSize: 11
            }
        }

        Flickable {
            id: shelfPageArea
            objectName: "shelfPage"
            visible: view.onShelfPage
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: shelfPageFlow.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Flow {
                id: shelfPageFlow
                objectName: "shelfPageFlow"
                width: shelfPageArea.width
                spacing: view.tileSpacing

                Repeater {
                    model: view.openShelfItems
                    MusicTile {
                        required property var modelData
                        required property int index
                        width: view.tileSize
                        height: view.tileSize
                        title: modelData.title
                        subtitle: modelData.subtitle
                        picture: modelData.thumbnail
                        removable: view.openShelf.kind === "saved"
                        // Played through the section it belongs to, so a tile
                        // does the same thing here as it does in the two rows.
                        onChosen: view.openShelf.kind === "saved"
                                  ? App.playSource(modelData.sourceId)
                                  : App.playShelfItem(view.openShelf.index, index)
                        onAskedFor: if (view.openShelf.kind !== "saved")
                                        view.askAbout(view.openShelf.index, index)
                        onRemoveRequested: App.removeSource(modelData.sourceId)
                    }
                }
            }
        }

        RowLayout {
            visible: App.musicResults.length > 0
            Layout.fillWidth: true
            Label {
                text: App.musicLabel.toUpperCase()
                color: Theme.colors.textMuted
                font.pixelSize: 10
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            Label {
                text: App.musicResults.length + " tracks"
                color: Theme.colors.textMuted
                font.pixelSize: 11
            }
        }

        ListView {
            id: results
            objectName: "musicResultsList"
            visible: App.musicResults.length > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: App.musicResults
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                required property var modelData
                required property int index
                width: results.width
                height: 52
                radius: 6
                color: rowHover.hovered ? Theme.colors.surfaceRaised : "transparent"

                HoverHandler { id: rowHover }
                TapHandler { onTapped: App.playResult(index) }
                // A song in an opened list is kept the same way a tile is.
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: view.askAboutResult(index)
                }

                Row {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 10

                    RoundedImage { width: 40; height: 40; radius: 5; source: modelData.thumbnail }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 120
                        spacing: 2
                        Label {
                            width: parent.width
                            text: modelData.title
                            color: Theme.colors.text
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                        Label {
                            width: parent.width
                            text: modelData.artist
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }
                }

                Label {
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.duration
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                }
            }
        }

        // ---- keeping an address ------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            TextField {
                id: sourceLabel
                Layout.preferredWidth: 150
                placeholderText: "Name, optional"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6; color: Theme.colors.background
                    border.width: 1; border.color: Theme.colors.border
                }
            }
            TextField {
                id: sourceUrl
                Layout.fillWidth: true
                placeholderText: "Keep an address, a round the clock stream for example"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6; color: Theme.colors.background
                    border.width: 1; border.color: Theme.colors.border
                }
                onAccepted: addButton.save()
            }
            CheckBox {
                id: isLive
                text: "live"
                contentItem: Label {
                    text: parent.text
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    leftPadding: parent.indicator.width + 4
                    verticalAlignment: Text.AlignVCenter
                }
            }
            FlatButton {
                id: addButton
                text: "Save"
                function save() {
                    App.addSource(sourceLabel.text, sourceUrl.text, isLive.checked)
                    sourceLabel.text = ""
                    sourceUrl.text = ""
                }
                onClicked: save()
            }
        }
    }

    SmoothScroll { flickable: shelfArea }
    SmoothScroll { flickable: shelfPageArea }
    SmoothScroll { flickable: results }
}
