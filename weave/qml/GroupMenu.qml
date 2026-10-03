import QtQuick
import QtQuick.Controls

// The groups a channel can go in, drawn the way the boxes are: ticked where
// the channel is already, and pressing a ticked one takes it out again. A
// menu inside a video's menu, and on its own beside a channel's page.
ThemedMenu {
    id: groups
    title: "Put channel in a group"

    // The channel, by its key.
    property string key: ""
    // Whether the entry that opens this menu is shown at all.
    property bool offered: true
    // Which groups hold the channel, asked when the menu opens.
    property var holding: []
    // The menu this one opens from, closed with it once a group is picked.
    property var owner: null

    signal newGroupWanted(string key)

    implicitWidth: 220

    function dismissAll() {
        groups.dismiss()
        if (groups.owner)
            groups.owner.dismiss()
    }

    Instantiator {
        // All is offered like any other list. It is not a row in the groups
        // table, but it holds channels in the sense this menu is asking
        // about, and a channel followed here has every reason to sit beside
        // a subscribed one.
        model: App.groups
        // A delegate made here does not inherit this file's ids, so the menu
        // is handed to each entry from out here.
        onObjectAdded: (index, object) => {
            object.picker = groups
            groups.insertItem(index, object)
        }
        onObjectRemoved: (index, object) => groups.removeItem(object)
        delegate: ThemedMenuItem {
            required property var modelData
            property var picker: null
            objectName: "groupEntry"
            text: (picker && picker.holding.indexOf(modelData.id) >= 0 ? "✓  " : "     ")
                  + modelData.name
            onTriggered: {
                if (!picker)
                    return
                if (picker.holding.indexOf(modelData.id) >= 0)
                    App.removeChannelFromGroup(modelData.id, picker.key)
                else
                    App.addChannelToGroup(modelData.id, picker.key)
                picker.dismissAll()
            }
        }
    }

    ThemedMenuSeparator {}

    ThemedMenuItem {
        objectName: "groupNew"
        text: "     New group…"
        onTriggered: {
            groups.newGroupWanted(groups.key)
            groups.dismissAll()
        }
    }
}
