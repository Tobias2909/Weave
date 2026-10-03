import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Listening rather than watching. It opens on what YouTube Music opens on,
// because a library that is empty is not a place to start from.
Item {
    id: view
    // The page moves when you arrive on it, and what moves is drawn inside
    // this, so it is cut off at the edges rather than reaching the bar above
    // or the one below.
    clip: true
    // Lent out so the window can carry it, the way the other pages lend the
    // part of themselves that scrolls.
    readonly property Item body: layout

    // A tile and the gap after it. The two row band has to count how many fit
    // across, so the size lives here rather than being left to each tile.
    readonly property int tileSize: 132
    readonly property int tileSpacing: 10

    // The one section opened in full, empty when the page is not on one. The
    // shelves, one section in full and a track list are the three things this
    // view shows, and exactly one of them is up at a time.
    readonly property var openShelf: App.musicShelfPage

    // A new box is named in the window's own popup, so it is asked for from
    // here, with the song it was asked for from when there is one.
    signal newBoxRequested(var song)

    // Which box the boxes row's own menu was opened on.
    property int chipBox: -1

    // The window's sideways step between tabs, lent in so the part under the
    // tabs moves the way every other row of tabs in the window moves it.
    property real slide: 0
    property real fade: 1
    signal tabRequested(int boxId)

    // The tabs are only for the page the music opens on. A search, a list
    // or a whole section has its own way back to it.
    readonly property bool onHome: App.musicResults.length === 0 && !view.onShelfPage

    // Right pressing a song offers to keep it. One menu for both the two rows
    // and the whole section page, told which tile it was opened on.
    property int askedShelf: -1
    property int askedItem: -1
    property int askedResult: -1

    // A tile of the box a tab shows.
    property int askedTab: -1

    function askAboutTab(index) {
        view.askedShelf = -1
        view.askedItem = -1
        view.askedResult = -1
        view.askedTab = index
        songBoxMenu.holding = App.songBoxes("tab", index, -1)
        songMenu.popup()
    }

    function askAboutResult(resultIndex) {
        view.askedTab = -1
        view.askedShelf = -1
        view.askedItem = -1
        view.askedResult = resultIndex
        songBoxMenu.holding = App.songBoxes("result", resultIndex, -1)
        songMenu.popup()
    }

    function askAbout(shelfIndex, itemIndex) {
        view.askedTab = -1
        view.askedResult = -1
        view.askedShelf = shelfIndex
        view.askedItem = itemIndex
        songBoxMenu.holding = App.songBoxes("shelf", shelfIndex, itemIndex)
        songMenu.popup()
    }

    // A box's own menu, from a right press on it in the row at the top.
    ThemedMenu {
        id: chipMenu
        objectName: "boxChipMenu"
        implicitWidth: 200

        ThemedMenuItem {
            text: "Play it"
            onTriggered: { App.playMusicBox(view.chipBox, false); chipMenu.dismiss() }
        }

        ThemedMenuItem {
            text: "Shuffle it"
            onTriggered: { App.playMusicBox(view.chipBox, true); chipMenu.dismiss() }
        }

        ThemedMenuSeparator {}

        ThemedMenuItem {
            text: "Music settings"
            onTriggered: { App.showMusicSettings(); chipMenu.dismiss() }
        }
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
                if (view.askedTab >= 0)
                    App.queueSong("tab", view.askedTab, -1, true)
                else if (view.askedResult >= 0)
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
                if (view.askedTab >= 0)
                    App.queueSong("tab", view.askedTab, -1, false)
                else if (view.askedResult >= 0)
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
            readonly property bool kept: view.askedTab >= 0
                                         ? App.songIsFavorite("tab", view.askedTab, -1)
                                         : view.askedResult >= 0
                                         ? App.resultIsFavorite(view.askedResult)
                                         : App.shelfItemIsFavorite(view.askedShelf,
                                                                   view.askedItem)
            text: kept ? "Remove from favorites" : "Add to favorites"
            onTriggered: {
                if (view.askedTab >= 0)
                    App.putSongInBox("tab", view.askedTab, -1, 0)
                else if (view.askedResult >= 0)
                    App.favoriteResult(view.askedResult)
                else
                    App.favoriteShelfItem(view.askedShelf, view.askedItem)
                songMenu.dismiss()
            }
        }

        // Into one of the boxes, or a new one, or out of one again.
        BoxMenu {
            id: songBoxMenu
            objectName: "songBoxMenu"
            owner: songMenu
            where: view.askedTab >= 0 ? "tab" : view.askedResult >= 0 ? "result" : "shelf"
            first: view.askedTab >= 0 ? view.askedTab
                                      : view.askedResult >= 0 ? view.askedResult : view.askedShelf
            second: view.askedTab >= 0 || view.askedResult >= 0 ? -1 : view.askedItem
            onNewBoxWanted: (song) => view.newBoxRequested(song)
        }

        // Only on a box's own tab, where taking a song out is the obvious
        // thing to want.
        ThemedMenuItem {
            objectName: "songOutOfBox"
            visible: view.askedTab >= 0
            height: visible ? implicitHeight : 0
            text: "Take it out of this box"
            onTriggered: {
                App.takeOutOfMusicTab(view.askedTab)
                songMenu.dismiss()
            }
        }

        ThemedMenuSeparator {}

        // The song as the video it is, in mpv, the way a card plays.
        ThemedMenuItem {
            objectName: "songWatchEntry"
            text: "Watch in mpv"
            onTriggered: {
                if (view.askedTab >= 0)
                    App.watchSong("tab", view.askedTab, -1)
                else if (view.askedResult >= 0)
                    App.watchResult(view.askedResult)
                else
                    App.watchShelfItem(view.askedShelf, view.askedItem)
                songMenu.dismiss()
            }
        }
    }
    readonly property var openShelfItems: openShelf.items ? openShelf.items : []
    readonly property bool onShelfPage: openShelfItems.length > 0

    ColumnLayout {
        id: layout
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
                onAccepted: {
                    if (!musicSuggestions.takePicked()) {
                        App.clearSuggestions()
                        App.musicSearch(text)
                    }
                }
                Keys.onEscapePressed: (event) => {
                    event.accepted = musicSuggestions.opened
                    if (musicSuggestions.opened) App.clearSuggestions()
                }
                Keys.onDownPressed: (event) => { event.accepted = musicSuggestions.move(1) }
                Keys.onUpPressed: (event) => { event.accepted = musicSuggestions.move(-1) }
                // The same as the search box at the top, from the music side.
                onTextEdited: musicSuggestTimer.restart()
                onActiveFocusChanged: if (!activeFocus) musicSuggestLeave.restart()

                Timer {
                    id: musicSuggestTimer
                    interval: 150
                    onTriggered: App.suggest("music", query.text)
                }
                Timer {
                    id: musicSuggestLeave
                    interval: 200
                    onTriggered: if (!query.activeFocus) App.clearSuggestions()
                }

                SuggestionList {
                    id: musicSuggestions
                    objectName: "musicSuggestions"
                    field: query
                    where: "music"
                    onChosen: (words) => {
                        musicSuggestTimer.stop()
                        App.clearSuggestions()
                        query.text = words
                        App.musicSearch(words)
                    }
                }

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
                objectName: "musicHomeButton"
                visible: App.musicResults.length > 0 || view.onShelfPage
                // Always the shelves, never one step back. A search left open
                // is still there when the Music tab is pressed again, and a
                // button that walked back from it went to whatever page was
                // open before, so the only way home was the whole history.
                // The mouse's back button is the one that walks.
                text: "Back to music"
                onClicked: {
                    query.text = ""
                    App.clearResults()
                }
            }

            FlatButton {
                visible: App.musicResults.length === 0 && !view.onShelfPage
                text: "Refresh"
                onClicked: App.refreshMusic()
            }

        }

        // ---- the tabs ---------------------------------------------------
        //
        // The shelves YouTube Music offers, then every box. Pressing one
        // steps sideways to it the way the tabs of a channel do, and only
        // what is under the row moves.
        Flow {
            id: musicTabs
            objectName: "boxChips"
            visible: view.onHome
            Layout.fillWidth: true
            spacing: 8

            Rectangle {
                id: shelvesTab
                objectName: "shelvesTab"
                readonly property bool chosen: App.musicTab < 0
                height: 30
                radius: 15
                width: shelvesWords.implicitWidth + 28
                color: chosen ? Theme.wash(Theme.colors.accent, 0.26)
                              : (shelvesHover.hovered ? Theme.wash(Theme.colors.accent, 0.16)
                                                      : Theme.colors.surfaceRaised)
                border.width: 1
                border.color: chosen || shelvesHover.hovered
                              ? Theme.wash(Theme.colors.accent, 0.6) : Theme.colors.border

                Label {
                    id: shelvesWords
                    anchors.centerIn: parent
                    text: "Shelves"
                    color: Theme.colors.text
                    font.pixelSize: 12
                    font.weight: shelvesTab.chosen ? Font.DemiBold : Font.Normal
                }

                HoverHandler { id: shelvesHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: view.tabRequested(-1) }
            }

            Repeater {
                model: App.musicBoxes

                Rectangle {
                    id: chip
                    objectName: "boxChip"
                    required property var modelData
                    readonly property bool chosen: App.musicTab === modelData.id
                    height: 30
                    radius: 15
                    width: chipWords.implicitWidth + 28
                    color: chosen ? Theme.wash(Theme.colors.accent, 0.26)
                                  : (chipHover.hovered ? Theme.wash(Theme.colors.accent, 0.16)
                                                       : Theme.colors.surfaceRaised)
                    border.width: 1
                    border.color: chosen || chipHover.hovered
                                  ? Theme.wash(Theme.colors.accent, 0.6) : Theme.colors.border

                    Row {
                        id: chipWords
                        anchors.centerIn: parent
                        spacing: 8

                        Label {
                            text: (chip.modelData.fixed ? "♥  " : "") + chip.modelData.name
                            color: Theme.colors.text
                            font.pixelSize: 12
                            font.weight: chip.chosen ? Font.DemiBold : Font.Normal
                        }

                        Label {
                            text: chip.modelData.count
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: view.tabRequested(chip.modelData.id) }
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        onTapped: {
                            view.chipBox = chip.modelData.id
                            chipMenu.popup()
                        }
                    }
                }
            }

            Rectangle {
                objectName: "newBoxChip"
                height: 30
                radius: 15
                width: newBoxWords.implicitWidth + 28
                color: newBoxHover.hovered ? Theme.wash(Theme.colors.accent, 0.16) : "transparent"
                border.width: 1
                border.color: Theme.colors.border

                Label {
                    id: newBoxWords
                    anchors.centerIn: parent
                    text: "+  New box"
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                }

                HoverHandler { id: newBoxHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: view.newBoxRequested(null) }
            }
        }

        // One box, as the tiles the shelves are drawn in. Pressing one plays
        // the box from there, in its own order.
        Flickable {
            id: boxArea
            objectName: "boxArea"
            visible: view.onHome && App.musicTab >= 0
            transform: Translate { x: view.slide }
            opacity: view.fade
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: boxColumn.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                id: boxColumn
                width: boxArea.width
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Label {
                        objectName: "boxSongCount"
                        visible: App.musicTabSongs.length > 0
                        text: (App.musicTabSongs.length === 1
                               ? "1 song" : App.musicTabSongs.length + " songs").toUpperCase()
                        color: Theme.colors.textMuted
                        font.pixelSize: 10
                        font.letterSpacing: 1.2
                        font.weight: Font.DemiBold
                    }

                    Item { Layout.fillWidth: true }

                    FlatButton {
                        objectName: "boxPlay"
                        visible: App.musicTabSongs.length > 0
                        text: "Play"
                        onClicked: App.playMusicBox(App.musicTab, false)
                    }

                    FlatButton {
                        objectName: "boxShuffle"
                        visible: App.musicTabSongs.length > 1
                        text: "Shuffle"
                        onClicked: App.playMusicBox(App.musicTab, true)
                    }
                }

                Label {
                    objectName: "boxEmpty"
                    visible: App.musicTabSongs.length === 0
                    Layout.fillWidth: true
                    Layout.topMargin: 20
                    text: "Nothing in this box yet. Right click a song anywhere and choose "
                          + "Put in a box, or keep the whole queue from beside its Clear."
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }

                Flow {
                    objectName: "boxTiles"
                    Layout.fillWidth: true
                    spacing: view.tileSpacing

                    Repeater {
                        model: App.musicTabSongs

                        MusicTile {
                            required property var modelData
                            required property int index
                            width: view.tileSize
                            height: view.tileSize
                            title: modelData.title
                            subtitle: modelData.subtitle
                            picture: modelData.thumbnail
                            subtitleLeads: (modelData.artistId || "") !== ""
                            onSubtitleChosen: App.openArtistChannel(modelData.artistId)
                            onChosen: App.playMusicTabSong(index)
                            onAskedFor: view.askAboutTab(index)
                        }
                    }
                }
            }
        }

        // ---- what is showing --------------------------------------------

        Flickable {
            id: shelfArea
            objectName: "shelfArea"
            visible: view.onHome && App.musicTab < 0
            transform: Translate { x: view.slide }
            opacity: view.fade
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

                            // The order and which ones show are kept in the
                            // music settings, opened from beside Music in the
                            // sidebar, rather than in arrows on every heading.

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
                                    // The name under a tile goes to whoever
                                    // made it, where the entry carries an
                                    // address for them.
                                    subtitleLeads: (modelData.artistId || "") !== ""
                                    onSubtitleChosen: App.openArtistChannel(modelData.artistId)
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
                                // Solid, so the film is mixed into the
                                // ground rather than laid over it.
                                color: seeAllHover.hovered
                                       ? Theme.washOver(Theme.colors.accent, 0.14,
                                                        Theme.colors.surface)
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
                        subtitleLeads: (modelData.artistId || "") !== ""
                        onSubtitleChosen: App.openArtistChannel(modelData.artistId)
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
                color: rowHover.hovered ? Theme.wash(Theme.colors.accent, 0.14)
                                        : "transparent"

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

        // For the Saved shelf, so not under a box.
        RowLayout {
            visible: App.musicTab < 0
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
