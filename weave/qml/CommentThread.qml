import QtQuick

// A comment with its replies indented under it.
Column {
    id: thread
    property var comment: ({})
    // How much bigger than its usual size everything in here is drawn. Passed
    // in from the panel, which decides it from how wide it has been dragged.
    property real textScale: 1.0

    spacing: 6

    CommentBody {
        width: thread.width
        comment: thread.comment
        textScale: thread.textScale
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
                // A delegate cannot see an id declared around it, but the
                // view it sits in is its parent here, and the thread is what
                // that parent belongs to.
                textScale: thread.textScale
            }
        }
    }
}
