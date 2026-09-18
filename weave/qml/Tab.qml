import QtQuick
import QtQuick.Controls

// One word in a row that walks between the halves of a page.
//
// These were buttons with a border each and the chosen one filled in the
// accent, which reads as a row of things to do rather than as where you are.
// A word with a line under it is what every other application means by a tab
// and it says the same thing more quietly.
//
// Still a Button underneath, so a press, the keyboard and the harness all
// reach it the way they always did. Declared one by one rather than built
// from a list, because a delegate is not a child anything can find by name.
Button {
    id: tab
    property bool selected: false

    implicitHeight: 30
    padding: 10

    contentItem: Label {
        text: tab.text
        font.pixelSize: 13
        font.weight: tab.selected ? Font.DemiBold : Font.Normal
        color: tab.selected || tab.hovered ? Theme.colors.text : Theme.colors.textMuted
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    // A line alone was too quiet on the themes whose accent sits close to
    // their ground, and a channel page draws these over its own banner, where
    // a thin line has almost nothing to stand against. So the tab you are on
    // carries the ground of its own as well.
    background: Rectangle {
        radius: 6
        color: tab.selected ? Theme.wash(Theme.colors.accent, 0.18)
                            : (tab.hovered ? Theme.wash(Theme.colors.accent, 0.10)
                                           : "transparent")

        Rectangle {
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 8
            height: 2
            radius: 1
            // Kept whatever happens, so nothing under the row moves as the
            // tabs are walked.
            color: tab.selected ? Theme.colors.accent : "transparent"
        }
    }
}
