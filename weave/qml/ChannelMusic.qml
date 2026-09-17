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
    // Which tile a menu was opened on, said as the record it is on and the
    // place on that record. Held here because a delegate is built in its own
    // scope and cannot see an id declared around it.
    property int askedGroup: -1
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
            visible: groups.count === 0
            text: App.channelMusicBusy ? "Looking for the music"
                                       : "No music for this channel"
            color: Theme.colors.textMuted
            font.pixelSize: 12
            topPadding: 10
        }

        // What was read last time is drawn at once, and the reading that
        // replaces it takes several seconds. Without this line the page looks
        // finished while it is still working, and then changes under the hand.
        Label {
            objectName: "channelMusicRefreshing"
            visible: App.channelMusicBusy && groups.count > 0
            text: "Checking for new records"
            color: Theme.colors.textMuted
            font.pixelSize: 11
        }

        // One block per record. The songs of an album belong together and in
        // the order they were put in, which a single shelf of every song an
        // artist ever released cannot show at all.
        Repeater {
            id: groups
            model: App.channelMusicGroups

            Column {
                id: groupBlock
                required property var modelData
                required property int index
                width: root.width
                spacing: 8
                topPadding: 6

                Row {
                    spacing: 10

                    RoundedImage {
                        objectName: "groupPicture"
                        // Asked while it is still a string. Read back off the
                        // item it is a QUrl, and a QUrl never equals a string,
                        // so an absent picture would hold its room open.
                        readonly property string address: groupBlock.modelData.picture || ""
                        visible: address !== ""
                        width: 56
                        height: 56
                        radius: 6
                        source: address
                    }

                    Column {
                        spacing: 2

                        Label {
                            objectName: "groupTitle"
                            text: groupBlock.modelData.title
                            color: Theme.colors.text
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Label {
                            objectName: "groupNote"
                            text: {
                                var parts = []
                                if (groupBlock.modelData.kind === "album")
                                    parts.push("Album")
                                else if (groupBlock.modelData.kind === "singles")
                                    parts.push("Singles, heard in no order")
                                if ((groupBlock.modelData.year || "") !== "")
                                    parts.push(groupBlock.modelData.year)
                                var count = groupBlock.modelData.songs.length
                                parts.push(count + (count === 1 ? " song" : " songs"))
                                return parts.join("  ·  ")
                            }
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                        }
                    }
                }

                Flow {
                    width: root.width
                    spacing: root.tileSpacing

                    Repeater {
                        model: groupBlock.modelData.songs

                        MusicTile {
                            objectName: "groupSong"
                            required property var modelData
                            required property int index
                            width: root.tileSize
                            height: root.tileSize
                            title: modelData.title
                            subtitle: modelData.artist
                            picture: modelData.thumbnail
                            // The name leads somewhere only when the song
                            // carries an address for whoever made it, which a
                            // compilation does not, so it is not drawn as a
                            // link on those.
                            subtitleLeads: (modelData.artistId || "") !== ""

                            onChosen: App.playChannelGroupSong(groupBlock.index, index)
                            onSubtitleChosen: App.openArtistMusic(modelData.artistId)
                            onAskedFor: {
                                root.askedGroup = groupBlock.index
                                root.asked = index
                                songMenu.popup()
                            }
                        }
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
                App.queueChannelGroupSong(root.askedGroup, root.asked, true)
                songMenu.dismiss()
            }
        }

        ThemedMenuItem {
            objectName: "channelMusicQueue"
            visible: Audio.hasQueue
            height: visible ? implicitHeight : 0
            text: "Add to the queue"
            onTriggered: {
                App.queueChannelGroupSong(root.askedGroup, root.asked, false)
                songMenu.dismiss()
            }
        }

        ThemedMenuItem {
            objectName: "channelMusicFavorite"
            readonly property bool kept: root.asked >= 0 && root.askedGroup >= 0
                                         && App.channelGroupSongIsFavorite(
                                                root.askedGroup, root.asked)
            text: kept ? "Remove from favorites" : "Add to favorites"
            onTriggered: {
                App.favoriteChannelGroupSong(root.askedGroup, root.asked)
                songMenu.dismiss()
            }
        }
    }
}
