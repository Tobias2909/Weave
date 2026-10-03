import QtQuick
import QtQuick.Controls

// What is carried and where it will land, drawn over a list whose rows can be
// put in another order. Lies over the list's visible part, so it is given the
// list as its parent and fills it, and it takes no input of its own.
//
// Works from the pointer and the scroll position alone, never from a row that
// was moved, so scrolling while a row is held changes nothing but where it
// would land. Near the top or the bottom edge the list scrolls by itself,
// faster the closer the pointer is, so a row can be carried the length of a
// long list without letting go.
//
// Not the moment a row is taken, though. The first and the last row shown lie
// inside an edge's reach, and taking one of those set the list racing at once,
// up to nearly two thousand pixels a second, which looked like dragging the
// list rather than the playlist. A row taken there starts the scrolling only
// once the pointer has left the edge, or pushes further into it, and the
// scrolling builds up rather than starting at full speed.
Item {
    id: order

    // The list this orders.
    property Flickable list: null
    property int rowHeight: 30
    property int rowCount: 0
    // Width left free on the right, where the list's scroll bar is.
    property int inset: 12

    // The row being carried and where it would land, -1 while nothing is.
    property int from: -1
    property int at: -1
    property string title: ""
    // The pointer, across the visible part of the list.
    property real viewY: 0
    property real sceneY: 0
    readonly property bool carrying: from >= 0

    // How near an edge the pointer has to be for the list to scroll, how far
    // a row taken inside that reach has to be pushed on before it does, and
    // how long the scrolling takes to reach full speed.
    property int edge: 40
    property int pushOn: 12
    property int rampMs: 350
    // Where the row was taken, whether the edges scroll yet, and for how long
    // the pointer has been in one.
    property real startY: 0
    property bool scrollArmed: false
    property real edgeHeldMs: 0

    signal dropped(int from, int to)

    anchors.fill: parent
    clip: true
    z: 5

    function settle() {
        if (!order.carrying || !order.list)
            return
        order.viewY = order.mapFromItem(null, 0, order.sceneY).y
        var into = order.list.contentY - order.list.originY + order.viewY
        order.at = Math.max(0, Math.min(order.rowCount - 1, Math.floor(into / order.rowHeight)))
    }

    function begin(index, words, y, pressY) {
        order.from = index
        order.title = words
        order.sceneY = y
        order.settle()
        // Measured from the press rather than from where the carry began,
        // which is already some way along.
        order.startY = pressY === undefined ? order.viewY
                                            : order.mapFromItem(null, 0, pressY).y
        order.scrollArmed = order.edgeDepth(order.startY) === 0
        order.edgeHeldMs = 0
        App.traceMark("order_take", {
            "row": index, "pressY": Math.round(order.startY), "viewY": Math.round(order.viewY),
            "height": Math.round(order.height), "armed": order.scrollArmed,
            "scrolled": order.list ? Math.round(order.list.contentY) : -1 })
    }

    // How far into an edge's reach a point is: negative in the top one,
    // positive in the bottom one, nought between them.
    function edgeDepth(y) {
        if (y < order.edge)
            return y - order.edge
        if (y > order.height - order.edge)
            return y - (order.height - order.edge)
        return 0
    }

    // Whether the edges scroll, for a pointer now at `y`. Once they do, they
    // go on doing so until the row is let go.
    function armedAt(y) {
        if (order.scrollArmed)
            return true
        var depth = order.edgeDepth(y)
        if (depth === 0)
            return true
        var further = depth < 0 ? order.startY - y : y - order.startY
        return further >= order.pushOn
    }

    // How many pixels one turn of the timer scrolls, signed, for a pointer
    // `depth` into an edge that has been in it for `heldMs`. Slow at the inner
    // side of the reach and fast at the edge itself and past it, and building
    // up over rampMs so it never starts at full speed.
    function edgeStep(depth, heldMs) {
        if (depth === 0)
            return 0
        var into = Math.min(1, Math.abs(depth) / order.edge)
        var ramp = Math.min(1, heldMs / order.rampMs)
        var size = Math.max(1, Math.round((2 + 18 * into * into) * ramp))
        return depth < 0 ? -size : size
    }

    function carry(y) {
        order.sceneY = y
        order.settle()
    }

    function finish() {
        var was = order.from
        var to = order.at
        App.traceMark("order_drop", {
            "row": was, "to": to, "viewY": Math.round(order.viewY),
            "scrolled": order.list ? Math.round(order.list.contentY) : -1 })
        order.from = -1
        order.at = -1
        if (was >= 0 && to >= 0 && was !== to)
            order.dropped(was, to)
    }

    // The scrolling near an edge, and keeping the landing place right while
    // the list scrolls under a still pointer, wheel included.
    Timer {
        interval: 16
        repeat: true
        running: order.carrying
        onTriggered: {
            var armed = order.armedAt(order.viewY)
            if (armed && !order.scrollArmed)
                App.traceMark("order_edges_on", { "viewY": Math.round(order.viewY) })
            order.scrollArmed = armed
            var depth = order.scrollArmed ? order.edgeDepth(order.viewY) : 0
            order.edgeHeldMs = depth === 0 ? 0 : order.edgeHeldMs + interval
            var step = order.edgeStep(depth, order.edgeHeldMs)
            if (step !== 0 && order.list) {
                var low = order.list.originY
                var high = low + Math.max(0, order.list.contentHeight - order.list.height)
                order.list.contentY = Math.max(low, Math.min(high, order.list.contentY + step))
            }
            order.settle()
        }
    }

    Rectangle {
        objectName: "orderLandingLine"
        visible: order.carrying && order.at !== order.from
        width: order.width - order.inset
        height: 2
        radius: 1
        color: Theme.colors.accent
        y: order.list ? (order.at + (order.at > order.from ? 1 : 0)) * order.rowHeight
                        - (order.list.contentY - order.list.originY) - 1 : 0
    }

    Rectangle {
        objectName: "orderCarried"
        visible: order.carrying
        width: order.width - order.inset
        height: order.rowHeight
        radius: 6
        y: Math.max(0, Math.min(order.height - height, order.viewY - height / 2))
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.accent

        Label {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 26
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: order.title
            color: Theme.colors.text
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }
}
