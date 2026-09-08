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
            // A Flickable with a content margin rests at minus that margin
            // rather than at zero, so the ends have to be worked out from the
            // margins and not assumed. Clamping at zero left a view with a
            // margin above it unable to reach its own top, which is where the
            // row of buttons over a group lives. With no margins these are
            // exactly zero and the span, which is what this used to say.
            var lower = -(control.horizontal ? control.flickable.leftMargin
                                             : control.flickable.topMargin)
            var reach = control.horizontal
                        ? control.flickable.contentWidth + control.flickable.rightMargin
                          - control.flickable.width
                        : control.flickable.contentHeight + control.flickable.bottomMargin
                          - control.flickable.height
            var upper = Math.max(lower, reach)
            var here = control.horizontal ? control.flickable.contentX
                                          : control.flickable.contentY
            var from = glide.running ? glide.to : here
            var to = Math.max(lower, Math.min(upper, from - notches * control.step))
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
