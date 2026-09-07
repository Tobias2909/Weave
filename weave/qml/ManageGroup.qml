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
    height: Math.min(Math.max(4, root.members.length) * 46 + 194,
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
    property var members: []

    function reload() {
        // Negative is All, which is asked for the same way. It is not a row in
        // the groups table, so the bridge answers it with a query instead.
        members = App.groupChannels(root.groupId)
    }

    onOpened: {
        reload()
        // Names and pictures arrive from the channel's own page. One put in a
        // group off a video card usually has neither yet.
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
                                           ? "Twitch" : "reading its page")
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
                text: root.members.length === 1 ? "1 channel"
                                                : root.members.length + " channels"
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
