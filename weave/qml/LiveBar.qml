import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Who is live, across both platforms, busiest first. Sits above whatever view
// is showing, because it is the one thing that is only worth knowing now.
Rectangle {
    id: bar

    readonly property bool hasStreams: App.liveStreams.length > 0
    readonly property bool showing: hasStreams || App.twitchNeedsLogin
    readonly property bool expanded: !App.liveCollapsed

    visible: showing
    height: showing ? (expanded && hasStreams ? 150 : 34) : 0
    color: Theme.colors.surface

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.colors.border
    }

    RowLayout {
        id: heading
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 14
        anchors.rightMargin: 12
        height: 34
        spacing: 10

        Rectangle {
            width: 7
            height: 7
            radius: 3.5
            color: Theme.colors.live
            visible: bar.hasStreams
        }

        Label {
            text: bar.hasStreams
                  ? "Live now  ·  " + App.liveStreams.length
                  : "Twitch is not connected"
            color: Theme.colors.textMuted
            font.pixelSize: 11
            font.letterSpacing: 1.1
            font.weight: Font.DemiBold
        }

        Label {
            visible: App.twitchStatus !== ""
            text: App.twitchStatus
            color: Theme.colors.textMuted
            font.pixelSize: 11
            elide: Text.ElideRight
            Layout.maximumWidth: 320
        }

        Item { Layout.fillWidth: true }

        FlatButton {
            visible: App.twitchNeedsLogin
            text: "Connect Twitch"
            accent: true
            onClicked: App.connectTwitch()
        }

        FlatButton {
            visible: bar.hasStreams
            text: bar.expanded ? "Hide" : "Show"
            onClicked: App.setLiveCollapsed(bar.expanded)
        }
    }

    ListView {
        id: strip
        visible: bar.expanded && bar.hasStreams
        anchors.top: heading.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.bottomMargin: 8
        orientation: ListView.Horizontal
        spacing: 8
        clip: true
        model: App.liveStreams

        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

        // A wheel over the strip moves it sideways, since there is nowhere
        // vertical for it to go.
        WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function (event) {
                var notches = event.angleDelta.y / 120
                if (notches === 0)
                    return
                var limit = Math.max(0, strip.contentWidth - strip.width)
                strip.contentX = Math.max(0, Math.min(limit, strip.contentX - notches * 180))
            }
        }

        delegate: Rectangle {
            required property var modelData
            width: 260
            height: strip.height
            radius: 8
            color: cardHover.hovered ? Theme.colors.surfaceRaised : Theme.colors.background
            border.width: 1
            border.color: cardHover.hovered ? Theme.colors.accent : Theme.colors.border

            HoverHandler { id: cardHover }
            TapHandler { onTapped: App.playLive(modelData.channelKey) }

            Row {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8

                RoundedImage {
                    width: 96
                    height: 54
                    radius: 6
                    source: modelData.thumbnail
                }

                Column {
                    width: parent.width - 104
                    spacing: 2

                    Row {
                        spacing: 5
                        RoundedImage {
                            width: 16
                            height: 16
                            circle: true
                            visible: modelData.avatar !== ""
                            source: modelData.avatar
                        }
                        Label {
                            text: modelData.name
                            color: Theme.colors.text
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                            width: Math.max(0, parent.parent.width - (modelData.avatar !== "" ? 21 : 0))
                        }
                    }

                    Label {
                        width: parent.width
                        text: modelData.title
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        text: {
                            var parts = []
                            if (modelData.game !== "") parts.push(modelData.game)
                            if (modelData.viewersText !== "")
                                parts.push(modelData.viewersText + " watching")
                            if (modelData.platform === "youtube") parts.push("YouTube")
                            return parts.join("  ·  ")
                        }
                    }
                }
            }
        }
    }
}
