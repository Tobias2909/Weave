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
                placeholderText: "Add a channel, a handle or a twitch.tv link"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: addField.activeFocus ? Theme.colors.accent : Theme.colors.border
                }
                onAccepted: {
                    // Keep the text when it was not even understood, so a typo
                    // can be corrected rather than retyped.
                    if (App.addChannel(text))
                        text = ""
                }
            }

            Button {
                text: "Import subscriptions"
                onClicked: App.importSubscriptions()
                contentItem: Label {
                    text: parent.text
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? Theme.colors.surfaceRaised : "transparent"
                    border.width: 1
                    border.color: Theme.colors.border
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

    // Groups live here. Membership is managed with the group subcommands for
    // now, this side is the filter.
    Rectangle {
        id: sidebar
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: banner.height
        width: 210
        color: Theme.colors.surface

        Rectangle {
            anchors.right: parent.right
            width: 1
            height: parent.height
            color: Theme.colors.border
        }

        ListView {
            id: groupList
            anchors.fill: parent
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            clip: true
            model: App.groups
            spacing: 2

            delegate: Rectangle {
                required property var modelData
                width: groupList.width
                height: 34
                color: modelData.id === App.selectedGroup ? Theme.colors.surfaceRaised
                                                          : "transparent"

                Rectangle {
                    visible: modelData.id === App.selectedGroup
                    width: 3
                    height: parent.height
                    color: Theme.colors.accent
                }

                HoverHandler { id: rowHover }
                TapHandler { onTapped: App.selectGroup(modelData.id) }

                Label {
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.right: countLabel.left
                    anchors.rightMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.name
                    elide: Text.ElideRight
                    font.pixelSize: 13
                    color: modelData.id === App.selectedGroup || rowHover.hovered
                           ? Theme.colors.text : Theme.colors.textMuted
                }

                Label {
                    id: countLabel
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.unwatched > 0 ? modelData.unwatched : ""
                    font.pixelSize: 11
                    color: Theme.colors.textMuted
                }
            }
        }
    }

    GridView {
        id: grid
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
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
                channelAvatar: model.channelAvatar
                progress: model.progress
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
            text: App.emptyHint
        }
    }
}
