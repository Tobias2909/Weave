import QtQuick
import QtQuick.Controls

// One video. Every colour comes from the Theme role map, never a literal, so
// the planned gradient themes need no changes in here.
Rectangle {
    id: card

    property string title: ""
    property string channelTitle: ""
    property string channelAvatar: ""
    property string thumbnail: ""
    property string ageText: ""
    property string durationText: ""
    property string viewsText: ""
    property string likesText: ""
    property bool watched: false
    property bool isLive: false
    property real progress: 0

    signal playRequested()
    signal channelRequested()
    signal menuRequested()
    signal listenRequested()

    radius: 8
    color: hover.hovered ? Theme.colors.surfaceRaised : Theme.colors.surface
    border.width: 1
    border.color: hover.hovered ? Theme.colors.accent : Theme.colors.border
    opacity: watched ? 0.55 : 1.0

    HoverHandler { id: hover }

    TapHandler {
        // Left click plays in mpv. That is the most common action, so it costs
        // no extra step.
        onTapped: card.playRequested()
    }
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: card.menuRequested()
    }

    Column {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        Item {
            width: parent.width
            height: width * 9 / 16

            Rectangle {
                id: thumbnailFrame
                anchors.fill: parent
                radius: 8
                color: Theme.colors.background

                RoundedImage {
                    anchors.fill: parent
                    radius: parent.radius
                    source: card.thumbnail
                    // Pictures are served by the disk cache provider, so the
                    // source is already an image:// address.
                }

                // A moving thumbnail replaces the still on hover in a later step.

                // Where playback stopped, read out of mpv's own resume files.
                // Present only while a video is partially watched, because a
                // video that reached the end leaves no resume file behind.
                Rectangle {
                    visible: card.progress > 0
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 3
                    color: Theme.colors.badgeBackground
                    // Matches the frame so the bar does not poke out past the
                    // rounded corners. Qt clamps this to half the height.
                    bottomLeftRadius: thumbnailFrame.radius
                    bottomRightRadius: thumbnailFrame.radius

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: parent.width * Math.min(1, card.progress)
                        color: Theme.colors.progress
                        bottomLeftRadius: thumbnailFrame.radius
                    }
                }
            }

            // Sound without a window. Only on hover, so it costs no layout.
            Rectangle {
                visible: hover.hovered
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 6
                width: 26
                height: 26
                radius: 13
                color: listenHover.hovered ? Theme.colors.accent : Theme.colors.badgeBackground

                HoverHandler { id: listenHover }
                // A MouseArea rather than a TapHandler. Handlers do not consume
                // the press, so the card underneath started the video in mpv as
                // well, which is the opposite of what this button is for.
                MouseArea {
                    anchors.fill: parent
                    onClicked: card.listenRequested()
                }

                Text {
                    anchors.centerIn: parent
                    text: "🎧"
                    font.pixelSize: 13
                }
            }

            Rectangle {
                visible: card.durationText !== "" || card.isLive
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 6
                anchors.bottomMargin: card.progress > 0 ? 9 : 6
                radius: 3
                color: card.isLive ? Theme.colors.live : Theme.colors.badgeBackground
                width: badge.implicitWidth + 10
                height: badge.implicitHeight + 4
                Text {
                    id: badge
                    anchors.centerIn: parent
                    text: card.isLive ? "LIVE" : card.durationText
                    color: Theme.colors.badgeText
                    font.pixelSize: 11
                    font.bold: card.isLive
                }
            }
        }

        Text {
            width: parent.width
            text: card.title
            color: card.watched ? Theme.colors.watchedDim : Theme.colors.text
            font.pixelSize: 13
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }

        // The channel line is its own click target, so a left click here opens
        // the channel page rather than starting the video.
        Row {
            id: channelRow
            width: parent.width
            spacing: 6

            HoverHandler { id: channelHover }
            TapHandler {
                gesturePolicy: TapHandler.ReleaseWithinBounds
                onTapped: card.channelRequested()
            }

            RoundedImage {
                width: 24
                height: 24
                circle: true
                visible: card.channelAvatar !== ""
                source: card.channelAvatar
            }

            Text {
                width: channelRow.width - (card.channelAvatar !== "" ? 30 : 0)
                text: card.channelTitle
                color: channelHover.hovered ? Theme.colors.text : Theme.colors.textMuted
                font.pixelSize: 12
                font.underline: channelHover.hovered
                elide: Text.ElideRight
            }
        }

        Text {
            width: parent.width
            color: Theme.colors.textMuted
            font.pixelSize: 11
            elide: Text.ElideRight
            text: {
                var parts = []
                if (card.viewsText !== "") parts.push(card.viewsText + " views")
                if (card.likesText !== "") parts.push(card.likesText + " likes")
                if (card.ageText !== "") parts.push(card.ageText)
                return parts.join("  ·  ")
            }
        }
    }
}
