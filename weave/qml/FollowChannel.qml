import QtQuick
import QtQuick.Controls

// Following a channel by name, which used to be a box in the toolbar beside
// the search box. Two boxes side by side asked people to know the difference
// before they had used either, so this one moved to the plus above the list it
// adds to, and the toolbar keeps the one that searches.
Popup {
    id: root
    objectName: "followChannel"

    anchors.centerIn: parent
    width: 380
    padding: 16
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: 8
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border
    }

    onOpened: {
        App.clearAddState()
        field.text = ""
        field.forceActiveFocus()
    }

    Column {
        width: parent.width
        spacing: 10

        Label {
            text: "Follow a channel"
            color: Theme.colors.text
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }

        Label {
            width: parent.width
            text: "A channel id, an @handle, a channel address or a twitch.tv link. "
                  + "It goes into All, and its videos arrive with the next refresh."
            color: Theme.colors.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }

        TextField {
            id: field
            objectName: "followField"
            width: parent.width
            placeholderText: "Add a channel, a handle or a twitch.tv link"
            color: Theme.colors.text
            placeholderTextColor: Theme.colors.textMuted
            background: Rectangle {
                radius: 6
                color: Theme.colors.background
                border.width: 1
                border.color: field.activeFocus ? Theme.colors.accent : Theme.colors.border
            }
            // The text is kept on a reference that was not understood, so a
            // typo can be corrected rather than retyped.
            onAccepted: {
                if (App.addChannel(text))
                    text = ""
            }
            onTextEdited: App.clearAddState()
        }

        // Whether that worked, said here rather than in the corner of a bar
        // this window is drawn over.
        Label {
            objectName: "followAnswer"
            width: parent.width
            visible: App.addMessage !== ""
            text: App.addMessage
            color: App.addState === "failed" ? Theme.colors.error
                                             : (App.addState === "added" ? Theme.colors.accent
                                                                         : Theme.colors.textMuted)
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }

        Row {
            spacing: 8
            anchors.right: parent.right

            FlatButton {
                text: "Done"
                onClicked: root.close()
            }

            FlatButton {
                objectName: "followAdd"
                text: "Follow"
                accent: true
                onClicked: {
                    if (App.addChannel(field.text))
                        field.text = ""
                }
            }
        }
    }
}
