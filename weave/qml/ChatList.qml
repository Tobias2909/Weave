import QtQuick
import QtQuick.Controls

// The chat beside a broadcast, newest at the bottom.
//
// One list, drawn in whichever place the chat is shown: the column beside the
// picture, the column beside a smaller picture filling the screen, or the
// panel over it. It is moved between them rather than made again, so where it
// was scrolled to and what it holds survive the move.
//
// A line is a row of pieces that wrap as words do: the person's roles as small
// words, their name in their colour, then every word, and every emote a
// picture the height of the row, moving where the emote does.
Item {
    id: chatList
    objectName: "chatList"

    // Bigger when the picture fills the screen.
    property bool big: false
    // On black whatever the theme: over the picture, or beside a picture
    // that fills the screen, where a lit column would pull the eye from it.
    property bool dark: false
    // Whether moving emotes move. Not while nobody can see them.
    property bool animate: true

    // Let go from outside, by a new chat or a replay that followed a seek:
    // it starts at its newest line again, following.
    readonly property bool held: Chat.held
    onHeldChanged: {
        if (!held && !lines.pinned) {
            lines.pinned = true
            Qt.callLater(lines.follow)
        }
    }

    readonly property int unit: big ? 30 : 26
    readonly property int fontSize: big ? 15 : 13
    readonly property color ink: dark ? "#f2f2f2" : Theme.colors.text
    readonly property color quiet: dark ? Qt.rgba(1, 1, 1, 0.62) : Theme.colors.textMuted

    // A name's colour, made darker on a light ground, where the colours
    // chosen to read on a dark one do not. On a dark ground a name somebody
    // picked dark is lifted until it reads, the way Twitch's own dark mode
    // does: dark blue on black is hard to make out, and black is not there.
    function nameColour(colour) {
        if (!colour)
            return chatList.ink
        if (Theme.light && !chatList.dark)
            return Qt.darker(colour, 1.7)
        var shade = Qt.lighter(colour, 1.0)
        var light = shade.hslLightness
        var hue = Math.max(0, shade.hslHue)
        for (var step = 0; step < 12 && chatList.luminance(shade) < 0.2; step++) {
            light = Math.min(1, light + 0.06)
            shade = Qt.hsla(hue, shade.hslSaturation, light, 1)
        }
        return shade
    }
    // How bright a colour looks, from none for black to one for white.
    function luminance(shade) {
        function part(value) {
            return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * part(shade.r) + 0.7152 * part(shade.g) + 0.0722 * part(shade.b)
    }

    ListView {
        id: lines
        objectName: "chatView"
        anchors.fill: parent
        clip: true
        spacing: 3
        model: Chat.model
        currentIndex: -1
        keyNavigationEnabled: false
        boundsBehavior: Flickable.StopAtBounds
        cacheBuffer: 400

        // A short chat sits at the bottom, by the newest, as a chat does.
        // Worked out a moment later rather than bound: a new margin moves the
        // view at once, which builds and drops lines, which changes the very
        // height the margin came from. Bound, that was a loop Qt cut short,
        // and the margin it left was the one from before, a gap at the top
        // of a chat shown in a smaller place and back.
        function placeShort() {
            topMargin = Math.max(0, height - contentHeight - 4)
            follow()
        }
        onContentHeightChanged: Qt.callLater(placeShort)
        Component.onCompleted: Qt.callLater(placeShort)

        // Following the newest line, until somebody scrolls up to read.
        property bool pinned: true
        property bool placing: false
        function follow() {
            if (!pinned)
                return
            placing = true
            chatScroll.stop()
            positionViewAtEnd()
            placing = false
        }
        function judge() {
            if (placing)
                return
            pinned = atYEnd
            Chat.setHeld(!pinned)
        }
        onHeightChanged: Qt.callLater(placeShort)
        // Followed on every line that comes rather than on the count, which
        // stops changing once the chat is full: from then on each line in is
        // one taken off the top, and a view that waited for the count to move
        // stayed where it was for good.
        Connections {
            target: Chat.model
            function onRowsInserted() { Qt.callLater(lines.follow) }
        }
        onMovementEnded: judge()

        ScrollBar.vertical: ScrollBar {
            id: chatBar
            policy: ScrollBar.AsNeeded
            onPressedChanged: {
                if (pressed)
                    lines.pinned = false
                else
                    lines.judge()
            }
        }

        delegate: Item {
            id: line
            objectName: "chatLine"
            required property string key
            required property string author
            required property string colour
            required property var roles
            required property var pieces
            required property string kind
            required property string amount
            required property string header
            required property string sticker
            required property bool action
            width: ListView.view.width - 10
            height: box.height

            readonly property bool boxed: kind === "cheer" || kind === "paid"

            Rectangle {
                id: box
                width: parent.width
                height: body.height + (line.boxed ? 12 : 0)
                radius: 6
                color: line.boxed ? Theme.wash(Theme.colors.accent, 0.16) : "transparent"
                border.width: line.boxed ? 1 : 0
                border.color: Theme.colors.accent

                Column {
                    id: body
                    x: line.boxed ? 8 : 0
                    y: line.boxed ? 6 : 0
                    width: parent.width - 2 * x
                    spacing: 0

                    // A subscription, a gift, a raid: one quiet line.
                    Label {
                        objectName: "chatNotice"
                        visible: line.kind === "notice" && line.header !== ""
                        width: parent.width
                        text: "★  " + line.header
                        color: chatList.quiet
                        font.pixelSize: chatList.fontSize - 1
                        font.italic: true
                        wrapMode: Text.Wrap
                        topPadding: 3
                        bottomPadding: 3
                    }

                    // Words at their own height, an emote at the row's, so a
                    // line of words wraps close and a row with an emote in it
                    // makes room for the picture.
                    Flow {
                        id: said
                        width: parent.width
                        spacing: 4
                        visible: line.author !== "" || line.pieces.length > 0

                        Label {
                            visible: line.roles.length > 0
                            height: nameWords.height
                            verticalAlignment: Text.AlignVCenter
                            text: line.roles.join(" ").toUpperCase()
                            color: chatList.quiet
                            font.pixelSize: chatList.fontSize - 3
                            font.letterSpacing: 0.4
                        }
                        Label {
                            id: nameWords
                            objectName: "chatAuthor"
                            visible: line.author !== ""
                            text: line.author
                            color: chatList.nameColour(line.colour)
                            font.pixelSize: chatList.fontSize
                            font.weight: Font.DemiBold
                        }
                        Label {
                            visible: line.amount !== ""
                            text: line.amount
                            color: chatList.ink
                            font.pixelSize: chatList.fontSize
                            font.weight: Font.Bold
                        }
                        // A Super Chat's words go under its name and amount.
                        Item {
                            visible: line.boxed && line.pieces.length > 0
                            width: said.width
                            height: 1
                        }
                        Image {
                            visible: line.sticker !== ""
                            height: chatList.unit * 2
                            width: height
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            source: line.sticker
                        }

                        Repeater {
                            model: line.pieces
                            delegate: Loader {
                                required property var modelData
                                readonly property var piece: modelData
                                sourceComponent: !piece.picture ? wordPiece
                                                 : (piece.moves || piece.picture.indexOf("file:") !== 0
                                                    ? movingPiece : stillPiece)
                            }
                        }
                    }
                }
            }

            Component {
                id: wordPiece
                Label {
                    text: parent ? parent.piece.text : ""
                    textFormat: Text.PlainText
                    color: line.action ? chatList.nameColour(line.colour) : chatList.ink
                    font.pixelSize: chatList.fontSize
                    font.italic: line.action
                }
            }
            Component {
                id: stillPiece
                Image {
                    objectName: "chatEmote"
                    readonly property var piece: parent ? parent.piece : ({})
                    height: chatList.unit
                    width: Math.round(height * (piece.ratio || 1))
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    smooth: true
                    mipmap: true
                    source: piece.picture || ""
                }
            }
            Component {
                id: movingPiece
                AnimatedImage {
                    objectName: "chatEmote"
                    readonly property var piece: parent ? parent.piece : ({})
                    height: chatList.unit
                    width: Math.round(height * (implicitHeight > 0 ? implicitWidth / implicitHeight
                                                                   : (piece.ratio || 1)))
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    smooth: true
                    playing: chatList.animate
                    source: piece.picture || ""
                }
            }
        }
    }

    // The wheel glides, three rows a notch, so the eye keeps its place. Up
    // and away from the newest line lets go of it at once, or a line coming
    // in while the view glides would pull it back down. Down to it takes
    // hold again at once, and a line that comes before the glide is there
    // takes the view the rest of the way.
    SmoothScroll {
        id: chatScroll
        flickable: lines
        step: 3 * chatList.unit
        onGlideStarted: function (toEnd) {
            lines.pinned = toEnd
            Chat.setHeld(!toEnd)
        }
        onGlidingChanged: {
            if (!gliding)
                lines.judge()
        }
    }

    // Scrolled up while lines kept coming: how many, and the way back.
    Rectangle {
        objectName: "chatUnseen"
        visible: Chat.held && Chat.unseen > 0
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 10
        width: unseenWords.implicitWidth + 24
        height: 28
        radius: 14
        color: Theme.colors.accent

        Label {
            id: unseenWords
            anchors.centerIn: parent
            text: Chat.unseen + " new  ↓"
            color: Theme.colors.badgeText
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                lines.pinned = true
                lines.follow()
                Chat.setHeld(false)
            }
        }
    }

    // What the chat is doing when it is not simply showing lines.
    Label {
        objectName: "chatStatus"
        visible: Chat.status !== ""
        // Placed by hand: two vertical anchors swapped by a condition make Qt
        // write the height, and a height written once stays.
        x: (parent.width - width) / 2
        y: lines.count === 0 ? (parent.height - height) / 2 : 6
        width: Math.min(parent.width - 20, implicitWidth)
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        text: Chat.status
        color: chatList.quiet
        font.pixelSize: 12
        padding: 6
        background: Rectangle {
            radius: 6
            color: chatList.dark ? Qt.rgba(0, 0, 0, 0.5) : Theme.colors.surfaceRaised
            visible: lines.count > 0
        }
    }
}
