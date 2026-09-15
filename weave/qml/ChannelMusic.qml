import QtQuick
import QtQuick.Controls

// The music a channel releases, as squares rather than as a list. The same
// shape the music page uses for anything you pick rather than read, which also
// gives the artwork room enough to be worth looking at.
//
// Which artist this is does not always answer to the same channel. Much of what
// an artist puts out is uploaded by a separate generated channel, so the page
// asks the music service who made this channel's videos rather than assuming
// the two are one. When the answer is somebody else, the line at the top says
// so, or a stranger's songs under a familiar name would read as the wrong page.
Flickable {
    id: root
    objectName: "channelMusic"

    readonly property int tileSize: 132
    readonly property int tileSpacing: 10
    // Read from outside, because the thing that turns a wheel notch into a
    // distance has to be declared beside a Flickable rather than inside one:
    // a child of a Flickable is reparented into content that moves.
    readonly property real rowHeight: tileSize + tileSpacing
    // Which tile a menu was opened on. Held here because a delegate is built
    // in its own scope and cannot see an id declared around it.
    property int asked: -1

    contentWidth: width
    contentHeight: body.height + 20
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    Column {
        id: body
        width: root.width
        spacing: 10

        Label {
            objectName: "channelMusicBy"
            visible: App.channelMusicBy !== ""
            text: "Released as " + App.channelMusicBy
            color: Theme.colors.textMuted
            font.pixelSize: 11
            topPadding: 4
        }

        Label {
            objectName: "channelMusicNote"
            visible: songs.count === 0
            text: App.channelMusicBusy ? "Looking for the music"
                                       : "No music for this channel"
            color: Theme.colors.textMuted
            font.pixelSize: 12
            topPadding: 10
        }

        Flow {
            width: root.width
            spacing: root.tileSpacing

            Repeater {
                id: songs
                model: App.channelMusic

                MusicTile {
                    required property var modelData
                    required property int index
                    width: root.tileSize
                    height: root.tileSize
                    title: modelData.title
                    subtitle: modelData.artist
                    picture: modelData.thumbnail
                    // The name leads somewhere only when the song carries an
                    // address for whoever made it, which a compilation does
                    // not, so it is not drawn as a link on those.
                    subtitleLeads: (modelData.artistId || "") !== ""

                    onChosen: App.playChannelMusic(index)
                    onSubtitleChosen: App.openArtistMusic(modelData.artistId)
                    onAskedFor: {
                        root.asked = index
                        songMenu.popup()
                    }
                }
            }
        }
    }

    // The same three the music page offers, because a song is a song wherever
    // it is drawn and two menus for one act come apart the moment either grows.
    ThemedMenu {
        id: songMenu
        objectName: "channelMusicMenu"

        ThemedMenuItem {
            objectName: "channelMusicPlayNext"
            // Nothing to be next to with an empty player, and nothing to add
            // to either, so both hide rather than misleading.
            visible: Audio.hasQueue
            height: visible ? implicitHeight : 0
            text: "Play it next"
            onTriggered: {
                App.queueChannelMusic(root.asked, true)
                songMenu.dismiss()
            }
        }

        ThemedMenuItem {
            objectName: "channelMusicQueue"
            visible: Audio.hasQueue
            height: visible ? implicitHeight : 0
            text: "Add to the queue"
            onTriggered: {
                App.queueChannelMusic(root.asked, false)
                songMenu.dismiss()
            }
        }

        ThemedMenuItem {
            objectName: "channelMusicFavorite"
            readonly property bool kept: root.asked >= 0
                                         && App.channelMusicIsFavorite(root.asked)
            text: kept ? "Remove from favorites" : "Add to favorites"
            onTriggered: {
                App.favoriteChannelMusic(root.asked)
                songMenu.dismiss()
            }
        }
    }
}
