import QtQuick
import QtQuick.Controls

// One comment. Split out from the thread because a component may not
// instantiate itself in QML, and replies are never nested deeper than one
// level anyway, so a thread is a comment plus a flat list of them.
Row {
    id: body
    property var comment: ({})
    property bool compact: false

    spacing: 8

    readonly property int pictureSize: compact ? 20 : 26
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
                font.pixelSize: 11
                font.weight: Font.DemiBold
            }
            Label {
                visible: body.comment.pinned === true
                text: "pinned"
                color: Theme.colors.textMuted
                font.pixelSize: 10
            }
            Label {
                text: body.comment.when ? body.comment.when : ""
                color: Theme.colors.textMuted
                font.pixelSize: 10
            }
        }

        Label {
            width: parent.width
            text: body.comment.text ? body.comment.text : ""
            color: Theme.colors.text
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }

        Label {
            visible: (body.comment.likes || 0) > 0
            text: body.comment.likes + " likes"
            color: Theme.colors.textMuted
            font.pixelSize: 10
        }
    }
}
