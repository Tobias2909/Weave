import QtQuick
import QtQuick.Controls

// Everything taken out of sight, in a window of its own.
//
// It was a list on the settings page, under the ceilings and the caches,
// where it grew past what that page can hold and made every other row on it
// harder to find. The one hidden last is on top, since somebody opening this
// is nearly always after what they have just put away, and the search is
// there because a list of several hundred is not read through.
Popup {
    id: root
    objectName: "hiddenVideosWindow"

    anchors.centerIn: parent
    // The same size as the playlist windows. Two windows that do the same
    // thing to two lists are one window as far as the eye is concerned.
    width: Math.min(560, (parent ? parent.width : 640) - 80)
    // Fitted to how many there are rather than fixed, since a window sized
    // for a dozen holding three reads as a window that failed to load them.
    // The room for four keeps it from jumping about as one is brought back,
    // and it is sized by how many are hidden rather than by how many a search
    // is showing, or it would grow and shrink under the hand that is typing.
    height: Math.min(Math.max(4, root.everyone.length) * 54 + 206,
                     (parent ? parent.height : 600) - 80)
    padding: 16
    modal: true
    focus: true

    background: Rectangle {
        radius: 8
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border
    }

    // A snapshot, not a live binding. A list that rebuilds itself sends the
    // rows back to the top under the hand that just pressed one, which is the
    // trap the playlist chooser and the group window both document.
    property var everyone: []
    property var shown: []
    property string filter: ""

    function apply() {
        var wanted = root.filter.trim().toLowerCase()
        if (wanted === "") {
            shown = root.everyone
            return
        }
        var out = []
        for (var i = 0; i < root.everyone.length; i++) {
            var one = root.everyone[i]
            // The channel counts as well as the title. What somebody
            // remembers about a card they put away is as often who made it.
            if (String(one.title).toLowerCase().indexOf(wanted) !== -1
                    || String(one.channelTitle).toLowerCase().indexOf(wanted) !== -1)
                out.push(one)
        }
        shown = out
    }

    function reload() {
        // Newest first is the database's own order, so nothing is sorted here.
        everyone = App.hiddenVideos
        apply()
    }

    // Bringing one back takes its row out of the snapshot rather than reading
    // the list again, so the rest of the list stays exactly where it is.
    function bringBack(key) {
        App.unhideVideo(key)
        var left = []
        for (var i = 0; i < root.everyone.length; i++)
            if (root.everyone[i].key !== key)
                left.push(root.everyone[i])
        everyone = left
        apply()
    }

    function bringBackAll() {
        App.unhideEverything()
        everyone = []
        apply()
    }

    onOpened: {
        filter = ""
        searchField.text = ""
        reload()
        searchField.forceActiveFocus()
    }

    Column {
        anchors.fill: parent
        spacing: 10

        Label {
            text: "Hidden videos"
            color: Theme.colors.text
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }

        Label {
            width: parent.width
            text: "Hiding a video takes its card out of the feed, out of a group and out of "
                  + "the suggestions. It stays in any box you put it in and it keeps whatever "
                  + "it was marked. Bring one back and it is drawn again wherever it belongs."
            color: Theme.colors.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }

        TextField {
            id: searchField
            objectName: "hiddenSearchField"
            width: parent.width
            placeholderText: "Search by title or channel"
            color: Theme.colors.text
            placeholderTextColor: Theme.colors.textMuted
            background: Rectangle {
                radius: 6
                color: Theme.colors.background
                border.width: 1
                border.color: searchField.activeFocus ? Theme.colors.accent
                                                      : Theme.colors.border
            }
            onTextChanged: {
                root.filter = text
                root.apply()
                hiddenList.contentY = 0
            }
        }

        // Said rather than left as an empty box, which reads as a list that
        // failed to load.
        Label {
            objectName: "hiddenNothing"
            width: parent.width
            visible: root.shown.length === 0
            text: root.everyone.length === 0 ? "Nothing is hidden."
                                             : "Nothing here by that name."
            color: Theme.colors.textMuted
            font.pixelSize: 12
        }

        ListView {
            id: hiddenList
            objectName: "hiddenVideos"
            visible: root.shown.length > 0
            width: parent.width
            height: parent.height - y - hiddenCloseRow.height - 20
            clip: true
            spacing: 6
            model: root.shown
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Item {
                id: hiddenRow
                objectName: "hiddenRow"
                required property var modelData
                width: hiddenList.width - 12
                height: 48

                // Asked for while it is still a string. Read back off the
                // picture it is a QUrl, and a QUrl is never equal to a
                // string, so a test against one is always true and a row with
                // no picture holds the hole open anyway.
                readonly property string picture: modelData.thumbnail || ""

                RoundedImage {
                    id: shot
                    objectName: "hiddenThumbnail"
                    visible: hiddenRow.picture !== ""
                    width: visible ? 68 : 0
                    height: 38
                    radius: 4
                    anchors.verticalCenter: parent.verticalCenter
                    source: hiddenRow.picture
                }

                Column {
                    anchors.left: shot.visible ? shot.right : parent.left
                    anchors.leftMargin: shot.visible ? 10 : 0
                    anchors.right: bringBack.left
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Label {
                        width: parent.width
                        text: hiddenRow.modelData.title
                        color: Theme.colors.text
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        // The channel and when it was put away, which is what
                        // the order of this list is by, so the order can be
                        // read rather than taken on trust.
                        text: {
                            var parts = []
                            if (hiddenRow.modelData.channelTitle !== "")
                                parts.push(hiddenRow.modelData.channelTitle)
                            if (hiddenRow.modelData.hiddenAgo !== "")
                                parts.push("hidden " + hiddenRow.modelData.hiddenAgo)
                            return parts.join("  ·  ")
                        }
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }

                FlatButton {
                    id: bringBack
                    objectName: "bringItBack"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Bring it back"
                    onClicked: root.bringBack(hiddenRow.modelData.key)
                }
            }
        }

        Row {
            id: hiddenCloseRow
            spacing: 8
            anchors.right: parent.right

            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: root.filter.trim() !== ""
                      ? root.shown.length + " of " + root.everyone.length
                      : (root.everyone.length === 1 ? "1 video"
                                                    : root.everyone.length + " videos")
                color: Theme.colors.textMuted
                font.pixelSize: 11
            }

            FlatButton {
                objectName: "unhideEverything"
                visible: root.everyone.length > 0
                text: "Bring them all back"
                onClicked: root.bringBackAll()
            }

            FlatButton {
                text: "Done"
                accent: true
                onClicked: root.close()
            }
        }
    }
}
