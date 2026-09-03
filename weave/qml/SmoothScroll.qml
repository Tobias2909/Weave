import QtQuick

// Wheel scrolling that glides, for any Flickable.
//
// A Flickable on its own jumps about sixty pixels a notch, which reads as
// stuck rather than as movement. Successive notches add to the animation's
// target rather than restarting from wherever the view has reached, so several
// quick notches travel the full distance instead of swallowing each other, and
// a drag or a flick takes over.
//
// Declared beside the Flickable rather than inside it, since a child of a
// Flickable is reparented into content that moves.
Item {
    id: control

    property Flickable flickable: null
    property bool horizontal: false
    property real step: 160
    property int duration: 160

    readonly property string axis: horizontal ? "contentX" : "contentY"

    NumberAnimation {
        id: glide
        target: control.flickable
        property: control.axis
        duration: control.duration
        easing.type: Easing.OutCubic
    }

    Connections {
        target: control.flickable
        function onMovementStarted() { glide.stop() }
        function onDraggingChanged() { if (control.flickable.dragging) glide.stop() }
    }

    WheelHandler {
        parent: control.flickable
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function (event) {
            if (!control.flickable)
                return
            var notches = (control.horizontal && event.angleDelta.y === 0
                           ? event.angleDelta.x : event.angleDelta.y) / 120
            if (notches === 0)
                return
            var span = control.horizontal
                       ? control.flickable.contentWidth - control.flickable.width
                       : control.flickable.contentHeight - control.flickable.height
            var limit = Math.max(0, span)
            var here = control.horizontal ? control.flickable.contentX
                                          : control.flickable.contentY
            var from = glide.running ? glide.to : here
            var to = Math.max(0, Math.min(limit, from - notches * control.step))
            if (to === here) {
                glide.stop()
                return
            }
            glide.stop()
            glide.from = here
            glide.to = to
            glide.start()
        }
    }
}
