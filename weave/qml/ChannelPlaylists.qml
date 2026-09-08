import QtQuick
import QtQuick.Controls

// The playlists a channel has made, as tiles. Names only until one is opened,
// because the tab that lists them carries no video count and a real count is
// one request per playlist. Opening one is what fills that in, free.
Flickable {
    id: root
    objectName: "channelPlaylists"

    // One row of tiles, so a wheel notch over this moves as far as it does
    // over the grid of videos. Read from outside, since the thing that turns
    // a notch into a distance has to be declared beside a Flickable rather
    // than inside one: a child of a Flickable is reparented into content that
    // moves.
    readonly property real rowHeight: tileHeight + flow.spacing
    readonly property real tileWidth: Math.max(240, Math.floor((root.width - 40) / 3))
    readonly property real tileHeight: tileWidth * 9 / 16 + 96

    contentHeight: flow.height + 20
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    Flow {
        id: flow
        x: 10
        y: 10
        width: root.width - 20
        spacing: 10

        Repeater {
            model: App.channelPlaylists

            PlaylistCard {
                id: tile
                objectName: "playlistTile"
                required property var modelData

                width: root.tileWidth
                height: root.tileHeight
                title: modelData.title
                thumbnail: modelData.thumbnail
                itemsText: modelData.itemsText
                kept: modelData.kept
                onOpenRequested: App.openChannelPlaylist(tile.modelData.key, tile.modelData.title)
                onKeepRequested: App.keepPlaylist(tile.modelData.key, !tile.modelData.kept)
            }
        }
    }

    Label {
        anchors.centerIn: parent
        visible: App.channelPlaylists.length === 0
        horizontalAlignment: Text.AlignHCenter
        text: "No playlists on this channel."
        color: Theme.colors.textMuted
        font.pixelSize: 13
    }
}
