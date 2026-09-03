import QtQuick

// A comment with its replies indented under it.
Column {
    id: thread
    property var comment: ({})

    spacing: 6

    CommentBody {
        width: thread.width
        comment: thread.comment
    }

    Column {
        x: 18
        width: thread.width - 18
        spacing: 6

        Repeater {
            model: thread.comment.replies ? thread.comment.replies : []
            CommentBody {
                required property var modelData
                width: parent.width
                comment: modelData
                compact: true
            }
        }
    }
}
