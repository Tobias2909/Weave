import QtQuick
import QtQuick.Controls

// One video. Every color comes from the Theme role map, never a literal, so
// the planned gradient themes need no changes in here.
Rectangle {
    id: card

    property string title: ""
    property string channelTitle: ""
    property string thumbnail: ""
    property string ageText: ""
    property string durationText: ""
    property string viewsText: ""
    property string likesText: ""
    property bool watched: false
    property bool isLive: false

    signal playRequested()
    signal detailsRequested()

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
        onTapped: card.detailsRequested()
    }

    Column {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        Item {
            width: parent.width
            height: width * 9 / 16

            Rectangle {
                anchors.fill: parent
                radius: 6
                color: Theme.colors.background
                clip: true

                Image {
                    anchors.fill: parent
                    source: card.thumbnail
                    asynchronous: true
                    cache: true
                    fillMode: Image.PreserveAspectCrop
                    // Thumbnails come straight from the image CDN rather than
                    // through the request throttle, which only guards the
                    // endpoints that can rate limit us.
                }
            }

            // A moving thumbnail replaces this still on hover in a later step.
            Rectangle {
                visible: card.durationText !== "" || card.isLive
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 6
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

        Text {
            width: parent.width
            text: card.channelTitle
            color: Theme.colors.textMuted
            font.pixelSize: 12
            elide: Text.ElideRight
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
