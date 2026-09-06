import QtQuick
import QtQuick.Controls

// A menu drawn by this application rather than by the platform, so it wears
// the chosen theme like everything else. Kept inside the window on purpose:
// a menu in a window of its own is styled by whatever the desktop provides
// and would be the one square, pale thing in a dark window.
Menu {
    id: control

    popupType: Popup.Item
    implicitWidth: 250
    padding: 6
    margins: 10
    overlap: 2

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: 90 }
        NumberAnimation {
            property: "scale"
            from: 0.97
            to: 1.0
            duration: 110
            easing.type: Easing.OutCubic
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0.0; duration: 70 }
    }

    background: Rectangle {
        implicitWidth: control.implicitWidth
        color: Theme.colors.surfaceRaised
        radius: 10
        border.width: 1
        border.color: Theme.colors.border

        // No drawn shadow. A real one needs a shader the software backend
        // cannot run, and the ring of colour that stands in for it shows at
        // the rounded corners as a hard black hairline. The raised surface
        // against the page is separation enough.
    }
}
