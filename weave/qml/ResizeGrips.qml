import QtQuick

// The border a frameless window no longer gets from the compositor.
//
// Invisible strips along the four edges and squares in the four corners, each
// asking the compositor to start a resize on the edges it covers. The
// compositor does the resizing, which is what keeps snapping and tiling
// working, and is the only thing that can work at all under Wayland, where a
// window is not allowed to place itself.
Item {
    id: grips

    // The window being resized.
    property var target: null

    // Thin enough that nothing drawn at the edge becomes hard to hit, thick
    // enough to be caught without aiming. The corners are wider so the two
    // edges they join can both be reached there.
    property int thickness: 6
    property int corner: 14

    component Grip: MouseArea {
        // Which edges of the window this one moves, as a Qt.Edges flag.
        property int edges: 0
        acceptedButtons: Qt.LeftButton
        // Immediately on press rather than after a drag threshold. A strip
        // this thin is left the moment the pointer moves, and a resize that
        // only began after that would never start.
        onPressed: if (grips.target) grips.target.startSystemResize(edges)
    }

    Grip {
        objectName: "gripLeft"
        edges: Qt.LeftEdge
        cursorShape: Qt.SizeHorCursor
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: grips.corner
        anchors.bottomMargin: grips.corner
        width: grips.thickness
    }

    Grip {
        objectName: "gripRight"
        edges: Qt.RightEdge
        cursorShape: Qt.SizeHorCursor
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: grips.corner
        anchors.bottomMargin: grips.corner
        width: grips.thickness
    }

    Grip {
        objectName: "gripTop"
        edges: Qt.TopEdge
        cursorShape: Qt.SizeVerCursor
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: grips.corner
        anchors.rightMargin: grips.corner
        height: grips.thickness
    }

    Grip {
        objectName: "gripBottom"
        edges: Qt.BottomEdge
        cursorShape: Qt.SizeVerCursor
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: grips.corner
        anchors.rightMargin: grips.corner
        height: grips.thickness
    }

    Grip {
        objectName: "gripTopLeft"
        edges: Qt.TopEdge | Qt.LeftEdge
        cursorShape: Qt.SizeFDiagCursor
        anchors.top: parent.top
        anchors.left: parent.left
        width: grips.corner
        height: grips.corner
    }

    Grip {
        objectName: "gripTopRight"
        edges: Qt.TopEdge | Qt.RightEdge
        cursorShape: Qt.SizeBDiagCursor
        anchors.top: parent.top
        anchors.right: parent.right
        width: grips.corner
        height: grips.corner
    }

    Grip {
        objectName: "gripBottomLeft"
        edges: Qt.BottomEdge | Qt.LeftEdge
        cursorShape: Qt.SizeBDiagCursor
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        width: grips.corner
        height: grips.corner
    }

    Grip {
        objectName: "gripBottomRight"
        edges: Qt.BottomEdge | Qt.RightEdge
        cursorShape: Qt.SizeFDiagCursor
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: grips.corner
        height: grips.corner
    }
}
