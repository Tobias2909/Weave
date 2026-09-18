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

    // The videos taken out of sight are a window of their own now, opened
    // from here and owned by the window, the same way the playlists are.
    signal hiddenRequested()

    // The part that scrolls, lent out so a wheel notch can be given the same
    // distance it has over the videos. What turns a notch into a distance has
    // to be declared beside a Flickable rather than inside one, since a child
    // of a Flickable rides in the content.
    readonly property Flickable scrolls: sheet

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

                        SettingsHeading { text: "Make your own" }

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

                        SettingsHeading { text: "Themes as files" }

                        Label {
                            width: parent.width
                            text: "A theme is a file of colours and nothing else, so one "
                                  + "can be handed to somebody or taken from them. Yours "
                                  + "are kept in the themes folder beside the settings."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            TextField {
                                id: themePath
                                objectName: "themePath"
                                width: view.width * 0.42
                                placeholderText: "A file, or a folder to copy into"
                                color: Theme.colors.text
                                placeholderTextColor: Theme.colors.textMuted
                                background: Rectangle {
                                    radius: 6
                                    color: Theme.colors.background
                                    border.width: 1
                                    border.color: themePath.activeFocus
                                                  ? Theme.colors.accent : Theme.colors.border
                                }
                            }

                            FlatButton {
                                objectName: "importTheme"
                                text: "Take one in"
                                enabled: themePath.text.trim() !== ""
                                onClicked: if (App.importTheme(themePath.text))
                                               themePath.text = ""
                            }

                            FlatButton {
                                objectName: "exportTheme"
                                text: "Hand out " + Theme.current
                                enabled: themePath.text.trim() !== ""
                                onClicked: App.exportTheme(Theme.current, themePath.text)
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

                        Row {
                            spacing: 8

                            FlatButton {
                                objectName: "settingsWizard"
                                text: "Getting started"
                                onClicked: App.openWizard()
                            }

                            FlatButton {
                                objectName: "settingsPlaylists"
                                text: "Playlist settings"
                                onClicked: view.playlistsRequested()
                            }
                        }

                        SettingsHeading { text: "Pictures on disk" }

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

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Ceiling"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                id: ceilingButton
                                objectName: "cacheCeiling"
                                text: App.cacheCeilingText + "  \u25be"
                                enabled: !App.cacheWorking
                                onClicked: ceilingMenu.popup(ceilingButton, 0,
                                                             ceilingButton.height + 2)

                                ThemedMenu {
                                    id: ceilingMenu
                                    objectName: "cacheCeilingMenu"
                                    implicitWidth: 160

                                    Repeater {
                                        model: App.cacheChoices

                                        ThemedMenuItem {
                                            required property var modelData

                                            // The tick marks the one in force. A menu here
                                            // draws its own entries, so a checkable item
                                            // would need an indicator of its own.
                                            text: modelData.megabytes === App.cacheCeiling
                                                  ? modelData.label + "   \u2713"
                                                  : modelData.label
                                            onTriggered: {
                                                App.setCacheCeiling(modelData.megabytes)
                                                ceilingMenu.dismiss()
                                            }
                                        }
                                    }
                                }
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

                        SettingsHeading { text: "Music videos on disk" }

                        Label {
                            width: parent.width
                            text: "The music player fetches a picture only while the Now "
                                  + "playing page is open, and never for anything over a "
                                  + "quarter of an hour. This is the tallest it will ask "
                                  + "for. A song offered only smaller is shown at what it "
                                  + "has, and a new ceiling takes hold at the next song."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Quality"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                id: videoCeilingButton
                                objectName: "videoCeiling"
                                text: App.videoCeilingText + "  \u25be"
                                onClicked: videoCeilingMenu.popup(videoCeilingButton, 0,
                                                                  videoCeilingButton.height + 2)

                                ThemedMenu {
                                    id: videoCeilingMenu
                                    objectName: "videoCeilingMenu"
                                    implicitWidth: 160

                                    Repeater {
                                        model: App.videoChoices

                                        ThemedMenuItem {
                                            required property var modelData

                                            // The tick marks the one in force, the same as
                                            // the picture cache's own menu does it.
                                            text: modelData.height === App.videoCeiling
                                                  ? modelData.label + "   \u2713"
                                                  : modelData.label
                                            onTriggered: {
                                                App.setVideoCeiling(modelData.height)
                                                videoCeilingMenu.dismiss()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Label {
                            width: parent.width
                            text: "A song you keep has its video written to disk the first "
                                  + "time you watch it, so every play after that starts at "
                                  + "once and pulls nothing. Only the ones you keep, and "
                                  + "only while a page is open to show a picture. The one "
                                  + "played longest ago goes first when the room runs out."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Kept"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "videosKept"
                                height: 28
                                text: App.videosKeptText
                                color: Theme.colors.text
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Ceiling"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                id: keepCeilingButton
                                objectName: "videoKeepCeiling"
                                // Written on the Python side, the same way
                                // every other sentence in this window is, so
                                // the button and the line above it cannot
                                // disagree about what a gigabyte is.
                                text: App.videoKeepCeilingText + "  \u25be"
                                onClicked: keepCeilingMenu.popup(keepCeilingButton, 0,
                                                                 keepCeilingButton.height + 2)

                                ThemedMenu {
                                    id: keepCeilingMenu
                                    objectName: "videoKeepCeilingMenu"
                                    implicitWidth: 160

                                    Repeater {
                                        model: App.videoKeepChoices

                                        ThemedMenuItem {
                                            required property var modelData

                                            text: modelData.mb === App.videoKeepCeiling
                                                  ? modelData.label + "   \u2713"
                                                  : modelData.label
                                            onTriggered: {
                                                App.setVideoKeepCeiling(modelData.mb)
                                                keepCeilingMenu.dismiss()
                                            }
                                        }
                                    }
                                }
                            }

                            FlatButton {
                                objectName: "forgetKeptVideos"
                                text: "Drop the kept videos"
                                onClicked: App.forgetKeptVideos()
                            }
                        }

                        // Videos taken out of sight from a card's own menu.
                        // Hidden is not deleted, and the list of them is a
                        // window of its own, since it grew long enough to
                        // bury every other row on this page.
                        SettingsHeading { text: "Hidden videos" }

                        Label {
                            width: parent.width
                            text: "Hiding a video takes its card out of the feed, out of a "
                                  + "group and out of the suggestions. It stays in any box "
                                  + "you put it in and it keeps whatever it was marked. The "
                                  + "window has every one of them, the one hidden last on "
                                  + "top, and a box to search them."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                objectName: "hiddenCount"
                                height: 28
                                text: App.hiddenCount === 0
                                      ? "Nothing is hidden"
                                      : App.hiddenCount + (App.hiddenCount === 1
                                                           ? " video is hidden"
                                                           : " videos are hidden")
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "openHidden"
                                // Nothing to open when nothing is hidden, and
                                // the line beside it already says so.
                                enabled: App.hiddenCount > 0
                                text: "The hidden videos"
                                onClicked: view.hiddenRequested()
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

                        SettingsHeading { text: "YouTube" }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Subscriptions"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "settingsImport"
                                text: "Import subscriptions"
                                onClicked: App.importSubscriptions()
                            }
                        }

                        Label {
                            width: parent.width
                            // Here rather than with the rest of the stored
                            // data, because which cookies the import is read
                            // with is the line under it and the two are one
                            // job.
                            text: "Importing reads the subscription list from YouTube and tracks "
                                  + "every channel in it. It is worth doing once, and again after "
                                  + "subscribing to something. It is read with the cookies below, "
                                  + "so a browser that is not signed in imports nothing."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Cookies"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                id: cookieButton
                                objectName: "cookieProfile"
                                text: App.cookieChoice + "  \u25be"
                                // Looked for again as the menu opens, so a
                                // browser signed in to a moment ago is in
                                // the list rather than after a restart.
                                onClicked: {
                                    App.refreshCookieProfiles()
                                    cookieMenu.popup(cookieButton, 0, cookieButton.height + 2)
                                }

                                ThemedMenu {
                                    id: cookieMenu
                                    objectName: "cookieProfileMenu"
                                    implicitWidth: 430

                                    Repeater {
                                        model: App.cookieChoices

                                        ThemedMenuItem {
                                            required property var modelData

                                            // The tick marks the one in
                                            // force, and the rest of the
                                            // line says whether the profile
                                            // is any use before it is picked.
                                            text: modelData.label
                                                  + (modelData.current ? "   \u2713" : "")
                                                  + (modelData.state
                                                     ? "      " + modelData.state : "")
                                            onTriggered: {
                                                App.setCookieProfile(modelData.path)
                                                cookieMenu.dismiss()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Label {
                            objectName: "cookieSource"
                            width: parent.width
                            text: App.cookieSource
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            elide: Text.ElideMiddle
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
                                  + "read from a browser profile rather than stored here. "
                                  + "Automatic prefers a profile that is signed in, and Firefox "
                                  + "forks such as Zen or Floorp are only found because this list "
                                  + "looks for them. A Google account can carry more than one "
                                  + "YouTube identity, and the music requests have to say which."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                    }
                }

                // ---- which copy this is ------------------------------------
                Rectangle {
                    width: body.width
                    height: about.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: about
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "This copy"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 20
                                text: "Running"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "runningVersion"
                                height: 20
                                text: App.version
                                color: Theme.colors.text
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Newest"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "newestVersion"
                                height: 28
                                // Three answers, and the third is the one a
                                // fresh start shows for a second or two.
                                text: App.updateVersion !== ""
                                      ? App.updateVersion + ", newer than this one"
                                      : (App.latestVersion !== ""
                                         ? App.latestVersion + ", which is this one"
                                         : "not asked yet")
                                color: App.updateVersion !== "" ? Theme.colors.accent
                                                                : Theme.colors.text
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "openRelease"
                                text: "The release page"
                                enabled: App.hasRelease
                                onClicked: App.openRelease()
                            }
                        }

                        Label {
                            width: parent.width
                            text: "The repository is asked once a day whether a newer release has "
                                  + "been published. Nothing is downloaded and nothing is sent but "
                                  + "the question."
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
