import QtQuick
import QtQuick.Controls

// Minimise, maximise and close, drawn inside a row the window already has
// rather than in a bar of its own, so a frameless window loses nothing and
// gains no height.
//
// It knows nothing about the window. Which one it acts on, and whether that
// one is maximised, are handed in, so the same three buttons could sit in any
// row.
Row {
    id: controls

    // Which of the two shapes the middle button offers.
    property bool maximised: false

    signal minimiseRequested()
    signal maximiseRequested()
    signal closeRequested()

    spacing: 2

    // One look for all three, and squarer than an ordinary button, since these
    // read as part of the bar rather than as controls sitting on it.
    component ControlButton: Button {
        id: button

        // Closing is the one that ends the session, so it says so under the
        // pointer while the other two only lift.
        property bool destructive: false

        implicitWidth: 34
        implicitHeight: 26
        padding: 0

        contentItem: Label {
            text: button.text
            font.pixelSize: 13
            color: button.destructive && button.hovered ? Theme.colors.badgeText
                                                        : Theme.colors.textMuted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        background: Rectangle {
            radius: 5
            // Nothing of its own when it is not under the pointer, so the bar
            // shows through and these do not read as three boxes in a row.
            color: {
                if (!button.hovered)
                    return "transparent"
                return button.destructive ? Theme.colors.live : Theme.colors.surfaceRaised
            }
        }
    }

    ControlButton {
        objectName: "windowMinimise"
        text: "─"
        onClicked: controls.minimiseRequested()
    }

    ControlButton {
        objectName: "windowMaximise"
        text: controls.maximised ? "❐" : "□"
        onClicked: controls.maximiseRequested()
    }

    ControlButton {
        objectName: "windowClose"
        destructive: true
        text: "✕"
        onClicked: controls.closeRequested()
    }
}
