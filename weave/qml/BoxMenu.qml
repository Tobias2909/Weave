import QtQuick
import QtQuick.Controls

// The boxes a song can go in, as a menu inside a song's own menu. Ticked
// where the song is already, and pressing a ticked one takes it out again,
// which is what the tick says it would do.
ThemedMenu {
    id: boxes
    title: "Put in a box"

    // Where the song was pressed and which one, as the window says it to
    // App.putSongInBox: a tile on a shelf, a row of an opened list, a song on
    // an artist's page.
    property string where: ""
    property int first: -1
    property int second: -1
    // Which boxes hold the song, asked when the song's menu opens.
    property var holding: []
    // The menu this one opens from, closed with it once a box is picked.
    property var owner: null

    signal newBoxWanted(var song)

    implicitWidth: 220

    function dismissAll() {
        boxes.dismiss()
        if (boxes.owner)
            boxes.owner.dismiss()
    }

    Instantiator {
        model: App.musicBoxes
        // A delegate made here does not inherit this file's ids, so the menu
        // is handed to each entry from out here, the way ChoiceButton does it.
        onObjectAdded: (index, object) => {
            object.picker = boxes
            boxes.insertItem(index, object)
        }
        onObjectRemoved: (index, object) => boxes.removeItem(object)
        delegate: ThemedMenuItem {
            required property var modelData
            property var picker: null
            objectName: "boxMenuEntry"
            text: (picker && picker.holding.indexOf(modelData.id) >= 0 ? "✓  " : "     ")
                  + modelData.name
            onTriggered: {
                if (!picker)
                    return
                App.putSongInBox(picker.where, picker.first, picker.second, modelData.id)
                picker.dismissAll()
            }
        }
    }

    ThemedMenuSeparator {}

    ThemedMenuItem {
        objectName: "boxMenuNew"
        text: "     New box…"
        onTriggered: {
            boxes.newBoxWanted({"where": boxes.where, "first": boxes.first,
                                "second": boxes.second})
            boxes.dismissAll()
        }
    }
}
