import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The things that belong to the whole application rather than to any one view.
// Two of them were in the toolbar, which had run out of room for them, and the
// rest had no place in the window at all and could only be reached from a
// terminal.
Item {
    id: view

    // The list of playlists to show lives in a popup the window owns, so it is
    // asked for from here rather than opened from here.
    signal playlistsRequested()

    // One width for the left hand word of every stated fact, so the answers
    // line up down the page rather than each starting wherever its own word
    // happens to end.
    readonly property int wordWidth: 130

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Label {
            text: "Settings"
            color: Theme.colors.text
            font.pixelSize: 18
            font.weight: Font.Bold
        }

        Flickable {
            id: sheet
            objectName: "settingsSheet"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: body.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 10 }

            Column {
                id: body
                width: sheet.width - 16
                spacing: 14

                // ---- appearance ---------------------------------------------
                Rectangle {
                    width: body.width
                    height: appearance.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: appearance
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "Appearance"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Label {
                            width: parent.width
                            text: "A theme is a file. The ones that came with the application "
                                  + "and any dropped into the themes directory are all offered "
                                  + "here, and the one in use is filled in."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 20
                                text: "In use"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "currentTheme"
                                height: 20
                                text: Theme.current
                                color: Theme.colors.text
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Flow {
                            objectName: "themeChoices"
                            width: parent.width
                            spacing: 8

                            Repeater {
                                model: Theme.names

                                FlatButton {
                                    required property int index
                                    required property var modelData

                                    objectName: "themeChoice" + index
                                    text: modelData
                                    accent: modelData === Theme.current
                                    onClicked: {
                                        Theme.select(modelData)
                                        // The dots follow, so a theme can be
                                        // picked up and altered rather than
                                        // started from nothing.
                                        maker.adoptCurrent()
                                    }
                                }
                            }
                        }

                        ThemedMenuSeparator {
                            width: parent.width
                        }

                        Label {
                            text: "Make your own"
                            color: Theme.colors.text
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }

                        ThemeMaker {
                            id: maker
                            objectName: "themeMaker"
                            width: parent.width
                        }

                        Flow {
                            objectName: "ownThemes"
                            width: parent.width
                            spacing: 8
                            visible: App.ownThemes.length > 0

                            Repeater {
                                model: App.ownThemes

                                FlatButton {
                                    required property var modelData
                                    text: "Throw away " + modelData
                                    onClicked: App.deleteTheme(modelData)
                                }
                            }
                        }
                    }
                }

                // ---- what is stored -----------------------------------------
                Rectangle {
                    width: body.width
                    height: stored.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: stored
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "Your data"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Label {
                            width: parent.width
                            text: "Importing reads the subscription list from YouTube and tracks "
                                  + "every channel in it. It is worth doing once, and again after "
                                  + "subscribing to something."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            FlatButton {
                                objectName: "settingsImport"
                                text: "Import subscriptions"
                                onClicked: App.importSubscriptions()
                            }

                            FlatButton {
                                objectName: "settingsPlaylists"
                                text: "Playlist settings"
                                onClicked: view.playlistsRequested()
                            }
                        }

                        Label {
                            width: parent.width
                            text: "Every thumbnail, avatar and banner is kept on disk, so a view "
                                  + "you come back to does not download itself again. Dropping "
                                  + "them costs nothing but the time to fetch them once more."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Pictures"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "cacheSize"
                                height: 28
                                text: App.cacheText
                                color: Theme.colors.text
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Row {
                            spacing: 8

                            FlatButton {
                                objectName: "pruneImages"
                                text: "Drop what has aged out"
                                enabled: !App.cacheWorking
                                onClicked: App.pruneImageCache()
                            }

                            FlatButton {
                                objectName: "clearImages"
                                text: "Drop them all"
                                enabled: !App.cacheWorking
                                onClicked: App.clearImageCache()
                            }
                        }
                    }
                }

                // ---- what it talks to ---------------------------------------
                Rectangle {
                    width: body.width
                    height: connections.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: connections
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "Connections"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Twitch"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "twitchState"
                                height: 28
                                text: App.twitchStatus !== "" ? App.twitchStatus
                                                              : (App.twitchConnected ? "connected"
                                                                                     : "not connected")
                                color: Theme.colors.text
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "twitchConnect"
                                text: App.twitchConnected ? "Connect again" : "Connect"
                                onClicked: App.connectTwitch()
                            }
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 20
                                text: "Cookies"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "cookieSource"
                                width: connections.width - view.wordWidth - 8
                                height: 20
                                text: App.cookieSource
                                color: Theme.colors.text
                                font.pixelSize: 12
                                elide: Text.ElideMiddle
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 20
                                text: "Music identity"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "musicIdentity"
                                width: connections.width - view.wordWidth - 8
                                height: 20
                                text: App.musicIdentity
                                color: Theme.colors.text
                                font.pixelSize: 12
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Label {
                            width: parent.width
                            text: "Only the parts past the plain feed need cookies, and they are "
                                  + "read from the browser profile rather than stored here. A "
                                  + "Google account can carry more than one YouTube identity, and "
                                  + "the music requests have to say which."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }
}
