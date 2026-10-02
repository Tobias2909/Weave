import QtQuick
import QtQuick.Controls

// Asks before a box of songs is made into a playlist on the account. This is
// a write to YouTube, the only one besides the listening note, so it says so
// in words, offers the name and who may see it, and does nothing until the
// button that names the act is pressed.
Popup {
    id: root
    objectName: "makePlaylist"

    property int boxId: -1
    property string boxName: ""
    property int songCount: 0
    property string privacy: "PRIVATE"

    anchors.centerIn: parent
    width: Math.min(440, (parent ? parent.width : 500) - 80)
    padding: 16
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: 8
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border
    }

    function ask(id, name, count) {
        boxId = id
        boxName = name
        songCount = count
        privacy = "PRIVATE"
        playlistName.text = name
        open()
        playlistName.forceActiveFocus()
        playlistName.selectAll()
    }

    function commit() {
        var name = playlistName.text.trim()
        if (name === "")
            return
        App.makePlaylistFromBox(root.boxId, name, root.privacy)
        root.close()
    }

    Column {
        width: parent.width
        spacing: 10

        Label {
            text: "Make a playlist on YouTube"
            color: Theme.colors.text
            font.pixelSize: 15
            font.weight: Font.DemiBold
        }

        Label {
            width: parent.width
            text: "The " + (root.songCount === 1 ? "song" : root.songCount + " songs")
                  + " in " + root.boxName + " go into a new playlist on your account, in the "
                  + "box's order. The box stays as it is. This writes to your YouTube account, "
                  + "and the playlist is yours to keep or delete there."
            color: Theme.colors.textMuted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }

        TextField {
            id: playlistName
            objectName: "makePlaylistName"
            width: parent.width
            color: Theme.colors.text
            placeholderText: "Road trip"
            placeholderTextColor: Theme.colors.textMuted
            background: Rectangle {
                radius: 6
                color: Theme.colors.background
                border.width: 1
                border.color: playlistName.activeFocus ? Theme.colors.accent
                                                       : Theme.colors.border
            }
            onAccepted: root.commit()
        }

        Row {
            spacing: 10

            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: "Who can see it"
                color: Theme.colors.text
                font.pixelSize: 12
            }

            ChoiceButton {
                objectName: "makePlaylistPrivacy"
                choices: [{ "value": "PRIVATE", "label": "Only you" },
                          { "value": "UNLISTED", "label": "Anyone with the link" },
                          { "value": "PUBLIC", "label": "Everyone" }]
                current: root.privacy
                usual: "PRIVATE"
                onChosen: (value) => root.privacy = value
            }
        }

        Row {
            spacing: 8
            anchors.right: parent.right

            FlatButton {
                text: "Cancel"
                onClicked: root.close()
            }

            FlatButton {
                objectName: "makePlaylistGo"
                text: "Make the playlist"
                accent: true
                enabled: playlistName.text.trim() !== ""
                onClicked: root.commit()
            }
        }
    }
}
