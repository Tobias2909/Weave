import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Everything one group holds, in one place: who is in it, how big they are,
// and a box to put another one in.
//
// A channel added here is followed for this group and nowhere else, which is
// the whole reason the window exists. Following a channel by name is what the
// toolbar box does, and that one goes into All.
Popup {
    id: root
    objectName: "manageGroup"

    property int groupId: -1
    property string groupName: ""

    // All is managed here too. It is not a group and never will be, since it
    // is every channel followed on its own account rather than a list somebody
    // keeps, but taking a channel out of it and putting one back are the same
    // two things this window already does.
    readonly property bool isAll: groupId < 0

    anchors.centerIn: parent
    width: 460
    // Fitted to what it holds rather than fixed. A group of three channels in
    // a window sized for a dozen reads as a window that failed to load them.
    // The room for four keeps it from jumping about as one is taken out.
    // Sized by how many there are rather than by how many a search is showing,
    // or the window would shrink and grow under the hand that is typing.
    height: Math.min(Math.max(4, root.everyone.length) * 46 + 194,
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
    // same trap the playlist chooser documents.
    property var everyone: []
    property var members: []
    property string filter: ""

    function apply() {
        var wanted = root.filter.trim().toLowerCase()
        if (wanted === "") {
            members = root.everyone
            return
        }
        var out = []
        for (var i = 0; i < root.everyone.length; i++) {
            var one = root.everyone[i]
            if (String(one.title).toLowerCase().indexOf(wanted) !== -1)
                out.push(one)
        }
        members = out
    }

    function reload() {
        // Assigning the model sends the view back to the top, and a reload can
        // arrive at any moment: every channel page that comes back announces
        // itself this way. Four hundred rows in and a jump to the top every
        // half second is what that felt like, so the place is kept.
        var was = memberList.contentY
        // Negative is All, which is asked for the same way. It is not a row in
        // the groups table, so the bridge answers it with a query instead.
        everyone = App.groupChannels(root.groupId)
        apply()
        memberList.contentY = Math.max(0, Math.min(was, memberList.contentHeight
                                                        - memberList.height))
    }

    onOpened: {
        App.clearAddState()
        filter = ""
        searchField.text = ""
        reload()
        // Names and pictures arrive from the channel's own page. One put in a
        // group off a video card usually has neither yet. Not for All, where
        // every channel came from the subscription list with a name and a
        // picture already and the only thing missing is a follower count,
        // which is not worth a page fetch each for several hundred of them.
        if (!root.isAll)
            App.fillGroupDetails(root.groupId)
        addToGroupField.text = ""
        addToGroupField.forceActiveFocus()
    }

    // Adding resolves in the background, so the row cannot appear until the
    // answer comes back. Both the answer and a removal announce themselves
    // this way.
    Connections {
        target: App
        function onGroupsChanged() {
            if (root.visible)
                root.reload()
        }
    }

    Column {
        anchors.fill: parent
        spacing: 10

        Label {
            text: root.isAll ? "All"
                             : (root.groupName === "" ? "Manage the group" : root.groupName)
            color: Theme.colors.text
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }

        Label {
            width: parent.width
            text: root.isAll
                  ? "Every channel you follow is here. Taking one out keeps the channel and "
                    + "its videos, they simply stop arriving in All, and an import cannot "
                    + "put it back. A channel that is in no group either is not asked after "
                    + "at all until it is added somewhere again."
                  : "Channels added here are followed for this group only and stay out of All."
            color: Theme.colors.textMuted
            font.pixelSize: 11
            wrapMode: Text.WordWrap
        }

        TextField {
            id: addToGroupField
            objectName: "addToGroupField"
            width: parent.width
            placeholderText: "Add a channel, a handle or a twitch.tv link"
            color: Theme.colors.text
            placeholderTextColor: Theme.colors.textMuted
            background: Rectangle {
                radius: 6
                color: Theme.colors.background
                border.width: 1
                border.color: addToGroupField.activeFocus ? Theme.colors.accent
                                                          : Theme.colors.border
            }
            // Kept on a reference that was not even understood, so a typo can
            // be corrected rather than retyped.
            onAccepted: {
                if (App.addChannelToGroupByRef(root.groupId, text))
                    text = ""
            }
            // An answer about the last reference must not be read as one
            // about what is being typed now.
            onTextEdited: App.clearAddState()
        }

        // Whether that worked. The status line in the toolbar says so too,
        // but this window is drawn over it, so without this a reference that
        // was misspelled looked exactly like one that was accepted.
        Label {
            objectName: "manageAddAnswer"
            width: parent.width
            visible: App.addMessage !== ""
            // No height binding. A wrapping label's implicit height comes
            // from its width, and tying the height back to it is a loop the
            // engine complains about. A Column skips what is not visible, so
            // there is nothing to collapse by hand.
            text: App.addMessage
            color: App.addState === "failed" ? Theme.colors.error
                                             : (App.addState === "added" ? Theme.colors.accent
                                                                         : Theme.colors.textMuted)
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }

        // Four hundred and sixty six channels is not a list anybody reads
        // through, so it is searched instead. Only the names, since that is
        // what somebody looking for one of them has.
        TextField {
            id: searchField
            objectName: "manageSearchField"
            visible: root.everyone.length > 8
            width: parent.width
            height: visible ? implicitHeight : 0
            placeholderText: "Search these channels"
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
                memberList.contentY = 0
            }
        }

        ListView {
            id: memberList
            objectName: "manageGroupList"
            width: parent.width
            height: parent.height - y - manageCloseRow.height - 20
            clip: true
            model: root.members
            spacing: 2
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Item {
                id: memberRow
                objectName: "manageGroupRow"
                required property var modelData
                width: memberList.width - 12
                height: 44

                RoundedImage {
                    id: picture
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: 32
                    height: 32
                    circle: true
                    source: memberRow.modelData.avatar
                    visible: memberRow.modelData.avatar !== ""
                }

                // A channel with no picture yet still needs its row to line up
                // with the others.
                Rectangle {
                    anchors.fill: picture
                    radius: width / 2
                    color: Theme.colors.border
                    visible: memberRow.modelData.avatar === ""
                }

                Column {
                    anchors.left: picture.right
                    anchors.leftMargin: 10
                    anchors.right: dropButton.left
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Label {
                        width: parent.width
                        text: memberRow.modelData.title
                        color: Theme.colors.text
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        // Said rather than left blank, so a row that is still
                        // waiting for its page looks like it is waiting.
                        text: {
                            var parts = []
                            if (memberRow.modelData.followersText !== "")
                                parts.push(memberRow.modelData.followersText + " following")
                            // Only worth saying inside a group, where it
                            // answers whether this channel shows anywhere
                            // else. In All itself it says nothing.
                            if (memberRow.modelData.inAll && !root.isAll)
                                parts.push("also in All")
                            if (parts.length === 0)
                                parts.push(memberRow.modelData.platform === "twitch"
                                           ? "Twitch"
                                           : (root.isAll ? "" : "reading its page"))
                            return parts.join("  ·  ")
                        }
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }

                FlatButton {
                    id: dropButton
                    objectName: "manageGroupRemove"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Remove"
                    onClicked: App.removeChannelFromGroup(root.groupId, memberRow.modelData.key)
                }
            }
        }

        Row {
            id: manageCloseRow
            spacing: 8
            anchors.right: parent.right

            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: root.filter.trim() !== ""
                      ? root.members.length + " of " + root.everyone.length
                      : (root.everyone.length === 1 ? "1 channel"
                                                    : root.everyone.length + " channels")
                color: Theme.colors.textMuted
                font.pixelSize: 11
            }

            FlatButton {
                text: "Done"
                accent: true
                onClicked: root.close()
            }
        }
    }
}
