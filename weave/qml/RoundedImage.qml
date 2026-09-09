import QtQuick
import QtQuick.Effects

// An image with genuinely rounded corners.
//
// Setting a radius on a Rectangle and turning on clip does not do this. Qt
// Quick clips to a rectangle whatever the radius is, so the picture keeps its
// square corners and only the frame behind it looks rounded. The picture has
// to be masked instead.
//
// Masking needs a shader, and the software scene graph cannot run one. On that
// backend the effect draws nothing at all, which would mean no pictures rather
// than square ones, so the plain image is shown instead. Rounded on hardware,
// square on software, never missing.
Item {
    id: root

    property alias source: picture.source
    property real radius: 6
    property bool circle: false
    property int fillMode: Image.PreserveAspectCrop
    property bool masked: (typeof EffectsAvailable === "undefined") ? true : EffectsAvailable

    Image {
        id: picture
        anchors.fill: parent
        asynchronous: true
        cache: true
        fillMode: root.fillMode
        // PreserveAspectCrop paints outside the item unless it is told not to,
        // which the masked path never notices because the mask cuts it back.
        // The fallback has no mask, so without this a picture whose shape does
        // not match its box hangs over whatever is beside it.
        clip: true
        // Drawn by the effect below when there is one to draw it.
        visible: !root.masked
        layer.enabled: root.masked
    }

    Rectangle {
        id: mask
        anchors.fill: parent
        // No point rendering a mask nothing will read.
        enabled: root.masked
        radius: root.circle ? Math.min(width, height) / 2 : root.radius
        antialiasing: true
        visible: false
        layer.enabled: true
    }

    MultiEffect {
        anchors.fill: parent
        visible: root.masked
        source: picture
        maskEnabled: true
        maskSource: mask
        // A hard edge. Without these the mask fades instead of cutting.
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1.0
    }
}
