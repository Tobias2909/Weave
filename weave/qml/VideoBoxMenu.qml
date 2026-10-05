import QtQuick
import QtQuick.Controls

// The boxes a video can go in, as a menu inside a video's own menu, drawn the
// way the boxes of songs are. Ticked where the video is already, and pressing
// a ticked one takes it out again, which is what the tick says it would do.
ThemedMenu {
    id: boxes
    title: "Put in a box"

    // The video, by its key.
    property string key: ""
    // Whether the entry that opens this menu is shown at all.
    property bool offered: true
    // Which boxes hold the video, asked when the video's menu opens.
    property var holding: []
    // The menu this one opens from, closed with it once a box is picked.
    property var owner: null

    signal newBoxWanted(string key)

    implicitWidth: 220

    function dismissAll() {
        boxes.dismiss()
        if (boxes.owner)
            boxes.owner.dismiss()
    }

    // A press on the entry that opens this menu, rather than resting on it,
    // is the quick way: into the first box, or out of it again when the video
    // is in it already. With no box yet there is nothing quick to do, so the
    // menu opens instead, with its New box.
    readonly property bool quickPick: true
    function takeQuickPick() {
        var first = App.boxes.length > 0 ? App.boxes[0] : null
        if (!first) {
            boxes.open()
            return
        }
        if (boxes.holding.indexOf(first.id) >= 0)
            App.removeFromBox(first.id, boxes.key)
        else
            App.addToBox(first.id, boxes.key)
        boxes.dismissAll()
    }

    Instantiator {
        model: App.boxes
        // A delegate made here does not inherit this file's ids, so the menu
        // is handed to each entry from out here.
        onObjectAdded: (index, object) => {
            object.picker = boxes
            boxes.insertItem(index, object)
        }
        onObjectRemoved: (index, object) => boxes.removeItem(object)
        delegate: ThemedMenuItem {
            required property var modelData
            property var picker: null
            objectName: "videoBoxEntry"
            text: (picker && picker.holding.indexOf(modelData.id) >= 0 ? "✓  " : "     ")
                  + modelData.name
            onTriggered: {
                if (!picker)
                    return
                if (picker.holding.indexOf(modelData.id) >= 0)
                    App.removeFromBox(modelData.id, picker.key)
                else
                    App.addToBox(modelData.id, picker.key)
                picker.dismissAll()
            }
        }
    }

    ThemedMenuSeparator {}

    ThemedMenuItem {
        objectName: "videoBoxNew"
        text: "     New box…"
        onTriggered: {
            boxes.newBoxWanted(boxes.key)
            boxes.dismissAll()
        }
    }
}
