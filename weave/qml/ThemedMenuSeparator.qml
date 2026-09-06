import QtQuick
import QtQuick.Controls

// A line between two groups of entries, in the theme's own border colour.
MenuSeparator {
    id: line

    padding: 4
    leftPadding: 10
    rightPadding: 10

    contentItem: Rectangle {
        implicitHeight: 1
        color: Theme.colors.border
    }
}
