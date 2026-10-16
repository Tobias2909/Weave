import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Who is live, across both platforms, busiest first. Sits above whatever view
// is showing, because it is the one thing that is only worth knowing now.
Rectangle {
    id: bar
    objectName: "liveBar"

    readonly property int count: App.liveModel.count
    readonly property bool hasStreams: count > 0

    // Nothing is shown until the first check has answered. Twitch takes a
    // few seconds and YouTube is instant, so revealing on the first thing to
    // arrive made the bar appear, then grow again a moment later. One reveal,
    // once everything is in, and only when there is something to reveal.
    readonly property bool showing: App.twitchNeedsLogin
                                    || (App.liveReady && hasStreams)
    readonly property bool expanded: !App.liveCollapsed
    // Every card at once, in rows down the bar, rather than one row of them
    // to scroll along. For finding one stream among many.
    readonly property bool allShown: App.liveAll

    // A card, its picture and the room between cards. One row draws every
    // card this wide; all of them draws as many of these as fit across and
    // then widens them, so each row fills the bar the way the video grid's
    // rows do.
    readonly property int gap: 8
    readonly property int inset: 7
    readonly property int cardHeight: 74
    readonly property int pictureHeight: cardHeight - inset * 2
    readonly property int pictureWidth: Math.round(pictureHeight * 16 / 9)
    readonly property int cardWidth: pictureWidth + inset * 3 + 168
    readonly property int perRow: Math.max(1, Math.floor((strip.width + gap) / (cardWidth + gap)))
    readonly property real cell: (strip.width + gap) / perRow
    readonly property int rows: Math.max(1, Math.ceil(count / perRow))
    // Tall enough for every row, and never more than most of the window, so
    // the page under it is still there. Past that it scrolls inside.
    readonly property int allHeight: 34 + rows * (cardHeight + gap)
    readonly property int ceiling: Math.max(116, Math.round((parent ? parent.height : 900) * 0.7))

    // Where the cards are, from one row (0) to all of them (1). Every card
    // places itself between its two places by this one number, which moves
    // in step with the bar's height, so the cards spread down into their rows
    // as the bar unrolls and gather back into one as it rolls up.
    property real spread: allShown ? 1 : 0
    Behavior on spread {
        NumberAnimation { duration: 260; easing.type: Easing.InOutCubic }
    }

    // Folded away rather than switched off, so the first stream of the
    // evening unrolls the bar and the last one to end rolls it back up.
    // Height is what the views below anchor to, so animating it moves them
    // with it instead of leaving a gap.
    visible: height > 0
    clip: true
    height: showing ? (expanded && hasStreams
                       ? (allShown ? Math.min(allHeight, ceiling) : 116) : 34) : 0

    Behavior on height {
        NumberAnimation { duration: 260; easing.type: Easing.InOutCubic }
    }

    opacity: showing ? 1.0 : 0.0
    Behavior on opacity {
        NumberAnimation { duration: 200; easing.type: Easing.InOutQuad }
    }
    // Read as a colour first. The roles are handed over as text, and asking
    // a piece of text for its red gives nothing, which builds a black bar.
    readonly property color panel: Qt.color(Theme.colors.surface)
    color: Qt.rgba(panel.r, panel.g, panel.b,
                   // A pale bar keeps more of itself, or the gradient behind
                   // it shows through and the dark text on it stops being
                   // readable.
                   Theme.washed ? (Theme.light ? 0.9 : 0.62) : 1.0)

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
            // The bar is only up when there is something live or when Twitch
            // wants a login, so there is no third thing left to say.
            text: bar.hasStreams
                  ? "Live now  ·  " + bar.count
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
            objectName: "liveAllButton"
            visible: bar.hasStreams && bar.expanded
            text: bar.allShown ? "One row" : "Show all"
            onClicked: App.setLiveAll(!bar.allShown)
        }

        FlatButton {
            visible: bar.hasStreams
            text: bar.expanded ? "Hide" : "Show"
            onClicked: App.setLiveCollapsed(bar.expanded)
        }
    }

    // A wheel over the strip moves it along the row, since there is nowhere
    // vertical for one row to go, and down the rows when there are several
    // and they are more than the bar has room for.
    SmoothScroll {
        id: stripWheel
        flickable: strip
        horizontal: !bar.allShown
        step: bar.allShown ? bar.cardHeight + bar.gap : 200
    }

    // Changing between one row and all of them starts again from the start,
    // and gets there in step with the cards. A card's place on screen is its
    // place in the strip less how far the strip is scrolled, so moving both
    // the same way at the same pace takes every card in a straight line from
    // where it is seen to where it is going, scrolled along the row or not.
    onAllShownChanged: {
        stripWheel.stop()
        settleX.from = strip.contentX
        settleY.from = strip.contentY
        settle.restart()
    }
    ParallelAnimation {
        id: settle
        NumberAnimation {
            id: settleX
            target: strip
            property: "contentX"
            to: 0
            duration: 260
            easing.type: Easing.InOutCubic
        }
        NumberAnimation {
            id: settleY
            target: strip
            property: "contentY"
            to: 0
            duration: 260
            easing.type: Easing.InOutCubic
        }
    }

    // Placed by hand rather than by a view, because a view lays a card out in
    // one arrangement or the other and cannot carry it between them. There
    // are only ever a few dozen streams, so having all of them built at once
    // costs nothing a view would have saved.
    Flickable {
        id: strip
        objectName: "liveStrip"
        visible: bar.expanded && bar.hasStreams
        anchors.top: heading.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        clip: true
        flickableDirection: bar.allShown ? Flickable.VerticalFlick : Flickable.HorizontalFlick
        contentWidth: (1 - bar.spread) * Math.max(0, bar.count * (bar.cardWidth + bar.gap) - bar.gap)
                      + bar.spread * width
        contentHeight: (1 - bar.spread) * bar.cardHeight
                       + bar.spread * (bar.rows * (bar.cardHeight + bar.gap) - bar.gap)

        // No visible bar. The wheel scrolls it and a bar across a band this
        // short is more clutter than help.
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOff }

        Repeater {
            model: App.liveModel

            delegate: Rectangle {
                id: streamCard
                required property int index
                required property string channelKey
                required property string platform
                required property string name
                required property string title
                required property string game
                required property string viewersText
                required property string thumbnail
                required property string avatar

                // Its place in one row, and its place among all of them. The
                // thumbnail fills the card's height and the text beside it is
                // vertically centred, so the card has no empty band along the
                // bottom. Whole pixels, or the words on a card that has come
                // to rest are drawn soft.
                readonly property int column: index % bar.perRow
                readonly property int line: Math.floor(index / bar.perRow)
                x: Math.round((1 - bar.spread) * index * (bar.cardWidth + bar.gap)
                              + bar.spread * column * bar.cell)
                y: Math.round(bar.spread * line * (bar.cardHeight + bar.gap))
                width: Math.round((1 - bar.spread) * bar.cardWidth
                                  + bar.spread * (bar.cell - bar.gap))
                height: bar.cardHeight

                // Which platform, said with colour rather than with a badge.
                // Kept to an edge and a tinted border so a card is never
                // washed in it.
                readonly property color mark: platform === "twitch"
                                              ? Theme.colors.twitch : Theme.colors.youtube

                radius: 8
                color: cardHover.hovered ? Theme.colors.surfaceRaised : Theme.colors.background
                border.width: 1
                border.color: cardHover.hovered
                              ? mark
                              : Qt.rgba(mark.r, mark.g, mark.b, 0.35)

                HoverHandler { id: cardHover }
                TapHandler { onTapped: App.playLive(streamCard.channelKey) }

                Item {
                    id: picture
                    x: bar.inset
                    y: bar.inset
                    width: bar.pictureWidth
                    height: bar.pictureHeight

                    // The streamer, on the corner of their own picture.
                    //
                    // It used to sit in the row with the name, where it was at
                    // the mercy of the title. That column is centred and grows
                    // with what is in it, so a title needing two lines took it
                    // to sixty nine of the card's seventy four and pushed the
                    // face to two pixels from the top, inside a corner eight
                    // pixels round and over the coloured edge. A longer one
                    // pushed it outside altogether.
                    //
                    // Here nothing can move it, it costs the words no width,
                    // and it is half again the size it was. The ring is the
                    // card's own colour, so it reads against whatever the
                    // picture happens to be, which is the same thing every
                    // other client does with it.
                    Rectangle {
                        objectName: "streamAvatarRing"
                        visible: streamCard.avatar !== ""
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.margins: 4
                        width: 30
                        height: 30
                        radius: 15
                        color: streamCard.color
                        z: 2

                        RoundedImage {
                            objectName: "streamAvatar"
                            anchors.fill: parent
                            anchors.margins: 2
                            circle: true
                            source: streamCard.avatar
                        }
                    }

                    // The picture on the card, and the next one coming in over
                    // it. A Twitch frame is made again every five minutes and
                    // arrives under a new address, and a picture whose address
                    // simply changed would be empty for as long as the new one
                    // took to come. So the new one loads unseen, fades in over
                    // the old, and only then becomes the one underneath. One
                    // that cannot be had leaves the old one up.
                    property string settled: ""

                    function arrived() {
                        if (nextFrame.status !== Image.Ready
                                || picture.settled === streamCard.thumbnail)
                            return
                        if (picture.settled === "") {
                            picture.settled = streamCard.thumbnail
                            return
                        }
                        fadeIn.restart()
                    }

                    RoundedImage {
                        objectName: "streamFrame"
                        anchors.fill: parent
                        radius: 6
                        source: picture.settled
                    }

                    RoundedImage {
                        id: nextFrame
                        objectName: "streamNextFrame"
                        anchors.fill: parent
                        radius: 6
                        source: streamCard.thumbnail
                        opacity: 0
                        visible: opacity > 0
                        // The address is changed before the picture is looked
                        // for, so a picture already at hand is only Ready a
                        // moment later, and says nothing as it becomes so.
                        onSourceChanged: Qt.callLater(picture.arrived)
                        onStatusChanged: picture.arrived()
                    }

                    NumberAnimation {
                        id: fadeIn
                        target: nextFrame
                        property: "opacity"
                        from: 0
                        to: 1
                        duration: 450
                        easing.type: Easing.InOutQuad
                        // The picture underneath takes the new one, which is
                        // already loaded, so it is drawn at once, and the one
                        // on top can go without a gap between them.
                        onFinished: {
                            picture.settled = streamCard.thumbnail
                            nextFrame.opacity = 0
                        }
                    }

                    // Handed to mpv and not yet on screen. A tile carries a
                    // channel rather than a video, which is what the window
                    // matches against here.
                    Rectangle {
                        id: startingWash
                        visible: App.startingKey === streamCard.channelKey
                        anchors.fill: parent
                        radius: 6
                        color: Qt.rgba(0, 0, 0, 0.55)

                        Rectangle {
                            anchors.centerIn: parent
                            width: 12
                            height: 12
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
                    }
                }

                // A thin edge in the platform's colour. Enough to tell them
                // apart at a glance without taking any room.
                // It asked for the card's corners and could not have them: Qt
                // clamps a corner to half the width, so three pixels can only
                // ever curve by one and a half and the ends stayed square
                // against a corner eight pixels round.
                //
                // So the shape is the card's own, drawn full size with the
                // card's radius, and only the first three pixels of it are let
                // through. Clipping is rectangular, which is exactly what is
                // wanted here, and the corners come out following the card
                // because they are the card's corners.
                Item {
                    objectName: "platformMark"
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 3
                    clip: true

                    Rectangle {
                        width: streamCard.width
                        height: streamCard.height
                        radius: streamCard.radius
                        color: streamCard.mark
                    }
                }

                Column {
                    anchors.left: picture.right
                    anchors.leftMargin: bar.inset
                    anchors.right: parent.right
                    anchors.rightMargin: bar.inset
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3

                    Row {
                        width: parent.width
                        spacing: 6

                        Label {
                            width: parent.width
                            anchors.verticalCenter: parent.verticalCenter
                            text: streamCard.name
                            color: Theme.colors.text
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                    }

                    Label {
                        width: parent.width
                        text: streamCard.title
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
                            if (streamCard.game !== "") parts.push(streamCard.game)
                            if (streamCard.viewersText !== "")
                                parts.push(streamCard.viewersText + " watching")
                            return parts.join("  ·  ")
                        }
                    }
                }
            }
        }
    }
}
