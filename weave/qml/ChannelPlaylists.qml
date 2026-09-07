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

            Rectangle {
                id: tile
                objectName: "playlistTile"
                required property var modelData

                width: Math.max(200, Math.floor((flow.width - 20) / 3))
                height: 84
                radius: 8
                color: hover.hovered ? Theme.colors.surfaceRaised : Theme.colors.surface
                border.width: 1
                border.color: Theme.colors.border

                HoverHandler { id: hover }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: App.openChannelPlaylist(tile.modelData.key, tile.modelData.title)
                }

                Column {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 6

                    Label {
                        width: parent.width
                        text: tile.modelData.title
                        color: Theme.colors.text
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        maximumLineCount: 2
                        wrapMode: Text.Wrap
                    }

                    Label {
                        // Nothing until it has been opened, rather than a
                        // confident zero for something nobody has counted.
                        text: tile.modelData.itemsText !== "" ? tile.modelData.itemsText
                                                              : "not read yet"
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                    }
                }

                // Keeping it puts it in the panel and holds it through every
                // reading of your own playlists, which never mention it.
                FlatButton {
                    objectName: "keepPlaylist"
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 8
                    visible: hover.hovered || tile.modelData.kept
                    text: tile.modelData.kept ? "Kept" : "Keep"
                    accent: tile.modelData.kept
                    onClicked: App.keepPlaylist(tile.modelData.key, !tile.modelData.kept)
                }
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
