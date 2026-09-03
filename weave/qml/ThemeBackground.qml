import QtQuick

// The window's ground, flat or washed with the theme's gradient.
//
// Painted on a canvas rather than assembled from gradient stops. A Rectangle's
// gradient only runs straight down, a rotated one has to be oversized and
// clipped, and building stops at runtime means creating objects from strings.
// A canvas takes an angle directly, runs on any backend including the software
// one, and leaves room for other gradient shapes later.
Item {
    id: ground

    readonly property var spec: Theme.gradient
    readonly property bool washed: spec.stops !== undefined

    Rectangle {
        anchors.fill: parent
        color: Theme.colors.background
    }

    Canvas {
        id: wash
        anchors.fill: parent
        visible: ground.washed
        renderStrategy: Canvas.Cooperative

        onPaint: {
            var context = getContext("2d")
            context.reset()
            if (!ground.washed)
                return

            var gradient
            if (ground.spec.type === "radial") {
                // Placed in fractions of the window and sized in fractions of
                // its diagonal, so a theme looks the same at any window size.
                var ox = ground.spec.originX * width
                var oy = ground.spec.originY * height
                var reach = Math.sqrt(width * width + height * height) * ground.spec.radius
                gradient = context.createRadialGradient(ox, oy, 0, ox, oy, reach)
            } else {
                // Zero runs straight down the window, forty five starts at the
                // top left corner. The line is the window's span along that
                // direction, so every stop lands where the author meant it to.
                var radians = ground.spec.angle * Math.PI / 180
                var dx = Math.sin(radians)
                var dy = Math.cos(radians)
                var span = Math.abs(width * dx) + Math.abs(height * dy)
                var cx = width / 2
                var cy = height / 2
                gradient = context.createLinearGradient(
                    cx - dx * span / 2, cy - dy * span / 2,
                    cx + dx * span / 2, cy + dy * span / 2)
            }

            for (var i = 0; i < ground.spec.stops.length; i++)
                gradient.addColorStop(ground.spec.stops[i].position,
                                      ground.spec.stops[i].color)

            context.fillStyle = gradient
            context.fillRect(0, 0, width, height)
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Connections {
        target: Theme
        function onChanged() { wash.requestPaint() }
    }
}
