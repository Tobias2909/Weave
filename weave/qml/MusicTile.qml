import QtQuick
import QtQuick.Controls

// A square picture with its name across the bottom, the shape a music app uses
// for anything you pick rather than read.
Item {
    id: tile
    property string title: ""
    property string subtitle: ""
    property string picture: ""
    property bool removable: false

    signal chosen()
    signal removeRequested()
    // Right pressing a song offers to keep it. What that means is the caller's
    // business, since a tile does not know a favourite from a playlist.
    signal askedFor(int x, int y)

    // The size a shelf gives it. Kept as a default so the tile stands on its
    // own, and overridden by whatever lays a row of them out.
    width: 132
    height: 132

    HoverHandler { id: tileHover }

    RoundedImage {
        anchors.fill: parent
        radius: 8
        source: tile.picture
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: "transparent"
        border.width: 1
        border.color: tileHover.hovered ? Theme.colors.accent : Theme.colors.border
    }

    // A wash under the words, so a bright picture cannot swallow them.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: tile.subtitle === "" ? 34 : 46
        bottomLeftRadius: 8
        bottomRightRadius: 8
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#00000000" }
            GradientStop { position: 0.45; color: "#b0000000" }
            GradientStop { position: 1.0; color: "#e6000000" }
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 7
            spacing: 1

            Label {
                width: parent.width
                text: tile.title
                color: "#ffffff"
                font.pixelSize: 11
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 1
            }
            Label {
                width: parent.width
                visible: tile.subtitle !== ""
                text: tile.subtitle
                color: "#cfcfcf"
                font.pixelSize: 10
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }
    }

    Rectangle {
        visible: tile.removable && tileHover.hovered
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 5
        width: 20
        height: 20
        radius: 10
        color: Theme.colors.badgeBackground
        Label {
            anchors.centerIn: parent
            text: "✕"
            color: "#ffffff"
            font.pixelSize: 10
        }
        MouseArea {
            anchors.fill: parent
            onClicked: tile.removeRequested()
        }
    }

    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (mouse) {
            if (mouse.button === Qt.RightButton)
                tile.askedFor(mouse.x, mouse.y)
            else
                tile.chosen()
        }
    }
}
