import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// What is playing, beside the feed. It follows mpv rather than the grid, so it
// shows whatever is on screen even when mpv moved on by itself.
Rectangle {
    id: panel
    color: Qt.rgba(Theme.colors.surface.r, Theme.colors.surface.g,
                   Theme.colors.surface.b, Theme.washed ? 0.62 : 1.0)

    Rectangle {
        anchors.left: parent.left
        width: 1
        height: parent.height
        color: Theme.colors.border
    }

    // Drag the left edge to resize. The width is remembered.
    Item {
        id: grip
        anchors.left: parent.left
        anchors.leftMargin: -3
        width: 7
        height: parent.height
        z: 2

        HoverHandler { cursorShape: Qt.SizeHorCursor }
        DragHandler {
            target: null
            yAxis.enabled: false
            onActiveChanged: if (!active) App.setPanelWidth(panel.width)
            onTranslationChanged: App.setPanelWidth(panel.width - translation.x)
        }
    }

    RowLayout {
        id: panelHead
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 14
        anchors.rightMargin: 8
        height: 34

        Label {
            text: "Now playing"
            color: Theme.colors.textMuted
            font.pixelSize: 11
            font.letterSpacing: 1.1
            font.weight: Font.DemiBold
        }

        Item { Layout.fillWidth: true }

        FlatButton {
            text: "✕"
            onClicked: App.closeDetail()
        }
    }

    SmoothScroll { flickable: panelBody }

    Flickable {
        id: panelBody
        anchors.top: panelHead.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 12
        anchors.topMargin: 0
        contentHeight: body.height
        clip: true
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: body
            width: parent.width
            spacing: 10

            RoundedImage {
                width: parent.width
                height: width * 9 / 16
                radius: 8
                source: App.detail.thumbnail ? App.detail.thumbnail : ""
            }

            Label {
                width: parent.width
                text: App.detail.title ? App.detail.title : ""
                color: Theme.colors.text
                font.pixelSize: 15
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }

            Row {
                width: parent.width
                spacing: 8

                HoverHandler { id: channelHover }
                TapHandler { onTapped: App.openChannel(App.detail.channelKey) }

                RoundedImage {
                    width: 28
                    height: 28
                    circle: true
                    visible: App.detail.channelAvatar !== ""
                    source: App.detail.channelAvatar ? App.detail.channelAvatar : ""
                }

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    text: App.detail.channelTitle ? App.detail.channelTitle : ""
                    color: channelHover.hovered ? Theme.colors.text : Theme.colors.textMuted
                    font.pixelSize: 13
                    font.underline: channelHover.hovered
                    elide: Text.ElideRight
                    width: Math.max(0, parent.width - 36)
                }
            }

            Flow {
                width: parent.width
                spacing: 14

                Repeater {
                    model: [
                        { label: "watching now", value: App.detail.watchingText },
                        { label: "", value: App.detail.gameText },
                        { label: "views", value: App.detail.viewsText },
                        { label: "likes", value: App.detail.likesText },
                        { label: "dislikes, estimated", value: App.detail.dislikesText },
                        { label: "", value: App.detail.durationText },
                        { label: "", value: App.detail.ageText },
                    ]
                    Label {
                        required property var modelData
                        // A binding is evaluated even while the item is
                        // hidden, so an absent field has to become an empty
                        // string here rather than reaching the text property
                        // as undefined.
                        readonly property string value: modelData.value ? modelData.value : ""
                        visible: value !== ""
                        text: modelData.label === "" ? value : value + " " + modelData.label
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.colors.border }

            Label {
                text: App.detailLoading ? "Loading comments" : "Comments"
                color: Theme.colors.textMuted
                font.pixelSize: 11
                font.letterSpacing: 1.1
                font.weight: Font.DemiBold
            }

            Label {
                width: parent.width
                visible: !App.detailLoading && App.detailComments.length === 0
                text: "No comments to show."
                color: Theme.colors.textMuted
                font.pixelSize: 12
            }

            Repeater {
                model: App.detailComments
                CommentThread {
                    required property var modelData
                    width: body.width
                    comment: modelData
                }
            }

            FlatButton {
                visible: App.detailComments.length > 0
                enabled: !App.detailLoading
                text: App.detailLoading ? "Loading" : "Show more"
                onClicked: App.loadMoreComments()
            }

            Item { width: 1; height: 4 }
        }
    }
}
