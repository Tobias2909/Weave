import QtQuick

// A comment with its replies indented under it.
Column {
    id: thread
    property var comment: ({})
    // How much bigger than its usual size everything in here is drawn. Passed
    // in from the panel, which decides it from how wide it has been dragged.
    property real textScale: 1.0
    // Replies start where the words of the comment they answer start, past
    // its picture, with a thin line down from that picture beside them. At
    // the old eighteen pixels a reply's picture sat half under its parent's
    // and the two read as one list.
    readonly property int replyIndent: head.pictureSize + head.spacing

    spacing: 6

    CommentBody {
        id: head
        width: thread.width
        comment: thread.comment
        textScale: thread.textScale
    }

    Item {
        width: thread.width
        height: replies.height
        // Asked of the replies themselves, never of the column's height. A
        // wrapper that hides itself on its child's size hides the child too,
        // which leaves the column empty and both hidden for good.
        visible: (thread.comment.replies ? thread.comment.replies.length : 0) > 0

        Rectangle {
            objectName: "commentThreadLine"
            x: Math.round(head.pictureSize / 2) - 1
            width: 2
            height: parent.height
            radius: 1
            color: Theme.colors.border
        }

        Column {
            id: replies
            objectName: "commentReplies"
            x: thread.replyIndent
            width: thread.width - thread.replyIndent
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
}
