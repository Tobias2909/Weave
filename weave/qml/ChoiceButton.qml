import QtQuick
import QtQuick.Controls

// A button that names the choice in force and opens a menu of the others.
// Lit in the accent while the choice is anything but the usual one, so a
// narrowed list says so before anything in it is read.
FlatButton {
    id: chooser

    // Each choice is { value, label }.
    property var choices: []
    property string current: ""
    // The usual choice, drawn plainly.
    property string usual: ""
    signal chosen(string value)

    function labelOf(value) {
        for (var i = 0; i < choices.length; i++)
            if (choices[i].value === value) return choices[i].label
        return value
    }

    text: labelOf(current) + "  ▾"
    accent: current !== usual
    onClicked: choiceMenu.popup(chooser, 0, chooser.height + 4)

    ThemedMenu {
        id: choiceMenu
        objectName: chooser.objectName + "Menu"

        Instantiator {
            model: chooser.choices
            // A delegate made here does not inherit this file's ids, so the
            // menu and the button are handed to each entry from out here.
            onObjectAdded: (index, object) => {
                object.owner = choiceMenu
                object.picker = chooser
                choiceMenu.insertItem(index, object)
            }
            onObjectRemoved: (index, object) => choiceMenu.removeItem(object)
            delegate: ThemedMenuItem {
                required property var modelData
                property var owner: null
                property var picker: null
                text: (picker && picker.current === modelData.value ? "✓  " : "    ")
                      + modelData.label
                onTriggered: {
                    if (picker)
                        picker.chosen(modelData.value)
                    if (owner)
                        owner.dismiss()
                }
            }
        }
    }
}
