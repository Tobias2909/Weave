import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Who is live, across both platforms, busiest first. Sits above whatever view
// is showing, because it is the one thing that is only worth knowing now.
Rectangle {
    id: bar
    objectName: "liveBar"

    readonly property bool hasStreams: App.liveStreams.length > 0

    // Only while the bar would otherwise be blank. On the repeat checks there
    // are already cards up, and swapping them for a line about checking would
    // make the bar flicker every ninety seconds for no gain.
    readonly property bool checking: App.liveChecking && !hasStreams
                                     && !App.twitchNeedsLogin
    readonly property bool showing: hasStreams || App.twitchNeedsLogin || checking
    readonly property bool expanded: !App.liveCollapsed

    visible: showing
    height: showing ? (expanded && hasStreams ? 116 : 34) : 0
    color: Qt.rgba(Theme.colors.surface.r, Theme.colors.surface.g,
                   Theme.colors.surface.b, Theme.washed ? 0.62 : 1.0)

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
            objectName: "liveHeading"
            text: bar.hasStreams
                  ? "Live now  ·  " + App.liveStreams.length
                  : (bar.checking ? "Checking who is live"
                                  : "Twitch is not connected")
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

    // A wheel over the strip moves it sideways, since there is nowhere
    // vertical for it to go.
    SmoothScroll {
        flickable: strip
        horizontal: true
        step: 200
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

        // No visible bar. The wheel scrolls it and a bar across a band this
        // short is more clutter than help.
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOff }

        delegate: Rectangle {
            id: streamCard
            required property var modelData

            // Sized to what it holds. The thumbnail fills the card's height and
            // the text beside it is vertically centred, so the card has no
            // empty band along the bottom.
            readonly property int inset: 7
            readonly property int pictureHeight: strip.height - inset * 2
            readonly property int pictureWidth: Math.round(pictureHeight * 16 / 9)

            // Which platform, said with colour rather than with a badge. Kept
            // to an edge and a tinted border so a card is never washed in it.
            readonly property color mark: modelData.platform === "twitch"
                                          ? Theme.colors.twitch : Theme.colors.youtube

            width: pictureWidth + inset * 3 + 168
            height: strip.height
            radius: 8
            color: cardHover.hovered ? Theme.colors.surfaceRaised : Theme.colors.background
            border.width: 1
            border.color: cardHover.hovered
                          ? mark
                          : Qt.rgba(mark.r, mark.g, mark.b, 0.35)

            HoverHandler { id: cardHover }
            TapHandler { onTapped: App.playLive(streamCard.channelKeyOf) }
            readonly property string channelKeyOf: modelData.channelKey

            Item {
                id: picture
                x: streamCard.inset
                y: streamCard.inset
                width: streamCard.pictureWidth
                height: streamCard.pictureHeight

                RoundedImage {
                    anchors.fill: parent
                    radius: 6
                    source: modelData.thumbnail
                }

            }

            // A thin edge in the platform's colour. Enough to tell them apart
            // at a glance without taking any room.
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 3
                topLeftRadius: streamCard.radius
                bottomLeftRadius: streamCard.radius
                color: streamCard.mark
            }

            Column {
                anchors.left: picture.right
                anchors.leftMargin: streamCard.inset
                anchors.right: parent.right
                anchors.rightMargin: streamCard.inset
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3

                Row {
                    width: parent.width
                    spacing: 6

                    RoundedImage {
                        width: 20
                        height: 20
                        circle: true
                        visible: modelData.avatar !== ""
                        source: modelData.avatar
                    }

                    Label {
                        width: parent.width - (modelData.avatar !== "" ? 26 : 0)
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.name
                        color: Theme.colors.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                }

                Label {
                    width: parent.width
                    text: modelData.title
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
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
                        return parts.join("  ·  ")
                    }
                }
            }
        }
    }
}
