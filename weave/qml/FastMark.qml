import QtQuick
import QtQuick.Controls

// Over a picture held down: it is running twice as fast, until let go. Light
// on dark whatever the theme, since it sits on the picture rather than on the
// window, and it takes no presses, so the hold under it is not disturbed.
Rectangle {
    id: mark

    anchors.horizontalCenter: parent.horizontalCenter
    anchors.top: parent.top
    anchors.topMargin: 16
    width: words.implicitWidth + 26
    height: 30
    radius: 15
    color: Qt.rgba(0, 0, 0, 0.7)

    Label {
        id: words
        anchors.centerIn: parent
        text: "2\u00d7  \u25b8\u25b8"
        color: "#f2f2f2"
        font.pixelSize: 13
        font.weight: Font.DemiBold
    }
}
