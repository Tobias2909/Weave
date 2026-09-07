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
    // On its way to mpv. Said here rather than in a corner of the window,
    // since this is where the press happened and where the eye already is.
    property bool starting: false

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
    // Only what has been watched. An announcement was dimmed too, on the
    // reasoning that it cannot be played yet, but a stream somebody is waiting
    // for is the opposite of something already dealt with and it read as a
    // fault in the picture rather than as a state.
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

            // Handed to mpv and not yet on screen. Over the picture and
            // inside the same frame, so it covers the duration and the
            // progress bar rather than fighting them for the corner.
            Rectangle {
                id: startingWash
                objectName: "startingWash"
                visible: card.starting
                anchors.fill: thumbnailFrame
                radius: thumbnailFrame.radius
                color: Qt.rgba(0, 0, 0, 0.55)
                z: 3

                Rectangle {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 12, startingRow.implicitWidth + 20)
                    height: 26
                    radius: 13
                    color: Theme.colors.surfaceRaised
                    border.width: 1
                    border.color: Theme.colors.border

                    Row {
                        id: startingRow
                        anchors.centerIn: parent
                        spacing: 6

                        // The same turning mark the window used to show at the
                        // bottom, so the two read as one thing moved.
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 9
                            height: 9
                            radius: 2
                            color: Theme.colors.accent
                            RotationAnimator on rotation {
                                running: startingWash.visible
                                loops: Animation.Infinite
                                from: 0
                                to: 360
                                duration: 1400
                            }
                        }

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Starting in mpv"
                            color: Theme.colors.text
                            font.pixelSize: 11
                        }
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

        // Always as tall as two lines, whether the title needs them or not.
        // Sized from a hidden two line copy rather than from a number, since
        // the line height belongs to the font the platform actually loaded.
        // Without this a one line title pulled the channel row up and nothing
        // below the picture lined up from card to card.
        Item {
            width: parent.width
            height: titleSizer.height

            Text {
                id: titleSizer
                visible: false
                text: "Ag\nAg"
                font: titleText.font
            }

            Text {
                id: titleText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                text: card.title
                color: card.watched ? Theme.colors.watchedDim : Theme.colors.text
                font.pixelSize: 13
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        // The channel line is its own click target, so a left click here opens
        // the channel page rather than starting the video. The picture stands
        // as tall as both lines beside it, which is what gives a card a face
        // to recognise from across the grid.
        Row {
            id: channelRow
            width: parent.width
            // As tall as the picture whether there is one or not. A listing
            // from a channel nothing is stored about has no picture to draw,
            // and letting the row shrink to its text put those cards half a
            // line out of step with the rest of the grid.
            height: 44
            spacing: 8

            // A picture only exists for a channel whose own page has been
            // read, which a search result's channel usually has not: it would
            // be one page fetch per channel on the page, against a ceiling the
            // sweep already spends most of. So a card with no picture draws
            // this instead, which costs nothing and, more to the point, is
            // something to press. Without it the only way through to the
            // channel was a thin line of text.
            Item {
                id: avatar
                anchors.verticalCenter: parent.verticalCenter
                width: 44
                height: 44

                RoundedImage {
                    anchors.fill: parent
                    circle: true
                    visible: card.channelAvatar !== ""
                    source: card.channelAvatar
                }

                Rectangle {
                    objectName: "channelInitial"
                    anchors.fill: parent
                    visible: card.channelAvatar === ""
                    radius: width / 2
                    color: Theme.colors.surfaceRaised
                    border.width: 1
                    border.color: Theme.colors.border

                    Label {
                        anchors.centerIn: parent
                        text: card.channelTitle === "" ? "" : card.channelTitle.charAt(0).toUpperCase()
                        color: Theme.colors.textMuted
                        font.pixelSize: 18
                    }
                }

                HoverHandler { id: avatarHover }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: card.channelRequested()
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: channelRow.width - avatar.width - channelRow.spacing
                spacing: 3

                // The name is a link, and the line under it is not, so the
                // handlers live on a wrapper around the name alone rather
                // than on the column that holds both. On the Text itself they
                // were never offered the press at all.
                Item {
                    objectName: "channelLink"
                    width: parent.width
                    height: channelName.implicitHeight + 8

                    Text {
                        id: channelName
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: card.channelTitle
                        color: (channelHover.hovered || avatarHover.hovered)
                               ? Theme.colors.text : Theme.colors.textMuted
                        font.pixelSize: 12
                        font.underline: channelHover.hovered || avatarHover.hovered
                        elide: Text.ElideRight
                    }

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
