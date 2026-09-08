import QtQuick
import QtQuick.Controls

// One playlist, drawn as a video card with the rest of the list showing behind
// it. A playlist is videos stacked on top of each other, so the card says so
// by being a stack rather than by carrying a word.
//
// Every colour comes from the Theme role map, never a literal, like the card
// this one is shaped after.
Item {
    id: card

    property string title: ""
    property string thumbnail: ""
    property string itemsText: ""
    property bool kept: false

    signal openRequested()
    signal keepRequested()

    readonly property int lift: 8

    HoverHandler { id: hover }
    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: card.openRequested()
    }

    // The rest of the list, behind the card. Two sheets is enough to read as
    // a stack; a third adds nothing but edges. Drawn before the body, so the
    // body covers all of each one but the edge that is meant to show.
    Repeater {
        model: 2

        Rectangle {
            required property int index
            readonly property int step: (2 - index) * card.lift

            x: step
            y: body.y - step
            width: body.width - step * 2
            height: body.height
            radius: 8
            color: index === 0 ? Theme.colors.surface : Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border
        }
    }

    Rectangle {
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: parent.height - card.lift * 2
        radius: 8
        color: hover.hovered ? Theme.colors.surfaceRaised : Theme.colors.surface
        border.width: 1
        border.color: hover.hovered ? Theme.colors.accent : Theme.colors.border

        Column {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 6

            Item {
                width: parent.width
                height: width * 9 / 16

                Rectangle {
                    id: frame
                    anchors.fill: parent
                    radius: 8
                    color: Theme.colors.background

                    RoundedImage {
                        anchors.fill: parent
                        radius: parent.radius
                        source: card.thumbnail
                    }
                }
            }

            Label {
                width: parent.width
                text: card.title
                color: Theme.colors.text
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 2
                wrapMode: Text.Wrap
            }

            Item {
                width: parent.width
                height: 20

                Label {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: card.itemsText !== "" ? card.itemsText : "not read yet"
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                }

                FlatButton {
                    objectName: "keepPlaylist"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    visible: hover.hovered || card.kept
                    text: card.kept ? "Kept" : "Keep"
                    accent: card.kept
                    onClicked: card.keepRequested()
                }
            }
        }
    }
}
