import QtQuick
import QtQuick.Controls

// A video as a wide picture with its name across the bottom: smaller than a
// card and larger than a song's square, for a page that is mostly pictures to
// pick from rather than rows to read.
Item {
    id: tile

    property string title: ""
    property string channel: ""
    property string picture: ""
    property string duration: ""
    // Already in mpv's playlist, which a press would add to again.
    property bool queued: false
    // Whether the channel's name goes somewhere when pressed. Only where its
    // channel is known, since a name with nowhere behind it is just words.
    property bool channelLeads: false

    signal chosen()
    signal askedFor()
    signal channelChosen()

    HoverHandler { id: tileHover; cursorShape: Qt.PointingHandCursor }

    // The press on the picture. First, so the channel's name above it takes
    // a press of its own.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (mouse) {
            if (mouse.button === Qt.RightButton)
                tile.askedFor()
            else
                tile.chosen()
        }
    }

    RoundedImage {
        anchors.fill: parent
        radius: 8
        source: tile.picture
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: "transparent"
        border.width: tileHover.hovered ? 2 : 1
        border.color: tileHover.hovered ? Theme.colors.accent : Theme.colors.border
    }

    Rectangle {
        visible: tile.duration !== ""
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 6
        width: durationWords.implicitWidth + 10
        height: 18
        radius: 4
        color: "#c0000000"

        Label {
            id: durationWords
            anchors.centerIn: parent
            text: tile.duration
            color: "#ffffff"
            font.pixelSize: 11
        }
    }

    Rectangle {
        objectName: "videoTileQueued"
        visible: tile.queued
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 6
        width: queuedWords.implicitWidth + 12
        height: 18
        radius: 4
        color: Theme.colors.accent

        Label {
            id: queuedWords
            anchors.centerIn: parent
            text: "In queue"
            color: "#ffffff"
            font.pixelSize: 10
            font.weight: Font.DemiBold
        }
    }

    // A wash under the words, so a bright picture cannot swallow them.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: tile.channel === "" ? 36 : 52
        bottomLeftRadius: 8
        bottomRightRadius: 8
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#00000000" }
            GradientStop { position: 0.45; color: "#b0000000" }
            GradientStop { position: 1.0; color: "#e6000000" }
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 8
            spacing: 1

            Label {
                width: parent.width
                text: tile.title
                color: "#ffffff"
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 1
            }

            Label {
                id: channelLabel
                objectName: "videoTileChannel"
                width: parent.width
                visible: tile.channel !== ""
                text: tile.channel
                color: tile.channelLeads && channelHover.hovered ? "#ffffff" : "#d0ffffff"
                font.pixelSize: 11
                font.underline: tile.channelLeads && channelHover.hovered
                elide: Text.ElideRight
                maximumLineCount: 1

                // Only as wide as the words, so the rest of the line still
                // plays the video.
                MouseArea {
                    enabled: tile.channelLeads
                    width: Math.min(channelLabel.implicitWidth, channelLabel.width)
                    height: parent.height
                    cursorShape: Qt.PointingHandCursor
                    onClicked: tile.channelChosen()

                    HoverHandler { id: channelHover }
                }
            }
        }
    }
}
