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
    property bool isUpcoming: false
    property bool canListen: true
    property string scheduledText: ""
    // Where an announced stream begins, on the reader's own clock. It takes
    // the place of the age, which for one of these is the day somebody put the
    // announcement up and answers nothing anybody asked.
    property string startsText: ""
    property real progress: 0

    signal playRequested()
    signal channelRequested()
    signal menuRequested()
    signal listenRequested()

    radius: 8
    color: hover.hovered ? Theme.colors.surfaceRaised : Theme.colors.surface
    border.width: 1
    border.color: hover.hovered ? Theme.colors.accent : Theme.colors.border
    // An announced stream is dimmed the same amount as something already
    // watched, since it cannot be played yet either. On this palette a card
    // sits close to the colour behind it, so raising this reads as almost no
    // change at all and the separation was measured away at 0.75.
    opacity: (watched || isUpcoming) ? 0.55 : 1.0

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

            // Sound without a window. Only on hover, so it costs no layout,
            // and not at all where a plain press already means listening,
            // since then it offers nothing the card does not already do.
            Rectangle {
                visible: hover.hovered && card.canListen
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
                visible: card.durationText !== "" || card.isLive || card.isUpcoming
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 6
                anchors.bottomMargin: card.progress > 0 ? 9 : 6
                radius: 4
                color: card.isLive ? Theme.colors.live
                       : card.isUpcoming ? Theme.colors.accent
                       : Theme.colors.badgeBackground
                width: badge.implicitWidth + 12
                height: badge.implicitHeight + 6
                Text {
                    id: badge
                    anchors.centerIn: parent
                    // An announced stream cannot be played yet, so the badge
                    // says when it starts rather than a duration it does not
                    // have. isLive wins if somehow both are set, since a
                    // stream that has gone live is no longer upcoming.
                    text: card.isLive ? "LIVE"
                          : card.isUpcoming ? card.scheduledText
                          : card.durationText
                    color: Theme.colors.badgeText
                    font.pixelSize: 11
                    font.bold: true
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
        // the channel page rather than starting the video. The picture stands
        // as tall as both lines beside it, which is what gives a card a face
        // to recognise from across the grid.
        Row {
            id: channelRow
            width: parent.width
            spacing: 8

            RoundedImage {
                id: avatar
                width: 44
                height: 44
                circle: true
                visible: card.channelAvatar !== ""
                source: card.channelAvatar

                HoverHandler { id: avatarHover }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: card.channelRequested()
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: channelRow.width
                       - (card.channelAvatar !== "" ? avatar.width + channelRow.spacing : 0)
                spacing: 3

                Text {
                    width: parent.width
                    text: card.channelTitle
                    color: (channelHover.hovered || avatarHover.hovered)
                           ? Theme.colors.text : Theme.colors.textMuted
                    font.pixelSize: 12
                    font.underline: channelHover.hovered || avatarHover.hovered
                    elide: Text.ElideRight

                    HoverHandler { id: channelHover }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: card.channelRequested()
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
                        // The day it starts, or for anything else the day it
                        // was published. Never both, since a card has one line
                        // for it.
                        if (card.isUpcoming && card.startsText !== "")
                            parts.push(card.startsText)
                        else if (card.ageText !== "")
                            parts.push(card.ageText)
                        return parts.join("  ·  ")
                    }
                }
            }
        }
    }
}
