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

    readonly property int last: 4
    readonly property int step: App.wizardStep

    anchors.centerIn: parent
    width: Math.min(560, (parent ? parent.width : 600) - 80)
    // One size for all four, so the buttons stay under the hand from page to
    // page instead of moving with the length of the words. Tall enough for the
    // longest of them, which is the subscription page once an import has
    // failed and the card has to explain why.
    // 370 measured against the longest page, which needs 278 of the 296 this
    // leaves it. Anything less clips the explanation of a failed import.
    height: Math.min((parent ? parent.height : 500) - 60, 370)
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
            anchors.rightMargin: 40
            spacing: 10

            Label {
                objectName: "wizardTitle"
                width: parent.width
                text: [
                    "Welcome to Weave",
                    "Your subscriptions",
                    "Twitch",
                    "How it looks",
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
                    "This is your subscriptions first. Nothing is put in front of them, "
                        + "what YouTube suggests waits on a page of its own until you go "
                        + "looking for it, and every video opens in mpv rather than in a "
                        + "page. These few pages are only the parts worth knowing before you "
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
                    "Press one and the whole window changes at once, so try them until "
                        + "one of them looks right. Whichever is on when you leave this page "
                        + "is the one you keep. The settings page can also make one of your "
                        + "own from a colour wheel.",
                    "Press a card to watch it in mpv. The headphone on a card listens without "
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

            // ---- page 1, the subscription list
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
                        + "YouTube. Weave is reading " + App.cookieSource + ". If that profile "
                        + "is signed out, or the browser is holding the file open, the import "
                        + "fails exactly like this. Sign in there, close the browser and try "
                        + "again."
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
                visible: root.step === 3
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
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Do not show this again"
                    color: Theme.colors.textMuted
                    font.pixelSize: 13

                    // The words are as much of the control as the box is.
                    TapHandler { onTapped: App.setWizardHidden(!App.wizardHidden) }
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
