import QtQuick
import QtQuick.Controls

// The music a channel releases, as songs rather than as videos.
//
// Which artist that is does not always answer to the same channel. Much of what
// an artist puts out is uploaded by a separate generated channel, so the page
// asks the music service who made this channel's videos rather than assuming
// the two are one. When the answer is somebody else, the line at the top says
// so, or a stranger's songs under a familiar name would read as the wrong page.
ListView {
    id: root
    objectName: "channelMusic"

    // Read from outside, because the thing that turns a wheel notch into a
    // distance has to be declared beside a Flickable rather than inside one.
    readonly property real rowHeight: 52
    // Which row a menu was opened on. A delegate cannot see an id declared
    // around it, so the menu is reached through the view.
    property int asked: -1
    property var owner: songMenu

    clip: true
    spacing: 2
    model: App.channelMusic
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    header: Item {
        width: root.width
        height: byLine.visible ? 30 : 8

        Label {
            id: byLine
            objectName: "channelMusicBy"
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            visible: App.channelMusicBy !== ""
            text: "Released as " + App.channelMusicBy
            color: Theme.colors.textMuted
            font.pixelSize: 11
        }
    }

    Label {
        anchors.centerIn: parent
        objectName: "channelMusicNote"
        visible: root.count === 0
        text: App.channelMusicBusy ? "Looking for the music"
                                   : "No music for this channel"
        color: Theme.colors.textMuted
        font.pixelSize: 12
    }

    delegate: Rectangle {
        id: songRow
        required property var modelData
        required property int index
        width: root.width
        height: root.rowHeight
        radius: 5
        color: songHover.hovered ? Theme.colors.surface : "transparent"

        HoverHandler { id: songHover }

        // A MouseArea rather than a handler, so the press is consumed and the
        // row underneath does not take it as well.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: function (mouse) {
                if (mouse.button === Qt.RightButton) {
                    var menu = songRow.ListView.view.owner
                    songRow.ListView.view.asked = songRow.index
                    menu.popup()
                    return
                }
                App.playChannelMusic(songRow.index)
            }
        }

        Row {
            anchors.fill: parent
            anchors.margins: 5
            spacing: 10

            RoundedImage {
                width: parent.height
                height: parent.height
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                visible: (songRow.modelData.thumbnail || "") !== ""
                source: songRow.modelData.thumbnail ? songRow.modelData.thumbnail : ""
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - parent.height - 70
                spacing: 1
                Label {
                    width: parent.width
                    text: songRow.modelData.title
                    color: Theme.colors.text
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
                Label {
                    width: parent.width
                    visible: (songRow.modelData.artist || "") !== ""
                    text: songRow.modelData.artist
                    color: Theme.colors.textMuted
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }

            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: songRow.modelData.duration ? songRow.modelData.duration : ""
                color: Theme.colors.textMuted
                font.pixelSize: 11
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
