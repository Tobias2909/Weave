import QtQuick
import QtQuick.Controls

// The band above the grid on a channel page. The banner and the subscriber
// count are fetched the first time a channel page is opened, so this renders
// without them and fills in when they arrive.
Item {
    id: header
    property var info: ({})
    signal closeRequested()

    height: visible ? 168 : 0

    Rectangle {
        anchors.fill: parent
        color: Theme.colors.surface
        clip: true

        Image {
            id: bannerImage
            anchors.fill: parent
            source: header.info.banner ? header.info.banner : ""
            visible: source !== ""
            asynchronous: true
            cache: true
            fillMode: Image.PreserveAspectCrop
            opacity: 0.55
        }

        // Keeps the text legible whatever the banner looks like.
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: Theme.colors.surface }
            }
        }

        Row {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: 20
            anchors.bottomMargin: 16
            spacing: 14

            Rectangle {
                width: 72
                height: 72
                radius: 36
                clip: true
                color: Theme.colors.surfaceRaised
                border.width: 2
                border.color: Theme.colors.surface

                Image {
                    anchors.fill: parent
                    source: header.info.avatar ? header.info.avatar : ""
                    asynchronous: true
                    cache: true
                    fillMode: Image.PreserveAspectCrop
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4

                Label {
                    text: header.info.title ? header.info.title : ""
                    color: Theme.colors.text
                    font.pixelSize: 22
                    font.weight: Font.Bold
                }

                Label {
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    text: {
                        var parts = []
                        if (header.info.followersText)
                            parts.push(header.info.followersText + " subscribers")
                        if (header.info.videos > 0)
                            parts.push(header.info.videos + " videos here")
                        return parts.join("  ·  ")
                    }
                }
            }
        }

        FlatButton {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 12
            text: "Back to the feed"
            onClicked: header.closeRequested()
        }

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.colors.border
        }
    }
}
