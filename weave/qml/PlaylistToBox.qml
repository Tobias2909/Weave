import QtQuick
import QtQuick.Controls

// Picks a playlist to copy into a new box of songs. Yours first, then the
// ones kept off a channel page. The playlist itself stays as it is, and one
// never opened here is read first, which the row says.
Popup {
    id: root
    objectName: "playlistToBox"

    // Taken when it opens, so the list holds still under the hand. A filter
    // narrows it, and the window is fitted to how many there are rather than
    // to what the filter shows, or it would shrink while being typed into.
    property var playlists: []
    readonly property var shown: {
        var words = filter.text.trim().toLowerCase()
        if (words === "")
            return root.playlists
        return root.playlists.filter(row => row.title.toLowerCase().indexOf(words) >= 0)
    }

    anchors.centerIn: parent
    width: Math.min(460, (parent ? parent.width : 500) - 80)
    height: Math.min((parent ? parent.height : 600) - 80,
                     Math.max(4, Math.min(12, root.playlists.length)) * 34 + 150)
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

    function pick() {
        root.playlists = App.playlistsForBoxes()
        filter.text = ""
        open()
        filter.forceActiveFocus()
    }

    Column {
        anchors.fill: parent
        spacing: 10

        Label {
            text: "New box from a playlist"
            color: Theme.colors.text
            font.pixelSize: 15
            font.weight: Font.DemiBold
        }

        Label {
            width: parent.width
            text: "Its songs are copied into a new box of the same name. The playlist "
                  + "stays as it is."
            color: Theme.colors.textMuted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }

        TextField {
            id: filter
            objectName: "playlistToBoxFilter"
            width: parent.width
            color: Theme.colors.text
            placeholderText: "Find a playlist"
            placeholderTextColor: Theme.colors.textMuted
            background: Rectangle {
                radius: 6
                color: Theme.colors.background
                border.width: 1
                border.color: filter.activeFocus ? Theme.colors.accent : Theme.colors.border
            }
        }

        ListView {
            objectName: "playlistToBoxList"
            width: parent.width
            // What the words above leave, so every row fits that the window
            // was sized for.
            height: Math.max(0, parent.height - y)
            clip: true
            model: root.shown
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            // Handed down, since a delegate cannot see the ids around it.
            property var owner: root

            // In the empty list itself, where there is room for it.
            Label {
                visible: root.shown.length === 0
                x: 8
                y: 8
                text: root.playlists.length === 0 ? "There are no playlists here yet."
                                                  : "No playlist has that in its name."
                color: Theme.colors.textMuted
                font.pixelSize: 12
            }

            delegate: Rectangle {
                id: choice
                required property var modelData
                width: ListView.view.width - 12
                height: 34
                radius: 5
                color: choiceHover.hovered ? Theme.wash(Theme.colors.accent, 0.14) : "transparent"

                HoverHandler { id: choiceHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    onTapped: {
                        App.boxFromPlaylist(choice.modelData.id)
                        choice.ListView.view.owner.close()
                    }
                }

                Label {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.right: facts.left
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    text: choice.modelData.title
                    color: Theme.colors.text
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }

                Label {
                    id: facts
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: (choice.modelData.linked ? "linked  ·  " : "")
                          + (!choice.modelData.read ? "read first"
                             : choice.modelData.count === 1 ? "1 video"
                             : choice.modelData.count + " videos")
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                }
            }
        }
    }
}
