import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Listening rather than watching. It opens on what YouTube Music opens on,
// because a library that is empty is not a place to start from.
Item {
    id: view

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

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
                text: App.musicSearching ? "Working" : "Search"
                accent: true
                enabled: !App.musicSearching
                onClicked: App.musicSearch(query.text)
            }

            FlatButton {
                // These are YouTube likes rather than YouTube Music likes. The
                // two lists are separate and this is the one with anything in.
                text: "Liked"
                enabled: !App.musicSearching
                onClicked: App.playLiked()
            }

            FlatButton {
                visible: App.musicResults.length > 0
                text: "Back to recommended"
                onClicked: { query.text = ""; App.clearResults() }
            }

            FlatButton {
                visible: App.musicResults.length === 0
                text: "Refresh"
                onClicked: App.refreshMusic()
            }
        }

        // ---- what is showing --------------------------------------------

        Flickable {
            id: shelfArea
            visible: App.musicResults.length === 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: shelfColumn.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                id: shelfColumn
                width: shelfArea.width
                spacing: 16

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    visible: App.audioSources.length > 0

                    Label {
                        text: "SAVED"
                        color: Theme.colors.textMuted
                        font.pixelSize: 10
                        font.letterSpacing: 1.2
                        font.weight: Font.DemiBold
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        Repeater {
                            model: App.audioSources
                            MusicTile {
                                required property var modelData
                                title: modelData.label
                                subtitle: modelData.live ? "live" : ""
                                picture: modelData.thumbnail ? modelData.thumbnail : ""
                                removable: true
                                onChosen: App.playSource(modelData.id)
                                onRemoveRequested: App.removeSource(modelData.id)
                            }
                        }
                    }
                }

                Repeater {
                    model: App.musicShelves
                    ColumnLayout {
                        required property var modelData
                        required property int index
                        // Named, so a tile inside can say which shelf it is in
                        // without colliding with its own index.
                        readonly property int shelfIndex: index
                        Layout.fillWidth: true
                        spacing: 8

                        Label {
                            text: modelData.title.toUpperCase()
                            color: Theme.colors.textMuted
                            font.pixelSize: 10
                            font.letterSpacing: 1.2
                            font.weight: Font.DemiBold
                        }

                        Flow {
                            Layout.fillWidth: true
                            spacing: 10
                            Repeater {
                                model: modelData.items
                                MusicTile {
                                    required property var modelData
                                    required property int index
                                    title: modelData.title
                                    subtitle: modelData.subtitle
                                    picture: modelData.thumbnail
                                    onChosen: App.playShelfItem(shelfIndex, index)
                                }
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: App.musicShelves.length === 0
                    text: App.musicSearching ? "Loading"
                                             : "Nothing to show yet. Search, or press Liked."
                    color: Theme.colors.textMuted
                    font.pixelSize: 13
                }

                Item { Layout.preferredHeight: 4 }
            }
        }

        RowLayout {
            visible: App.musicResults.length > 0
            Layout.fillWidth: true
            Label {
                text: App.musicLabel.toUpperCase()
                color: Theme.colors.textMuted
                font.pixelSize: 10
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            Label {
                text: App.musicResults.length + " tracks"
                color: Theme.colors.textMuted
                font.pixelSize: 11
            }
        }

        ListView {
            id: results
            visible: App.musicResults.length > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: App.musicResults
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

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

                    RoundedImage { width: 40; height: 40; radius: 5; source: modelData.thumbnail }

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

        // ---- keeping an address ------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            TextField {
                id: sourceLabel
                Layout.preferredWidth: 150
                placeholderText: "Name, optional"
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
                placeholderText: "Keep an address, a round the clock stream for example"
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
    }

    SmoothScroll { flickable: shelfArea }
    SmoothScroll { flickable: results }
}
