import QtQuick
import QtQuick.Controls

// The pages a fresh install is walked through.
//
// Four of them, counted from zero, so the number reads as how far there is to
// go rather than as a page number. Two of them offer the two things a new copy
// cannot do anything without, the subscription list and Twitch, and the other
// two say what this is and how it is used.
//
// It stops appearing on its own once both of those are done, so the box in the
// corner is for somebody who wants it gone before that.
Popup {
    id: root
    objectName: "wizard"

    readonly property int last: 6
    readonly property int step: App.wizardStep
    // The page that asks where videos play.
    readonly property int videosStep: 5

    readonly property real roomWidth: parent ? parent.width : 640
    readonly property real roomHeight: parent ? parent.height : 620
    width: Math.min(600, roomWidth - 80)
    // As tall as the page in it and no taller, so no page stands half empty
    // beside the one with two pictures on it. One size for all of them left
    // every words page with a hole under its words.
    readonly property real wantedHeight: page.implicitHeight + page.anchors.bottomMargin
                                         + footer.height + topPadding + bottomPadding
    height: Math.min(roomHeight - 60, Math.ceil(wantedHeight))
    // The bottom edge stays where it is and the top moves, so Back and Next
    // stay under the hand from page to page however long the words are.
    readonly property real bottomEdge: Math.min(roomHeight - 30, Math.round((roomHeight + 370) / 2))
    x: Math.round((roomWidth - width) / 2)
    y: Math.max(30, bottomEdge - height)
    Behavior on height {
        enabled: root.opened
        NumberAnimation { duration: 200; easing.type: Easing.OutCubic }
    }
    padding: 20
    focus: true
    // Not modal, and dimmed by a rectangle of the window's own rather than by
    // the overlay a modal popup brings. A modal overlay swallows every press
    // that is not on the card, which in a window with no frame of its own
    // means the window can no longer be moved or resized while these are open.
    // The cross closes them, so nothing here is a trap.
    modal: false
    dim: false
    closePolicy: Popup.CloseOnEscape

    // A Popup owns its own visible, so binding that to the window's answer is
    // a binding loop, and a loop here left the card drawn over everything at
    // startup. It is opened and closed from the change instead.
    onClosed: App.closeWizard()

    Connections {
        target: App
        function onWizardChanged() {
            if (App.wizardOpen && !root.opened)
                root.open()
            else if (!App.wizardOpen && root.opened)
                root.close()
        }
    }

    background: Rectangle {
        radius: 10
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border
    }

    // One way a video can play: what happens, drawn, and who it suits. The
    // whole card is the button, the way a picture of the thing is easier to
    // choose by than its name.
    component PlaceChoice: Rectangle {
        id: choice
        property string place: "weave"
        property string name: ""
        property string words: ""
        property bool chosen: false
        property bool offered: true
        property string refusal: ""
        signal picked()

        radius: 8
        color: chosen ? Theme.washOver(Theme.colors.accent, 0.1, Theme.colors.surfaceRaised)
                      : "transparent"
        border.width: chosen ? 2 : 1
        border.color: chosen ? Theme.colors.accent
                             : (pointing.hovered ? Theme.colors.textMuted : Theme.colors.border)
        opacity: offered ? 1 : 0.5

        VideoPlaceScene {
            id: picture
            x: 10
            y: 10
            width: parent.width - 20
            height: 150
            place: choice.place
            running: root.opened && root.step === root.videosStep && choice.offered
        }

        Label {
            id: placeName
            x: 14
            y: picture.y + picture.height + 16
            text: choice.name
            color: Theme.colors.text
            font.pixelSize: 15
            font.weight: Font.DemiBold
        }

        Label {
            x: 14
            anchors.top: placeName.bottom
            anchors.topMargin: 6
            width: parent.width - 28
            text: choice.offered ? choice.words : choice.refusal
            color: Theme.colors.text
            font.pixelSize: 12
            lineHeight: 1.35
            wrapMode: Text.Wrap
        }

        HoverHandler {
            id: pointing
            enabled: choice.offered
            cursorShape: Qt.PointingHandCursor
        }
        // Kept to itself. A handler shares a press with every handler under
        // it, and under this card are the cards of the feed, which played.
        TapHandler {
            enabled: choice.offered
            gesturePolicy: TapHandler.ReleaseWithinBounds
            onTapped: choice.picked()
        }
    }

    // ---- the pages ------------------------------------------------------

    Item {
        anchors.fill: parent

        // The way out for somebody who wants none of this. A press outside no
        // longer closes them, so there has to be one.
        FlatButton {
            id: closeMark
            objectName: "wizardClose"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: -6
            anchors.rightMargin: -6
            width: 28
            text: "\u2715"
            onClicked: root.close()
        }

        Label {
            id: counter
            anchors.right: closeMark.left
            anchors.rightMargin: 10
            anchors.top: parent.top
            text: root.step + " of " + root.last
            color: Theme.colors.textMuted
            font.pixelSize: 12
        }

        Column {
            id: page
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: footer.top
            anchors.bottomMargin: 14
            spacing: 10
            // While the card is still growing to a taller page, what does not
            // fit yet is hidden rather than drawn over the buttons.
            clip: true

            Label {
                objectName: "wizardTitle"
                // Clear of the count and the cross beside it.
                width: parent.width - 90
                text: [
                    "Welcome to Weave",
                    "Your subscriptions",
                    "Twitch",
                    "Search suggestions",
                    "How it looks",
                    "How videos play",
                    "How it is used",
                ][root.step]
                color: Theme.colors.text
                font.pixelSize: 20
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }

            Label {
                objectName: "wizardBody"
                width: parent.width
                text: [
                    "This is your subscriptions first. "
                        + (App.videosInWeave ? "Every video plays on a page of its own, "
                                               + "right here in the window. "
                                             : "Every video opens in mpv rather than in a page. ")
                        + "These few pages are only the parts worth knowing before you "
                        + "start. There is a good deal more in here than they cover, and the "
                        + "rest is worth finding as you go. None of it is final either, and "
                        + "the Getting started button on the settings page opens these pages "
                        + "again whenever you want them.",
                    "Weave builds its feed from each channel's own feed, so it has to know "
                        + "which channels are yours. Importing reads that list from YouTube "
                        + "once and follows every channel in it. Nothing is written back to "
                        + "your account, here or anywhere else in this application.",
                    "Connecting Twitch puts whoever is live at the top of the window, beside "
                        + "the YouTube streams. It asks for no password: a page opens in your "
                        + "browser with a code already filled in, and you approve it there. "
                        + "This one is optional, and skipping it costs you only the live bar.",
                    "While you type a search, what you have typed so far is sent to YouTube "
                        + "after each pause, and a list under the box shows what it suggests. "
                        + "Anonymous sends the words alone. From your account sends them with "
                        + "your login, so the suggestions follow what you watch and YouTube "
                        + "knows who is typing. The settings page changes this later.",
                    "Press one and the whole window changes at once, so try them until "
                        + "one of them looks right. Whichever is on when you leave this page "
                        + "is the one you keep. The settings page can also make one of your "
                        + "own from a colour wheel.",
                    "A video can open in mpv, in a window of its own, or right here on a "
                        + "page of its own like the music. Press the one you want. The settings "
                        + "page changes it later, and a right click on any card plays that one "
                        + "video the other way.",
                    (App.videosInWeave ? "Press a card to watch it on its own page. "
                                       : "Press a card to watch it in mpv. ")
                        + "The headphone on a card listens without "
                        + "a window. A group holds channels you pick, a box holds videos you "
                        + "pick, and both live in the panel on the left. Right click a card "
                        + "for everything else, and the settings page holds the rest.",
                ][root.step]
                color: Theme.colors.textMuted
                font.pixelSize: 14
                lineHeight: 1.3
                wrapMode: Text.Wrap
            }

            Label {
                objectName: "wizardFarewell"
                visible: root.step === root.last
                width: parent.width
                text: "That is all of it. Have fun with Weave."
                color: Theme.colors.accent
                font.pixelSize: 14
                wrapMode: Text.Wrap
            }

            // ---- where videos play, shown rather than described
            Item {
                objectName: "wizardVideoPlaces"
                visible: root.step === root.videosStep
                width: page.width
                height: 320

                PlaceChoice {
                    objectName: "wizardInMpv"
                    width: (parent.width - 16) / 2
                    height: parent.height
                    place: "mpv"
                    name: "In mpv"
                    words: "Your own mpv opens in its own window, with your mpv.conf, your "
                           + "scripts and your keys. For people with their own mpv setup, or a "
                           + "second screen."
                    chosen: !App.videosInWeave
                    offered: App.mpvFound
                    refusal: "mpv is not installed on this machine. Once it is, this can be "
                             + "picked here or on the settings page."
                    onPicked: App.setVideosInWeave(false)
                }

                PlaceChoice {
                    objectName: "wizardInWeave"
                    x: parent.width - width
                    width: (parent.width - 16) / 2
                    height: parent.height
                    place: "weave"
                    name: "In Weave"
                    words: "The video plays on a page in this window, with recommendations, "
                           + "comments and a stream's chat beside it. For one screen."
                    chosen: App.videosInWeave
                    onPicked: App.setVideosInWeave(true)
                }
            }

            // ---- page 1, the subscription list
            // Which browser first, since the import is read with its cookies
            // and the wrong one is the usual reason it comes back empty.
            Row {
                visible: root.step === 1
                spacing: 8

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Cookies"
                    color: Theme.colors.textMuted
                    font.pixelSize: 13
                }

                FlatButton {
                    id: wizardCookieButton
                    objectName: "wizardCookieProfile"
                    text: App.cookieChoice + "  \u25be"
                    onClicked: {
                        App.refreshCookieProfiles()
                        wizardCookieMenu.popup(wizardCookieButton, 0,
                                               wizardCookieButton.height + 2)
                    }

                    ThemedMenu {
                        id: wizardCookieMenu
                        objectName: "wizardCookieMenu"
                        implicitWidth: 430

                        Repeater {
                            model: App.cookieChoices

                            ThemedMenuItem {
                                required property var modelData

                                text: modelData.label
                                      + (modelData.current ? "   \u2713" : "")
                                      + (modelData.state ? "      " + modelData.state : "")
                                onTriggered: {
                                    App.setCookieProfile(modelData.path)
                                    wizardCookieMenu.dismiss()
                                }
                            }
                        }
                    }
                }
            }

            Row {
                visible: root.step === 1
                spacing: 8

                FlatButton {
                    id: importButton
                    objectName: "wizardImport"
                    text: App.importState === "done" ? "Import again" : "Import subscriptions"
                    accent: App.importState !== "done"
                    enabled: App.importState !== "working"
                    onClicked: App.importSubscriptions()
                }

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    objectName: "wizardImportState"
                    // Whatever yt-dlp said, which can be a sentence.
                    width: Math.max(0, page.width - importButton.width - 8)
                    text: App.importMessage
                    color: App.importState === "failed" ? Theme.colors.error : Theme.colors.text
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
            }

            Label {
                visible: root.step === 1
                width: parent.width
                // The cookie source, always, because it is what the import
                // needs rather than something to look at once it has gone
                // wrong. A failure adds the reason underneath.
                text: App.importState === "failed"
                      ? "The list is read with the cookies of a browser profile signed in to "
                        + "YouTube. Weave is reading " + App.cookieSource + ". If that is the "
                        + "wrong browser, pick another one above. If that profile is signed "
                        + "out, or the browser is holding the file open, the import fails "
                        + "exactly like this. Sign in there, close the browser and try again."
                      : "Read with the cookies of " + App.cookieSource
                color: App.importState === "failed" ? Theme.colors.text : Theme.colors.textMuted
                font.pixelSize: 12
                lineHeight: 1.3
                wrapMode: Text.Wrap
            }

            // ---- page 3, the themes, tried rather than described
            // Bounded and scrolling, because this list is as long as the
            // themes directory and a card of one size cannot grow with it.
            Flickable {
                objectName: "wizardThemes"
                visible: root.step === 4
                width: parent.width
                height: Math.min(themeFlow.implicitHeight, 140)
                contentHeight: themeFlow.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height

                Flow {
                    id: themeFlow
                    width: parent.width
                    spacing: 6

                    Repeater {
                        model: Theme.names

                        FlatButton {
                            required property int index
                            required property var modelData

                            objectName: "wizardTheme" + index
                            text: modelData
                            accent: modelData === Theme.current
                            // Nothing is remembered here beyond what the
                            // window already does. Choosing one is choosing it.
                            onClicked: Theme.select(modelData)
                        }
                    }
                }
            }

            // ---- page 3, where the suggestions come from
            Row {
                visible: root.step === 3
                spacing: 8

                FlatButton {
                    objectName: "wizardSuggestAnonymous"
                    text: "Anonymous"
                    accent: !App.suggestFromAccount
                    onClicked: App.setSuggestFromAccount(false)
                }

                FlatButton {
                    objectName: "wizardSuggestAccount"
                    text: "From your account"
                    accent: App.suggestFromAccount
                    onClicked: App.setSuggestFromAccount(true)
                }
            }

            // ---- page 2, Twitch
            Row {
                visible: root.step === 2
                spacing: 8

                FlatButton {
                    objectName: "wizardTwitch"
                    text: App.twitchConnected ? "Connect again" : "Connect Twitch"
                    accent: !App.twitchConnected
                    onClicked: App.connectTwitch()
                }

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    objectName: "wizardTwitchState"
                    text: App.twitchStatus !== "" ? App.twitchStatus
                                                  : (App.twitchConnected ? "connected"
                                                                         : "not connected")
                    color: Theme.colors.text
                    font.pixelSize: 13
                }
            }
        }

        // ---- what carries you through them ------------------------------

        Item {
            id: footer
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 28

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                // Drawn here rather than left to the control. The box this
                // style ships is a white square, which on a dark card is the
                // brightest thing in the window and reads as a warning.
                CheckBox {
                    id: hideBox
                    objectName: "wizardHide"
                    anchors.verticalCenter: parent.verticalCenter
                    checked: App.wizardHidden
                    onToggled: App.setWizardHidden(checked)

                    indicator: Rectangle {
                        implicitWidth: 16
                        implicitHeight: 16
                        x: hideBox.leftPadding
                        y: (hideBox.height - height) / 2
                        radius: 4
                        color: hideBox.checked ? Theme.colors.accent : "transparent"
                        border.width: 1
                        border.color: hideBox.checked ? Theme.colors.accent
                                                      : (hideBox.hovered ? Theme.colors.text
                                                                         : Theme.colors.border)

                        Label {
                            anchors.centerIn: parent
                            visible: hideBox.checked
                            text: "\u2713"
                            color: Theme.colors.badgeText
                            font.pixelSize: 11
                        }
                    }
                }

                // The box draws no text of its own in this style, so the words
                // are a label beside it.
                Label {
                    objectName: "wizardHideWords"
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Do not show this again"
                    color: Theme.colors.textMuted
                    font.pixelSize: 13

                    // The words are as much of the control as the box is. An
                    // area rather than a handler: a handler shares the press
                    // with the card under the pages, which played, and one
                    // told to keep it never fires on words at all.
                    MouseArea {
                        anchors.fill: parent
                        onClicked: App.setWizardHidden(!App.wizardHidden)
                    }
                }
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                FlatButton {
                    objectName: "wizardBack"
                    text: "Back"
                    enabled: root.step > 0
                    onClicked: App.stepWizard(-1)
                }

                FlatButton {
                    objectName: "wizardNext"
                    text: root.step === root.last ? "Done" : "Next"
                    accent: true
                    onClicked: {
                        if (root.step === root.last)
                            root.close()
                        else
                            App.stepWizard(1)
                    }
                }
            }
        }
    }
}
