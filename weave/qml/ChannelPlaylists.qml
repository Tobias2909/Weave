import QtQuick
import QtQuick.Controls

// The playlists a channel has made, as tiles. Names only until one is opened,
// because the tab that lists them carries no video count and a real count is
// one request per playlist. Opening one is what fills that in, free.
Flickable {
    id: root
    objectName: "channelPlaylists"

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

                width: Math.max(240, Math.floor((flow.width - 20) / 3))
                height: width * 9 / 16 + 96
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
