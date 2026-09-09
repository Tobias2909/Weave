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

        // What the last press of the members button found, over the banner
        // where the eye already is. It is about a press, so it is here only
        // after one and only on the channel it was about.
        Rectangle {
            id: noteCard
            objectName: "membersNote"

            // Read once into a property of its own, so the animation below has
            // something to react to and the label is not the only thing that
            // knows the words changed.
            readonly property string words: header.info.membersNote || ""
            // How much of its time has gone, 0 to 1. The bar IS the timer:
            // what is drawn and the moment the words go are the same thing,
            // rather than an animation beside a timer that can drift from it.
            property real spent: 0

            visible: words !== ""
            anchors.centerIn: parent
            width: Math.min(parent.width - 60, noteText.implicitWidth + 32)
            height: noteText.implicitHeight + 24
            radius: 8
            color: Qt.rgba(Qt.color(Theme.colors.surfaceRaised).r,
                           Qt.color(Theme.colors.surfaceRaised).g,
                           Qt.color(Theme.colors.surfaceRaised).b, 0.94)
            border.width: 1
            border.color: Theme.colors.border

            // Which answer this is. The words cannot say "asked again" on
            // their own, so pressing the button twice and being told the same
            // thing would leave the second answer running out the first one's
            // clock and vanishing early.
            readonly property int said: header.info.membersNoteAt || 0

            // Restarted rather than merely started, so every answer gets its
            // own full time whether or not it reads like the last one.
            onSaidChanged: {
                noteCard.spent = 0
                if (noteCard.words !== "")
                    countdown.restart()
            }

            onWordsChanged: {
                if (noteCard.words === "") {
                    countdown.stop()
                    noteCard.spent = 0
                }
            }

            NumberAnimation {
                id: countdown
                objectName: "membersNoteCountdown"
                target: noteCard
                property: "spent"
                from: 0
                to: 1
                duration: 25000
                onFinished: App.clearMembersNote()
            }

            Label {
                id: noteText
                objectName: "membersNoteText"
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 10
                width: Math.min(header.width - 92, implicitWidth)
                text: noteCard.words
                color: Theme.colors.text
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }

            // The time running out, along the foot of the card. Inside the
            // border rather than over it, and rounded at the left end only, so
            // it reads as filling the card rather than as a line drawn on it.
            Rectangle {
                objectName: "membersNoteBar"
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 2
                height: 3
                width: (parent.width - 4) * Math.max(0, Math.min(1, noteCard.spent))
                radius: 1.5
                color: Theme.colors.accent
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
                // It stays whatever the answer was. A channel can open a
                // membership later, and a button that disappears without a
                // word looks like one that broke rather than one with nothing
                // to do. What it found is said on the banner instead.
                visible: header.info.platform !== "twitch"
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
