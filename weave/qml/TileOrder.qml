import QtQuick
import QtQuick.Controls

// What is carried and where it will land, drawn over a grid of equal tiles
// whose order can be changed. DragOrder does the same for a list, a row at a
// time; here a tile can land anywhere across as well as down, so the landing
// mark is a bar standing between two tiles rather than a line between rows.
//
// Works from the pointer and the scroll position alone, never from a tile
// that was moved, so scrolling while a tile is held changes nothing but where
// it would land. Near the top or the bottom edge the page scrolls by itself,
// the same way and under the same rules as DragOrder: not at once when the
// tile was taken inside an edge's reach, and building up rather than starting
// at full speed.
Item {
    id: order

    // The page that scrolls, and the grid inside it that holds the tiles.
    property Flickable list: null
    property Item grid: null
    property int tileSize: 132
    property int spacing: 10
    property int count: 0

    // The tile being carried, and the tile it would be put down in front of,
    // which is the number of tiles when it would go on the end. Both -1 while
    // nothing is carried.
    property int from: -1
    property int at: -1
    property string title: ""
    property string subtitle: ""
    property string picture: ""
    // The pointer, in the window and across the visible part of the page.
    property real sceneX: 0
    property real sceneY: 0
    property real viewX: 0
    property real viewY: 0
    // Where the landing bar stands, across the visible part of the page.
    property real barX: 0
    property real barY: 0
    readonly property bool carrying: from >= 0

    readonly property real step: tileSize + spacing
    readonly property int columns: grid ? Math.max(1, Math.floor((grid.width + spacing) / step))
                                        : 1

    property int edge: 40
    property int pushOn: 12
    property int rampMs: 350
    property real startY: 0
    property bool scrollArmed: false
    property real edgeHeldMs: 0

    signal dropped(int from, int before)

    anchors.fill: parent
    clip: true
    z: 5

    function settle() {
        if (!order.carrying || !order.grid)
            return
        var here = order.mapFromItem(null, order.sceneX, order.sceneY)
        order.viewX = here.x
        order.viewY = here.y
        var inGrid = order.grid.mapFromItem(null, order.sceneX, order.sceneY)
        var rows = Math.max(1, Math.ceil(order.count / order.columns))
        var row = Math.max(0, Math.min(rows - 1, Math.floor(inGrid.y / order.step)))
        // In front of a tile while the pointer is on its left half, behind it
        // once past the middle.
        var col = Math.max(0, Math.min(order.columns,
                                       Math.floor((inGrid.x - order.tileSize / 2) / order.step)
                                       + 1))
        var onRow = Math.min(order.columns, order.count - row * order.columns)
        col = Math.min(col, onRow)
        order.at = row * order.columns + col
        var bar = order.grid.mapToItem(order, col * order.step - order.spacing / 2,
                                       row * order.step)
        order.barX = bar.x
        order.barY = bar.y
    }

    function begin(index, words, under, picture, x, y, pressY) {
        order.from = index
        order.title = words
        order.subtitle = under
        order.picture = picture
        order.sceneX = x
        order.sceneY = y
        order.settle()
        order.startY = order.mapFromItem(null, 0, pressY).y
        order.scrollArmed = order.edgeDepth(order.startY) === 0
        order.edgeHeldMs = 0
        App.traceMark("order_take", {
            "tile": index, "pressY": Math.round(order.startY), "viewY": Math.round(order.viewY),
            "height": Math.round(order.height), "armed": order.scrollArmed,
            "scrolled": order.list ? Math.round(order.list.contentY) : -1 })
    }

    function edgeDepth(y) {
        if (y < order.edge)
            return y - order.edge
        if (y > order.height - order.edge)
            return y - (order.height - order.edge)
        return 0
    }

    function armedAt(y) {
        if (order.scrollArmed)
            return true
        var depth = order.edgeDepth(y)
        if (depth === 0)
            return true
        var further = depth < 0 ? order.startY - y : y - order.startY
        return further >= order.pushOn
    }

    function edgeStep(depth, heldMs) {
        if (depth === 0)
            return 0
        var into = Math.min(1, Math.abs(depth) / order.edge)
        var ramp = Math.min(1, heldMs / order.rampMs)
        var size = Math.max(1, Math.round((2 + 18 * into * into) * ramp))
        return depth < 0 ? -size : size
    }

    function carry(x, y) {
        order.sceneX = x
        order.sceneY = y
        order.settle()
    }

    // Whether letting go here would change anything. In front of the tile
    // itself or of the one after it is where it already is.
    readonly property bool moves: carrying && at >= 0 && at !== from && at !== from + 1

    function finish() {
        var was = order.from
        var to = order.at
        var moves = order.moves
        App.traceMark("order_drop", {
            "tile": was, "before": to, "viewY": Math.round(order.viewY),
            "scrolled": order.list ? Math.round(order.list.contentY) : -1 })
        order.from = -1
        order.at = -1
        if (moves)
            order.dropped(was, to)
    }

    Timer {
        interval: 16
        repeat: true
        running: order.carrying
        onTriggered: {
            order.scrollArmed = order.armedAt(order.viewY)
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

    // A smaller copy of the tile, hanging below and to the right of the
    // pointer. Centred on the pointer it covered the very gap it was about to
    // land in, bar and all. It takes no input, so the page underneath goes on
    // hearing the pointer that carries it.
    MusicTile {
        objectName: "tileCarried"
        visible: order.carrying
        enabled: false
        width: Math.round(order.tileSize * 0.72)
        height: width
        x: Math.max(0, Math.min(order.width - width, order.viewX + 14))
        y: Math.max(0, Math.min(order.height - height, order.viewY + 14))
        opacity: 0.9
        title: order.title
        subtitle: order.subtitle
        picture: order.picture

        Rectangle {
            anchors.fill: parent
            radius: 8
            color: "transparent"
            border.width: 2
            border.color: Theme.colors.accent
        }
    }

    // Over the carried copy, should the two ever meet.
    Rectangle {
        objectName: "tileLandingBar"
        visible: order.moves
        x: order.barX - width / 2
        y: order.barY
        width: 4
        height: order.tileSize
        radius: 2
        color: Theme.colors.accent
    }
}
