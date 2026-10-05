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
    // SponsorBlock's kinds carry a dot before their names and the longest
    // name is two words, so its part of the card takes a little more.
    readonly property int kindWidth: wordWidth + 24

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

                // ---- where videos play ---------------------------------------
                // First, because it decides what pressing anything does.
                Rectangle {
                    objectName: "videosCard"
                    width: body.width
                    height: videosBody.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: videosBody
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "Videos"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Videos play in"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "videosInMpv"
                                text: "In mpv"
                                accent: !App.videosInWeave
                                enabled: App.mpvFound
                                onClicked: App.setVideosInWeave(false)
                            }

                            FlatButton {
                                objectName: "videosInWeave"
                                text: "In Weave"
                                accent: App.videosInWeave
                                onClicked: App.setVideosInWeave(true)
                            }
                        }

                        Label {
                            objectName: "videosWords"
                            width: parent.width
                            text: "In mpv hands every video and stream to your own mpv, in a window "
                                  + "of its own, with your mpv.conf, your scripts and your keys. That "
                                  + "suits an mpv set up the way you like it, or a second screen. In "
                                  + "Weave plays it on a page in this window, the way the music plays, "
                                  + "with the queue beside it. A right click on any card plays that "
                                  + "one video the other way without changing this."
                                  + (App.mpvFound ? "" : " mpv is not installed on this machine, "
                                                         + "so for now they play in Weave.")
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        // What a video played here is fetched at, and whether it
                        // has captions. Only for the window's own player: mpv
                        // goes by its own configuration.
                        Row {
                            objectName: "videoQualityRow"
                            visible: App.videosInWeave
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Quality"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Repeater {
                                model: [0, 2160, 1440, 1080, 720, 480]

                                FlatButton {
                                    required property int modelData
                                    objectName: "videoQuality_" + modelData
                                    text: modelData ? modelData + "p"
                                                    : "Auto (up to " + Video.autoHeight + "p)"
                                    accent: Video.quality === modelData
                                    onClicked: Video.setQuality(modelData)
                                }
                            }
                        }

                        Label {
                            visible: App.videosInWeave
                            width: parent.width
                            text: "Auto follows the screen the window is on. A height picked here "
                                  + "or in the player stays until Auto is picked again. A "
                                  + "YouTube Premium account gets Premium quality wherever a "
                                  + "video has it."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            objectName: "videoCaptionsRow"
                            visible: App.videosInWeave
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Captions"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "videoCaptionsOff"
                                text: "Off"
                                accent: !Video.captionsOn
                                onClicked: Video.setCaptionsOn(false)
                            }

                            FlatButton {
                                objectName: "videoCaptionsOn"
                                text: "On"
                                accent: Video.captionsOn
                                onClicked: Video.setCaptionsOn(true)
                            }
                        }

                        Label {
                            visible: App.videosInWeave
                            width: parent.width
                            text: "On shows them in the language last picked with CC on a video, "
                                  + "the uploader's own before YouTube's, and otherwise in the "
                                  + "video's own language."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        SettingsHeading {
                            visible: App.videosInWeave
                            text: "SponsorBlock"
                        }

                        Row {
                            objectName: "sponsorRow"
                            visible: App.videosInWeave
                            spacing: 8

                            Label {
                                width: view.kindWidth
                                height: 28
                                text: "SponsorBlock"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "sponsorOff"
                                text: "Off"
                                accent: !Video.sponsorOn
                                onClicked: Video.setSponsorBlock(false)
                            }

                            FlatButton {
                                objectName: "sponsorOn"
                                text: "On"
                                accent: Video.sponsorOn
                                onClicked: Video.setSponsorBlock(true)
                            }
                        }

                        // The credit its licence asks for, and what is sent.
                        Label {
                            objectName: "sponsorWords"
                            visible: App.videosInWeave
                            width: parent.width
                            text: "Skips or marks the parts of a video other viewers have marked, "
                                  + "such as a sponsor or an intro. Weave sends SponsorBlock only "
                                  + "the first four characters of a hash of the video's id, so it "
                                  + "never learns which video you watch. The segments come from "
                                  + "SponsorBlock (sponsor.ajay.app) and are shared under "
                                  + "CC BY-NC-SA 4.0."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        // Each kind, only while it is on: skipped, offered with a
                        // button, or left alone.
                        Repeater {
                            model: Video.sponsorCategories

                            Row {
                                id: kindRow
                                required property var modelData
                                objectName: "sponsorKind_" + modelData.key
                                visible: App.videosInWeave && Video.sponsorOn
                                spacing: 8

                                Item {
                                    width: view.kindWidth
                                    height: 28

                                    Rectangle {
                                        id: kindDot
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 8
                                        height: 8
                                        radius: 4
                                        color: kindRow.modelData.colour
                                    }
                                    Label {
                                        anchors.left: kindDot.right
                                        anchors.leftMargin: 8
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: kindRow.modelData.label
                                        elide: Text.ElideRight
                                        color: Theme.colors.textMuted
                                        font.pixelSize: 12
                                    }
                                }

                                Repeater {
                                    model: [{ action: "skip", label: "Skip" },
                                            { action: "button", label: "Button" },
                                            { action: "ignore", label: "Ignore" }]

                                    FlatButton {
                                        required property var modelData
                                        objectName: "sponsor_" + kindRow.modelData.key + "_"
                                                    + modelData.action
                                        text: modelData.label
                                        accent: kindRow.modelData.action === modelData.action
                                        onClicked: Video.setSegmentAction(kindRow.modelData.key,
                                                                          modelData.action)
                                    }
                                }
                            }
                        }
                    }
                }

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

                        SettingsHeading { text: "Music" }

                        Label {
                            width: parent.width
                            text: "The music page has settings of its own: its shelves, your "
                                  + "boxes of songs, which of them are kept on disk, and what "
                                  + "is told to YouTube Music. They open from the \u22ef beside "
                                  + "Music in the sidebar, or from here."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        FlatButton {
                            objectName: "settingsMusic"
                            text: "Music settings"
                            onClicked: App.showMusicSettings()
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


                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Search suggestions"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "suggestAnonymous"
                                text: "Anonymous"
                                accent: !App.suggestFromAccount
                                onClicked: App.setSuggestFromAccount(false)
                            }

                            FlatButton {
                                objectName: "suggestFromAccount"
                                text: "From your account"
                                accent: App.suggestFromAccount
                                onClicked: App.setSuggestFromAccount(true)
                            }
                        }

                        // What each one sends, since the account one sends every
                        // pause in the typing along with who is typing.
                        Label {
                            objectName: "suggestWords"
                            width: parent.width
                            text: "While you type in a search box, what you have typed so far is "
                                  + "sent to YouTube after each pause, the way its own search box "
                                  + "does, and the list under the box shows what it suggests. "
                                  + "Anonymous sends the words alone, so the suggestions are the "
                                  + "ones anybody would get. From your account sends them with "
                                  + "your login, so the suggestions follow what you watch, and "
                                  + "YouTube knows who is typing them."
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
                                // Newer, older, the same, or not asked yet.
                                text: App.newestWords
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
