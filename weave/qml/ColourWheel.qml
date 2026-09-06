import QtQuick

// A disc of every hue, with the middle of it pale and the rim full strength.
// Painted once and kept, because it is repainted for nothing otherwise and a
// dot is dragged across it many times a second. Canvas rather than a shader,
// so it draws on the software backend as well.
Canvas {
    id: wheel

    // Where a colour sits on the disc, and what colour sits somewhere on it.
    // Both are here rather than in the page, so the arithmetic that draws the
    // disc and the arithmetic that reads it cannot drift apart.
    function colourAt(px, py) {
        var half = width / 2
        var dx = (px - half) / half
        var dy = (py - half) / half
        var distance = Math.min(1, Math.sqrt(dx * dx + dy * dy))
        var angle = Math.atan2(dy, dx)
        if (angle < 0)
            angle += 2 * Math.PI
        return Qt.hsva(angle / (2 * Math.PI), distance, 1.0, 1.0)
    }

    function placeOf(colour) {
        var half = width / 2
        var angle = colour.hsvHue < 0 ? 0 : colour.hsvHue * 2 * Math.PI
        var distance = colour.hsvSaturation
        return Qt.point(half + Math.cos(angle) * distance * half,
                        half + Math.sin(angle) * distance * half)
    }

    function inside(px, py) {
        var half = width / 2
        var dx = px - half
        var dy = py - half
        return Math.sqrt(dx * dx + dy * dy) <= half
    }

    onPaint: {
        var ctx = getContext("2d")
        var half = width / 2
        ctx.clearRect(0, 0, width, height)
        // Drawn as a fan of thin wedges. A per pixel loop is the obvious way
        // and is far too slow for a disc this size.
        for (var step = 0; step < 360; step++) {
            // Wider than the step they are drawn at, so neighbours overlap
            // and no seam shows between them.
            var from = (step - 1.2) * Math.PI / 180
            var to = (step + 1.2) * Math.PI / 180
            var run = ctx.createLinearGradient(
                half, half,
                half + Math.cos(step * Math.PI / 180) * half,
                half + Math.sin(step * Math.PI / 180) * half)
            run.addColorStop(0, Qt.hsva(step / 360, 0, 1, 1))
            run.addColorStop(1, Qt.hsva(step / 360, 1, 1, 1))
            ctx.beginPath()
            ctx.moveTo(half, half)
            ctx.arc(half, half, half, from, to, false)
            ctx.closePath()
            ctx.fillStyle = run
            ctx.fill()
        }
    }
}
