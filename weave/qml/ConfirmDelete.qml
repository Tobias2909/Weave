import QtQuick
import QtQuick.Controls

// Asks before a group or a box goes, and shows what is in it.
//
// Neither takes anything with it. A group keeps its channels and a box keeps
// its videos, so what this really answers is "which one was that again",
// which is why it lists what is inside rather than only warning.
Popup {
    id: root
    objectName: "confirmDelete"

    // group or box, and which one
    property string kind: "group"
    property int itemId: -1
    property string itemName: ""
    property var members: []

    readonly property bool isGroup: kind === "group"

    anchors.centerIn: parent
    width: Math.min(420, (parent ? parent.width : 500) - 80)
    height: Math.min((parent ? parent.height : 500) - 80,
                     Math.max(3, Math.min(6, members.length)) * 24 + 190)
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

    function ask(which, id, name) {
        kind = which
        itemId = id
        itemName = name
        members = which === "group" ? App.groupChannels(id) : App.boxVideos(id)
        open()
    }

    Column {
        anchors.fill: parent
        spacing: 10

        Label {
            objectName: "confirmTitle"
            width: parent.width
            text: root.isGroup ? "Delete this group?" : "Delete this box?"
            color: Theme.colors.text
            font.pixelSize: 15
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }

        Label {
            objectName: "confirmName"
            width: parent.width
            text: root.itemName
            color: Theme.colors.accent
            font.pixelSize: 13
            elide: Text.ElideRight
        }

        Label {
            width: parent.width
            text: root.members.length === 0
                  ? (root.isGroup ? "There are no channels in it."
                                  : "There are no videos in it.")
                  : (root.isGroup
                     ? root.members.length + " channel" + (root.members.length === 1 ? "" : "s")
                       + " are in it, and every one of them is kept."
                     : root.members.length + " video" + (root.members.length === 1 ? "" : "s")
                       + " are in it, and every one of them is kept.")
            color: Theme.colors.textMuted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }

        // What is inside, so the right one is the one that goes.
        ListView {
            objectName: "confirmMembers"
            width: parent.width
            height: Math.max(0, parent.height - 150)
            clip: true
            model: root.members
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Label {
                required property var modelData
                width: ListView.view.width
                height: 24
                text: modelData.title !== undefined && modelData.title !== ""
                      ? modelData.title
                      : (modelData.name !== undefined ? modelData.name : "")
                color: Theme.colors.text
                font.pixelSize: 12
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }

        Row {
            anchors.right: parent.right
            spacing: 8

            FlatButton {
                objectName: "confirmCancel"
                text: "Keep it"
                onClicked: root.close()
            }

            FlatButton {
                objectName: "confirmDeleteButton"
                text: root.isGroup ? "Delete the group" : "Delete the box"
                accent: true
                onClicked: {
                    if (root.isGroup)
                        App.deleteGroup(root.itemId)
                    else
                        App.deleteBox(root.itemId)
                    root.close()
                }
            }
        }
    }
}
