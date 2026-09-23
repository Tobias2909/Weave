import QtQuick
import QtQuick.Controls

// The playlists a channel has made, as tiles, with a box for finding one by
// name. Names only until one is opened, because the tab that lists them
// carries no video count and a real count is one request per playlist.
// Opening one is what fills that in, free.
//
// A GridView rather than a Flow of every tile, because a channel can list a
// thousand playlists and a Flow builds a card, a picture and a fetch for
// every one of them the moment the tab is opened. A view builds the rows it
// draws and a little ahead, so the cost of arriving here is the same whether
// the channel has twelve lists or twelve hundred.
Item {
    id: root
    objectName: "channelPlaylists"

    // The walk between tabs and the rise on arrival move this, and the root
    // clips, so neither can reach the panels on either side.
    property alias walkItem: holder
    property alias flick: grid

    // One row of tiles, so a wheel notch over this moves as far as it does
    // over the grid of videos. Read from outside, since the thing that turns
    // a notch into a distance has to be declared beside a view rather than
    // inside one.
    readonly property real rowHeight: grid.cellHeight

    // What is typed in the box, and what is left after it. The filter is over
    // what is already stored, so it costs nothing and answers on the letter.
    property string query: ""
    readonly property var everyone: App.channelPlaylists
    readonly property var shown: {
        var wanted = root.query.trim().toLowerCase()
        if (wanted === "")
            return root.everyone
        return root.everyone.filter(function (row) {
            return row.title.toLowerCase().indexOf(wanted) !== -1
        })
    }

    clip: true

    Item {
        id: holder
        anchors.fill: parent

        Row {
            id: findRow
            x: 10
            y: 10
            width: parent.width - 20
            height: visible ? 34 : 0
            spacing: 10
            // Nothing to look through until there is more than a screenful,
            // and a box over four tiles is furniture. A reading in progress
            // brings the row back whatever is in it, because that is where
            // the word about it goes.
            visible: root.everyone.length > 8
                     || (App.channelPlaylistsBusy && root.everyone.length > 0)

            TextField {
                id: findField
                objectName: "playlistSearchField"
                visible: root.everyone.length > 8
                width: Math.min(320, parent.width * 0.4)
                height: parent.height
                placeholderText: "Find a playlist"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                font.pixelSize: 13
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: findField.activeFocus ? Theme.colors.accent
                                                        : Theme.colors.border
                }
                onTextChanged: {
                    root.query = findField.text
                    grid.contentY = 0
                }
            }

            Label {
                objectName: "playlistCount"
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                color: Theme.colors.textMuted
                font.pixelSize: 12
                readonly property string counted:
                    root.query.trim() === "" ? root.everyone.length + " playlists"
                                             : root.shown.length + " of " + root.everyone.length
                text: App.channelPlaylistsBusy
                      ? counted + " · reading the rest"
                      : counted
            }
        }

        GridView {
            id: grid
            objectName: "channelPlaylistsGrid"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: findRow.visible ? findRow.bottom : parent.top
            anchors.bottom: parent.bottom
            // No side margin of its own. This view is anchored to the edges
            // the grid of videos occupies, which carries that margin already,
            // and a second one here would make the cells narrower than a
            // video's and break the match at the widths where a column is
            // won or lost.
            anchors.topMargin: 10
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            cacheBuffer: 400
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            // The rule the grid of videos uses, copied on purpose rather than
            // chosen again here. The two views are anchored to the same edges,
            // so with the same rule a row holds as many playlists as it holds
            // videos at every window width, and a wheel notch moves the same
            // distance over either.
            readonly property int columnCount: Math.max(2, Math.floor(width / 330))
            cellWidth: Math.max(200, Math.floor(width / columnCount))
            cellHeight: cellWidth * 9 / 16 + 108

            model: root.shown

            delegate: Item {
                width: grid.cellWidth
                height: grid.cellHeight

                required property var modelData

                PlaylistCard {
                    id: tile
                    objectName: "playlistTile"
                    anchors.fill: parent
                    anchors.margins: 6
                    title: parent.modelData.title
                    thumbnail: parent.modelData.thumbnail
                    itemsText: parent.modelData.itemsText
                    kept: parent.modelData.kept
                    onOpenRequested: App.openChannelPlaylist(tile.parent.modelData.key,
                                                             tile.parent.modelData.title)
                    onKeepRequested: App.keepPlaylist(tile.parent.modelData.key,
                                                      !tile.parent.modelData.kept)
                }
            }
        }
    }

    // What the page says when it is not yet drawing tiles. Reading a tab of a
    // thousand playlists takes seconds, and until this said so an empty page
    // was the only answer a channel gave while its list was on its way.
    Label {
        objectName: "playlistsWord"
        anchors.centerIn: parent
        visible: root.shown.length === 0
        horizontalAlignment: Text.AlignHCenter
        text: App.channelPlaylistsBusy ? "Reading the playlists of this channel."
              : root.everyone.length === 0 ? "No playlists on this channel."
                                           : "No playlist here by that name."
        color: Theme.colors.textMuted
        font.pixelSize: 13
    }
}
