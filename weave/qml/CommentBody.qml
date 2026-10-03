import QtQuick
import QtQuick.Controls

// One comment. Split out from the thread because a component may not
// instantiate itself in QML, and replies are never nested deeper than one
// level anyway, so a thread is a comment plus a flat list of them.
Row {
    id: body
    property var comment: ({})
    property bool compact: false
    // How much bigger than its usual size this is drawn. The panel decides it
    // from how wide it has been dragged and hands it down, since a component
    // in its own file cannot see anything declared in the one that uses it.
    property real textScale: 1.0
    // Shown beside a song on the Now playing page rather than in the panel, so
    // a time pressed in it goes to that point in the song and not in mpv.
    property bool song: false

    spacing: 8

    function sized(pixels) { return Math.round(pixels * body.textScale) }

    readonly property int pictureSize: sized(compact ? 20 : 26)
    readonly property bool hasPicture: comment.avatar !== undefined && comment.avatar !== ""

    RoundedImage {
        width: body.pictureSize
        height: body.pictureSize
        circle: true
        visible: body.hasPicture
        source: body.hasPicture ? body.comment.avatar : ""
    }

    Column {
        width: body.width - (body.hasPicture ? body.pictureSize + body.spacing : 0)
        spacing: 2

        Row {
            spacing: 6
            Label {
                text: body.comment.author ? body.comment.author : ""
                color: body.comment.byUploader ? Theme.colors.accent : Theme.colors.text
                font.pixelSize: body.sized(11)
                font.weight: Font.DemiBold
            }
            Label {
                visible: body.comment.pinned === true
                text: "pinned"
                color: Theme.colors.textMuted
                font.pixelSize: body.sized(10)
            }
            Label {
                text: body.comment.when ? body.comment.when : ""
                color: Theme.colors.textMuted
                font.pixelSize: body.sized(10)
            }
        }

        // Markup, so an address, a channel's handle and a time can be pressed
        // the way they can in a description. A press anywhere else in the
        // words is not taken, so a list of comments still scrolls under it.
        Label {
            id: commentWords
            objectName: "commentText"
            width: parent.width
            text: body.comment.markup ? body.comment.markup : ""
            textFormat: Text.StyledText
            linkColor: Theme.colors.accent
            color: Theme.colors.text
            font.pixelSize: body.sized(12)
            wrapMode: Text.Wrap
            onLinkActivated: function (link) {
                if (link.indexOf("weave-seek:") !== 0)
                    App.openLink(link)
                else if (body.song)
                    Audio.seekTo(parseInt(link.slice(11)))
                else
                    App.seekVideo(parseInt(link.slice(11)))
            }

            HoverHandler {
                cursorShape: commentWords.linkAt(point.position.x, point.position.y) !== ""
                             ? Qt.PointingHandCursor : Qt.ArrowCursor
            }
        }

        Label {
            visible: (body.comment.likes || 0) > 0
            text: body.comment.likes + " likes"
            color: Theme.colors.textMuted
            font.pixelSize: body.sized(10)
        }
    }
}
