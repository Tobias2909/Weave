import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// What is playing, beside the feed. It follows mpv rather than the grid, so it
// shows whatever is on screen even when mpv moved on by itself.
Rectangle {
    id: panel
    // Read as a colour first. The roles are handed over as text, and asking
    // a piece of text for its red gives nothing, which builds a black bar.
    //
    // Named ground rather than panel. A property that shares the name of an
    // id loses to the id, so panel.r read the item rather than the colour and
    // came back undefined, which Qt.rgba paints black. On a dark theme that
    // looked plausible. On a light one the whole bar was black with dark text
    // on it.
    readonly property color ground: Qt.color(Theme.colors.surface)

    // How much bigger everything in here is drawn than it is at the narrowest
    // the panel goes. The panel is dragged wider to read the comments, and a
    // wider panel that keeps eleven pixel text only fits more of the same
    // squint, so the words grow with the room. Narrow is the size it has
    // always been, deliberately: what is there now is right for that width and
    // only the widening needed an answer.
    //
    // The ceiling is a third bigger rather than the full width ratio. The
    // panel can be dragged to nearly twice its narrowest, and text at twice
    // the size reads as a different application rather than as the same one
    // with more room.
    readonly property int narrowest: 300
    readonly property int widest: 560
    readonly property real biggest: 1.35
    readonly property real textScale: {
        var along = (Math.max(narrowest, Math.min(widest, width)) - narrowest)
                    / (widest - narrowest)
        return 1 + along * (biggest - 1)
    }

    // Rounded once here rather than at every use, so two labels asked for the
    // same size can never land a pixel apart.
    function sized(pixels) { return Math.round(pixels * panel.textScale) }
    color: Qt.rgba(ground.r, ground.g, ground.b,
                   // A pale bar keeps more of itself, or the gradient behind
                   // it shows through and the dark text on it stops being
                   // readable.
                   Theme.washed ? (Theme.light ? 0.9 : 0.62) : 1.0)

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
            font.pixelSize: panel.sized(11)
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
                objectName: "detailTitle"
                width: parent.width
                text: App.detail.title ? App.detail.title : ""
                color: Theme.colors.text
                font.pixelSize: panel.sized(15)
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }

            Row {
                width: parent.width
                spacing: 8

                HoverHandler { id: channelHover }
                TapHandler { onTapped: App.openChannel(App.detail.channelKey) }

                RoundedImage {
                    width: panel.sized(28)
                    height: panel.sized(28)
                    circle: true
                    visible: App.detail.channelAvatar !== ""
                    source: App.detail.channelAvatar ? App.detail.channelAvatar : ""
                }

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    text: App.detail.channelTitle ? App.detail.channelTitle : ""
                    color: channelHover.hovered ? Theme.colors.text : Theme.colors.textMuted
                    font.pixelSize: panel.sized(13)
                    font.underline: channelHover.hovered
                    elide: Text.ElideRight
                    width: Math.max(0, parent.width - panel.sized(28) - 8)
                }
            }

            Flow {
                width: parent.width
                spacing: 14

                Repeater {
                    model: [
                        { label: "", value: App.detail.startsText
                                            ? "Starts " + App.detail.startsText : "" },
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
                        font.pixelSize: panel.sized(11)
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.colors.border }

            Label {
                text: App.detailLoading ? "Loading comments" : "Comments"
                color: Theme.colors.textMuted
                font.pixelSize: panel.sized(11)
                font.letterSpacing: 1.1
                font.weight: Font.DemiBold
            }

            Label {
                width: parent.width
                visible: !App.detailLoading && App.detailComments.length === 0
                text: "No comments to show."
                color: Theme.colors.textMuted
                font.pixelSize: panel.sized(12)
            }

            Repeater {
                model: App.detailComments
                CommentThread {
                    required property var modelData
                    width: body.width
                    comment: modelData
                    // Handed down rather than reached for. A component in
                    // another file cannot see an id declared in this one.
                    textScale: panel.textScale
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
