import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Listening, rather than watching. Search first, because a library that is
// empty is not a place to start from.
Item {
    id: view

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            TextField {
                id: query
                Layout.fillWidth: true
                placeholderText: "Search YouTube Music"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: query.activeFocus ? Theme.colors.accent : Theme.colors.border
                }
                onAccepted: App.musicSearch(text)
            }

            FlatButton {
                text: App.musicSearching ? "Searching" : "Search"
                accent: true
                enabled: !App.musicSearching
                onClicked: App.musicSearch(query.text)
            }
        }

        // Things returned to rather than searched for, a round the clock
        // stream being the obvious one.
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            visible: App.audioSources.length > 0 || addRow.visible

            Label {
                text: "Saved"
                color: Theme.colors.textMuted
                font.pixelSize: 10
                font.letterSpacing: 1.1
                font.weight: Font.DemiBold
            }

            Flow {
                Layout.fillWidth: true
                spacing: 8

                Repeater {
                    model: App.audioSources
                    Rectangle {
                        required property var modelData
                        width: label.implicitWidth + 46
                        height: 30
                        radius: 15
                        color: pinHover.hovered ? Theme.colors.surfaceRaised : Theme.colors.surface
                        border.width: 1
                        border.color: modelData.live ? Theme.colors.live : Theme.colors.border

                        HoverHandler { id: pinHover }
                        TapHandler { onTapped: App.playSource(modelData.id) }

                        Label {
                            id: label
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: Theme.colors.text
                            font.pixelSize: 12
                        }

                        Label {
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: "✕"
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            TapHandler { onTapped: App.removeSource(modelData.id) }
                        }
                    }
                }
            }
        }

        RowLayout {
            id: addRow
            Layout.fillWidth: true
            spacing: 8

            TextField {
                id: sourceLabel
                Layout.preferredWidth: 160
                placeholderText: "Name"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6; color: Theme.colors.background
                    border.width: 1; border.color: Theme.colors.border
                }
            }
            TextField {
                id: sourceUrl
                Layout.fillWidth: true
                placeholderText: "Any YouTube address to keep, a stream for example"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6; color: Theme.colors.background
                    border.width: 1; border.color: Theme.colors.border
                }
                onAccepted: addButton.save()
            }
            CheckBox {
                id: isLive
                text: "live"
                contentItem: Label {
                    text: parent.text
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    leftPadding: parent.indicator.width + 4
                    verticalAlignment: Text.AlignVCenter
                }
            }
            FlatButton {
                id: addButton
                text: "Save"
                function save() {
                    App.addSource(sourceLabel.text, sourceUrl.text, isLive.checked)
                    sourceLabel.text = ""
                    sourceUrl.text = ""
                }
                onClicked: save()
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.colors.border }

        ListView {
            id: results
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: App.musicResults
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Label {
                anchors.centerIn: parent
                visible: results.count === 0 && !App.musicSearching
                horizontalAlignment: Text.AlignHCenter
                color: Theme.colors.textMuted
                font.pixelSize: 13
                text: "Search for something, or save an address above.\nThe headphone on any video card plays it here too."
            }

            delegate: Rectangle {
                required property var modelData
                required property int index
                width: results.width
                height: 52
                radius: 6
                color: rowHover.hovered ? Theme.colors.surfaceRaised : "transparent"

                HoverHandler { id: rowHover }
                TapHandler { onTapped: App.playResult(index) }

                Row {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 10

                    RoundedImage {
                        width: 40
                        height: 40
                        radius: 5
                        source: modelData.thumbnail
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 120
                        spacing: 2
                        Label {
                            width: parent.width
                            text: modelData.title
                            color: Theme.colors.text
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                        Label {
                            width: parent.width
                            text: modelData.artist
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }
                }

                Label {
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.duration
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                }
            }
        }
    }

    SmoothScroll { flickable: results }
}
