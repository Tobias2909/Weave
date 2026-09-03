import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    visible: true
    width: 1400
    height: 900
    minimumWidth: 640
    minimumHeight: 480
    title: "Weave"
    color: Theme.colors.background

    header: ToolBar {
        background: Rectangle {
            color: Theme.colors.surface
            border.width: 0
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.colors.border
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 12

            Label {
                text: "Weave"
                color: Theme.colors.text
                font.pixelSize: 18
                font.weight: Font.Bold
            }

            TextField {
                id: addField
                Layout.preferredWidth: 300
                placeholderText: "Add a channel id or a twitch.tv link"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: addField.activeFocus ? Theme.colors.accent : Theme.colors.border
                }
                onAccepted: {
                    if (App.addChannel(text)) {
                        text = ""
                        App.refresh()
                    }
                }
            }

            Item { Layout.fillWidth: true }

            Label {
                text: App.status
                color: Theme.colors.textMuted
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.maximumWidth: 420
            }

            Switch {
                text: "Hide watched"
                checked: App.hideWatched
                onToggled: App.setHideWatched(checked)
                contentItem: Label {
                    text: parent.text
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    leftPadding: parent.indicator.width + 6
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                text: App.busy ? "Refreshing" : "Refresh"
                enabled: !App.busy
                onClicked: App.refresh()
                contentItem: Label {
                    text: parent.text
                    color: Theme.colors.text
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 6
                    color: parent.enabled ? (parent.hovered ? Theme.colors.accentHover
                                                            : Theme.colors.accent)
                                          : Theme.colors.border
                }
            }
        }
    }

    // A source that fails silently is the failure mode this whole app has to
    // guard against, so problems are visible here rather than only in settings.
    Rectangle {
        id: banner
        visible: App.problems.length > 0
        anchors.top: parent.top
        width: parent.width
        height: visible ? 32 : 0
        color: Theme.colors.surfaceRaised
        z: 2

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 8
            Label {
                text: App.problems.length + " problem"
                      + (App.problems.length === 1 ? "" : "s") + "  ·  "
                      + App.problems[App.problems.length - 1]
                color: Theme.colors.error
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
    }

    GridView {
        id: grid
        anchors.fill: parent
        anchors.topMargin: banner.height + 10
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        clip: true
        cellWidth: Math.max(260, Math.floor(width / Math.max(1, Math.floor(width / 330))))
        cellHeight: cellWidth * 9 / 16 + 108
        model: feedModel
        cacheBuffer: 800

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            VideoCard {
                anchors.fill: parent
                anchors.margins: 6
                title: model.title
                channelTitle: model.channelTitle
                thumbnail: model.thumbnail
                ageText: model.ageText
                durationText: model.durationText
                viewsText: model.viewsText
                likesText: model.likesText
                watched: model.watched
                isLive: model.isLive
                onPlayRequested: App.play(model.key)
                onDetailsRequested: model.watched ? App.markUnwatched(model.key)
                                                  : App.markWatched(model.key)
            }
        }

        Label {
            anchors.centerIn: parent
            visible: grid.count === 0
            horizontalAlignment: Text.AlignHCenter
            color: Theme.colors.textMuted
            font.pixelSize: 14
            text: "Nothing here yet.\nAdd a channel above, then press Refresh."
        }
    }
}
