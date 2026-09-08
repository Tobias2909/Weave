import QtQuick
import QtQuick.Controls

// The band above the grid on a channel page. The banner and the subscriber
// count are fetched the first time a channel page is opened, so this renders
// without them and fills in when they arrive.
Item {
    id: header
    property var info: ({})
    signal closeRequested()
    signal groupsRequested()

    height: visible ? 168 : 0

    Rectangle {
        anchors.fill: parent
        color: Theme.colors.surface
        clip: true

        Image {
            id: bannerImage
            anchors.fill: parent
            source: header.info.banner ? header.info.banner : ""
            visible: source !== ""
            asynchronous: true
            cache: true
            fillMode: Image.PreserveAspectCrop
            // Dimmed, but meant to be seen. The gradient below is what keeps
            // the text legible, so this does not have to be faint as well.
            opacity: 0.8
        }

        // Keeps the text legible whatever the banner looks like.
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: Theme.colors.surface }
            }
        }

        Row {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: 20
            anchors.bottomMargin: 16
            spacing: 14

            Item {
                width: 76
                height: 76

                RoundedImage {
                    anchors.fill: parent
                    anchors.margins: 2
                    circle: true
                    source: header.info.avatar ? header.info.avatar : ""
                }

                // A ring, so the icon reads against whatever the banner is.
                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: "transparent"
                    border.width: 2
                    border.color: Theme.colors.surface
                    antialiasing: true
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4

                Label {
                    text: header.info.title ? header.info.title : ""
                    color: Theme.colors.text
                    font.pixelSize: 22
                    font.weight: Font.Bold
                }

                Label {
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    text: {
                        var parts = []
                        if (header.info.followersText)
                            parts.push(header.info.followersText + " subscribers")
                        if (header.info.videos > 0)
                            parts.push(header.info.videos + " videos here")
                        return parts.join("  ·  ")
                    }
                }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 12
            spacing: 8

            // What is behind this channel's membership. It is in no other
            // feed at all, so nothing is read until this is pressed, and
            // pressing it reads now rather than waiting for the poller to
            // come round to this channel, which can be hours.
            //
            // Only where there is a question to ask. A channel already found
            // to sell nothing stops offering it rather than offering a button
            // whose only answer is to say so again, and Twitch has no such
            // thing at all.
            FlatButton {
                objectName: "channelMembers"
                visible: header.info.platform !== "twitch"
                         && header.info.sellsMembership === true
                text: header.info.membersWanted ? "Members on" : "Members"
                accent: header.info.membersWanted === true
                onClicked: App.wantMembers(header.info.key, !header.info.membersWanted)
            }
            FlatButton {
                text: "Groups"
                onClicked: header.groupsRequested()
            }
            FlatButton {
                // Where a step back actually lands, since a channel page is
                // opened from the feed, a group, a box and a search alike.
                text: App.backLabel !== "" ? App.backLabel : "Back to the feed"
                onClicked: header.closeRequested()
            }
        }

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.colors.border
        }
    }
}
