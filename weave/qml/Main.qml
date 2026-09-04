import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    visible: true
    width: 1400
    height: 900
    minimumWidth: 760
    minimumHeight: 520
    title: App.viewKind === "channel" && App.channelInfo.title
           ? "Weave  ·  " + App.channelInfo.title : "Weave"
    color: Theme.colors.background

    ThemeBackground {
        anchors.fill: parent
        z: -1
    }

    // Which video the context menu is acting on.
    property string menuKey: ""
    property string menuChannelKey: ""
    property bool menuWatched: false

    // The name popup serves boxes and groups alike, so it carries which of
    // the two it is acting on. The key is the video for a box and the channel
    // for a group, and is empty when the popup was opened from the sidebar
    // rather than from something being filed.
    property string namingKind: "box"
    property int namingId: -1
    property string namingKey: ""

    // Keeps a newly selected sidebar row on screen once the list is longer
    // than the sidebar.
    function revealRow(item) {
        var top = item.mapToItem(sidebarColumn, 0, 0).y
        var bottom = top + item.height
        if (top < sidebarFlick.contentY)
            sidebarFlick.contentY = Math.max(0, top)
        else if (bottom > sidebarFlick.contentY + sidebarFlick.height)
            sidebarFlick.contentY = bottom - sidebarFlick.height
    }

    function askForName(kind, id, key, current) {
        root.namingKind = kind
        root.namingId = id
        root.namingKey = key
        nameField.text = current
        namePopup.open()
        nameField.forceActiveFocus()
        nameField.selectAll()
    }

    // Opens the tick list of groups for one channel, from wherever a channel
    // is on screen.
    function askForGroups(channelKey) {
        if (!channelKey)
            return
        channelGroupMenu.channelKey = channelKey
        channelGroupMenu.popup()
    }

    // A panel over a gradient is translucent, otherwise the bars would cover
    // the corner the light comes from and the wash would never be seen.
    readonly property real panelOpacity: Theme.washed ? 0.62 : 1.0
    function panelColour(role) {
        return Qt.rgba(role.r, role.g, role.b, root.panelOpacity)
    }

    header: ToolBar {
        background: Rectangle {
            color: root.panelColour(Theme.colors.surface)
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.colors.border
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 12

            Label {
                text: "Weave"
                color: Theme.colors.text
                font.pixelSize: 18
                font.weight: Font.Bold
            }

            TextField {
                id: addField
                Layout.preferredWidth: 260
                placeholderText: "Add a channel, a handle or a twitch.tv link"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: addField.activeFocus ? Theme.colors.accent : Theme.colors.border
                }
                onAccepted: {
                    // Keep the text when it was not even understood, so a typo
                    // can be corrected rather than retyped.
                    if (App.addChannel(text))
                        text = ""
                }
            }

            TextField {
                id: searchField
                objectName: "searchField"
                Layout.preferredWidth: 220
                placeholderText: "Search what is stored"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: searchField.activeFocus ? Theme.colors.accent
                                                          : Theme.colors.border
                }
                // Live, because the whole search is one query over the local
                // database and costs nothing. Emptying it goes back to
                // wherever the search started.
                onTextChanged: App.search(text)
                Keys.onEscapePressed: text = ""
            }

            FlatButton {
                // The history is only worth importing once, so it lives with
                // the view it fills rather than in the bar all the time.
                visible: App.viewKind === "history"
                text: "Import from YouTube"
                onClicked: App.importHistory()
            }

            FlatButton {
                visible: App.viewKind === "recommended"
                text: "Ask again"
                onClicked: App.refreshRecommended()
            }

            FlatButton {
                visible: App.viewKind === "playlist"
                text: "Read it again"
                onClicked: App.refreshPlaylist()
            }

            FlatButton {
                text: "Import subscriptions"
                onClicked: App.importSubscriptions()
            }

            FlatButton {
                text: Theme.current
                onClicked: themeMenu.popup()
            }

            Item { Layout.fillWidth: true }

            Label {
                text: App.status
                color: Theme.colors.textMuted
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.maximumWidth: 380
            }

            Switch {
                text: "Hide watched"
                checked: App.hideWatched
                onToggled: App.setHideWatched(checked)
                contentItem: Label {
                    text: parent.text
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    leftPadding: parent.indicator.width + 6
                    verticalAlignment: Text.AlignVCenter
                }
            }

            FlatButton {
                text: App.busy ? "Refreshing" : "Refresh"
                accent: true
                enabled: !App.busy
                onClicked: App.refresh()
            }
        }
    }

    // A source that fails silently is the failure mode this whole application
    // has to guard against, so problems are visible here rather than only in
    // the settings.
    Rectangle {
        id: banner
        visible: App.problems.length > 0
        anchors.top: parent.top
        width: parent.width
        height: visible ? 32 : 0
        color: Theme.colors.surfaceRaised
        z: 3

        Label {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 12
            verticalAlignment: Text.AlignVCenter
            text: App.problems.length + " problem"
                  + (App.problems.length === 1 ? "" : "s") + "  ·  "
                  + App.problems[App.problems.length - 1]
            color: Theme.colors.error
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }

    MiniPlayer {
        id: miniPlayer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        z: 2
    }

    // ---- sidebar ---------------------------------------------------------

    Rectangle {
        id: sidebar
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: miniPlayer.top
        anchors.topMargin: banner.height
        width: 214
        color: root.panelColour(Theme.colors.surface)

        Rectangle {
            anchors.right: parent.right
            width: 1
            height: parent.height
            color: Theme.colors.border
        }

        // A wheel over the sidebar moves the selection rather than scrolling
        // the list, which is what makes stepping through the boxes and back to
        // All a single gesture. Small touchpad deltas are accumulated so one
        // flick does not jump several entries.
        WheelHandler {
            property real carried: 0
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function (event) {
                carried += event.angleDelta.y
                while (carried >= 120) {
                    carried -= 120
                    App.stepSelection(-1)
                }
                while (carried <= -120) {
                    carried += 120
                    App.stepSelection(1)
                }
            }
        }

        Flickable {
            id: sidebarFlick
            anchors.fill: parent
            anchors.topMargin: 8
            anchors.bottomMargin: 8
            contentHeight: sidebarColumn.height
            clip: true
            interactive: false
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Column {
                id: sidebarColumn
                width: parent.width
                spacing: 2

                SidebarHeading {
                    text: "Channels"
                    actionText: "+"
                    onAction: root.askForName("group", -1, "", "")
                }

                Repeater {
                    model: App.groups
                    SidebarRow {
                        width: sidebarColumn.width
                        label: modelData.name
                        count: modelData.unwatched
                        selected: modelData.id < 0 ? App.viewKind === "all"
                                                   : (App.viewKind === "group"
                                                      && App.viewId === modelData.id)
                        onActivated: App.selectGroup(modelData.id)
                        onRevealRequested: root.revealRow(this)
                        // All is not a group anyone made, so it cannot be
                        // renamed, moved or deleted.
                        onContextRequested: {
                            if (modelData.id < 0)
                                return
                            groupMenu.groupId = modelData.id
                            groupMenu.groupName = modelData.name
                            groupMenu.popup()
                        }
                    }
                }

                Label {
                    visible: App.groups.length <= 1
                    width: sidebarColumn.width - 28
                    x: 14
                    text: "A group holds channels you pick, and shows only their videos. Make one with the plus above."
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }

                Item { width: 1; height: 10 }

                SidebarHeading { text: "Yours" }

                SidebarRow {
                    width: sidebarColumn.width
                    label: "Recommended"
                    count: 0
                    selected: App.viewKind === "recommended"
                    onActivated: App.showRecommended()
                    onRevealRequested: root.revealRow(this)
                }

                SidebarRow {
                    width: sidebarColumn.width
                    label: "History"
                    count: 0
                    selected: App.viewKind === "history"
                    onActivated: App.showHistory()
                    onRevealRequested: root.revealRow(this)
                }

                SidebarRow {
                    width: sidebarColumn.width
                    label: "Music"
                    count: 0
                    selected: App.viewKind === "music"
                    onActivated: App.showMusic()
                    onRevealRequested: root.revealRow(this)
                }

                Item { width: 1; height: 10 }

                SidebarHeading {
                    text: "Playlists"
                    // Read on request rather than at launch. These are
                    // YouTube's own lists and asking for them is a request,
                    // so it happens when you want it to.
                    actionText: "\u21bb"
                    onAction: App.refreshPlaylists()
                }

                Repeater {
                    model: App.playlists
                    SidebarRow {
                        width: sidebarColumn.width
                        label: modelData.title
                        count: modelData.items
                        selected: App.viewKind === "playlist" && App.viewPlaylist === modelData.ext_id
                        onActivated: App.selectPlaylist(modelData.ext_id)
                        onRevealRequested: root.revealRow(this)
                    }
                }

                Label {
                    visible: App.playlists.length === 0
                    width: sidebarColumn.width - 28
                    x: 14
                    text: "Your YouTube playlists appear here. Press the arrow above to read them."
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }

                Item { width: 1; height: 10 }

                SidebarHeading {
                    text: "Boxes"
                    actionText: "+"
                    onAction: root.askForName("box", -1, "", "")
                }

                Repeater {
                    model: App.boxes
                    SidebarRow {
                        width: sidebarColumn.width
                        label: modelData.name
                        count: modelData.items
                        selected: App.viewKind === "box" && App.viewId === modelData.id
                        onActivated: App.selectBox(modelData.id)
                        onRevealRequested: root.revealRow(this)
                        onContextRequested: {
                            boxMenu.boxId = modelData.id
                            boxMenu.boxName = modelData.name
                            boxMenu.popup()
                        }
                    }
                }

                Label {
                    visible: App.boxes.length === 0
                    width: sidebarColumn.width - 28
                    x: 14
                    text: "A box holds videos you pick yourself. Make one with the plus above."
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    // ---- content ---------------------------------------------------------

    LiveBar {
        id: liveBar
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: banner.height
    }

    ChannelHeader {
        id: channelHeader
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: liveBar.visible ? liveBar.bottom : parent.top
        anchors.topMargin: liveBar.visible ? 0 : banner.height
        info: App.channelInfo
        visible: App.viewKind === "channel"
        onCloseRequested: App.selectGroup(-1)
        onGroupsRequested: root.askForGroups(App.channelInfo.key)
    }

    DetailPanel {
        id: detailPanel
        objectName: "detailPanel"
        anchors.right: parent.right
        anchors.top: liveBar.visible ? liveBar.bottom : parent.top
        anchors.topMargin: liveBar.visible ? 0 : banner.height
        anchors.bottom: miniPlayer.top
        width: App.panelWidth
        visible: App.detailOpen && App.viewKind !== "music"
    }

    MusicView {
        id: musicView
        objectName: "musicView"
        visible: App.viewKind === "music"
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: liveBar.visible ? liveBar.bottom : parent.top
        anchors.topMargin: liveBar.visible ? 0 : banner.height
        anchors.bottom: miniPlayer.top
    }

    GridView {
        id: grid
        objectName: "grid"
        visible: App.viewKind !== "music"
        anchors.left: sidebar.right
        anchors.right: detailPanel.visible ? detailPanel.left : parent.right
        anchors.top: channelHeader.visible ? channelHeader.bottom
                                          : (liveBar.visible ? liveBar.bottom : parent.top)
        anchors.bottom: miniPlayer.top
        anchors.topMargin: channelHeader.visible ? 8
                                                 : (liveBar.visible ? 10 : banner.height + 10)
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        clip: true
        cellWidth: Math.max(260, Math.floor(width / Math.max(1, Math.floor(width / 330))))
        cellHeight: cellWidth * 9 / 16 + 108
        model: feedModel
        cacheBuffer: 800

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        // Sized in card rows and set in the config, since how far a notch
        // should move is taste.
        SmoothScroll {
            flickable: grid
            step: grid.cellHeight * App.scrollRowsPerNotch
        }

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            VideoCard {
                anchors.fill: parent
                anchors.margins: 6
                title: model.title
                channelTitle: model.channelTitle
                channelAvatar: model.channelAvatar
                thumbnail: model.thumbnail
                ageText: model.ageText
                durationText: model.durationText
                viewsText: model.viewsText
                likesText: model.likesText
                watched: model.watched
                isLive: model.isLive
                progress: model.progress
                onPlayRequested: App.play(model.key)
                onListenRequested: App.playAudio(model.key)
                onChannelRequested: App.openChannel(model.channelKey)
                onMenuRequested: {
                    root.menuKey = model.key
                    root.menuChannelKey = model.channelKey
                    root.menuWatched = model.watched
                    videoMenu.popup()
                }
            }
        }

        Label {
            anchors.centerIn: parent
            visible: grid.count === 0 && App.viewKind !== "music"
            horizontalAlignment: Text.AlignHCenter
            color: Theme.colors.textMuted
            font.pixelSize: 14
            text: App.emptyHint
        }
    }

    // ---- menus and the name popup ---------------------------------------

    Menu {
        id: videoMenu
        objectName: "videoMenu"

        // Every entry dismisses the menu itself. A Menu is supposed to close
        // on its own when an item fires, and it did not here, so it is done
        // explicitly rather than left to chance.
        MenuItem {
            text: "Play in mpv"
            onTriggered: { App.play(root.menuKey); videoMenu.dismiss() }
        }
        MenuItem {
            text: "Open the channel"
            onTriggered: { App.openChannel(root.menuChannelKey); videoMenu.dismiss() }
        }
        MenuItem {
            text: "Groups for this channel"
            onTriggered: {
                var key = root.menuChannelKey
                videoMenu.dismiss()
                root.askForGroups(key)
            }
        }
        MenuItem {
            text: root.menuWatched ? "Mark as not watched" : "Mark as watched"
            onTriggered: {
                if (root.menuWatched)
                    App.markUnwatched(root.menuKey)
                else
                    App.markWatched(root.menuKey)
                videoMenu.dismiss()
            }
        }

        MenuSeparator {}

        // Built from the box list at the moment the menu opens, with a tick
        // beside the boxes this video is already in, so one menu both adds and
        // removes.
        Instantiator {
            id: boxEntries
            model: App.boxes
            // A delegate created here does not inherit this file's id scope, so
            // it cannot see videoMenu, and reaching for it raises a reference
            // error that also leaves the menu open. The menu is handed to each
            // entry from out here, where the id does resolve.
            // Five, counting the entries declared above this and the
            // separator. Adding another entry up there means changing this.
            onObjectAdded: (index, object) => {
                object.owner = videoMenu
                videoMenu.insertItem(index + 5, object)
            }
            onObjectRemoved: (index, object) => videoMenu.removeItem(object)
            delegate: MenuItem {
                required property var modelData
                property var owner: null
                text: (App.boxesHolding(root.menuKey).indexOf(modelData.id) >= 0
                       ? "✓  " : "   ") + modelData.name
                onTriggered: {
                    if (App.boxesHolding(root.menuKey).indexOf(modelData.id) >= 0)
                        App.removeFromBox(modelData.id, root.menuKey)
                    else
                        App.addToBox(modelData.id, root.menuKey)
                    if (owner)
                        owner.dismiss()
                }
            }
        }

        MenuItem {
            text: "Put in a new box"
            onTriggered: { videoMenu.dismiss(); root.askForName("box", -1, root.menuKey, "") }
        }
    }

    Menu {
        id: themeMenu
        objectName: "themeMenu"

        Instantiator {
            model: Theme.names
            onObjectAdded: (index, object) => {
                object.owner = themeMenu
                themeMenu.insertItem(index, object)
            }
            onObjectRemoved: (index, object) => themeMenu.removeItem(object)
            delegate: MenuItem {
                required property var modelData
                property var owner: null
                text: (modelData === Theme.current ? "✓  " : "   ") + modelData
                onTriggered: {
                    Theme.select(modelData)
                    if (owner)
                        owner.dismiss()
                }
            }
        }
    }

    // The groups one channel is in, ticked, so one menu both adds and removes.
    // Opened from a video's menu and from the channel page.
    Menu {
        id: channelGroupMenu
        objectName: "channelGroupMenu"
        property string channelKey: ""

        Instantiator {
            id: channelGroupEntries
            // All is not a real group and cannot hold anything, so it is not
            // offered. Filtering by id rather than by position, since which
            // row All occupies is not this file's business.
            model: App.groups.filter(function (g) { return g.id >= 0 })
            // A delegate created here does not inherit this file's id scope,
            // so the menu is handed to each entry from out here.
            onObjectAdded: (index, object) => {
                object.owner = channelGroupMenu
                channelGroupMenu.insertItem(index, object)
            }
            onObjectRemoved: (index, object) => channelGroupMenu.removeItem(object)
            delegate: MenuItem {
                required property var modelData
                property var owner: null
                text: (App.groupsHolding(channelGroupMenu.channelKey).indexOf(modelData.id) >= 0
                       ? "✓  " : "   ") + modelData.name
                onTriggered: {
                    if (App.groupsHolding(channelGroupMenu.channelKey).indexOf(modelData.id) >= 0)
                        App.removeChannelFromGroup(modelData.id, channelGroupMenu.channelKey)
                    else
                        App.addChannelToGroup(modelData.id, channelGroupMenu.channelKey)
                    if (owner)
                        owner.dismiss()
                }
            }
        }

        MenuItem {
            text: "Put in a new group"
            onTriggered: {
                var key = channelGroupMenu.channelKey
                channelGroupMenu.dismiss()
                root.askForName("group", -1, key, "")
            }
        }
    }

    Menu {
        id: groupMenu
        objectName: "groupMenu"
        property int groupId: -1
        property string groupName: ""

        MenuItem {
            text: "Rename"
            onTriggered: {
                var id = groupMenu.groupId, name = groupMenu.groupName
                groupMenu.dismiss()
                root.askForName("group", id, "", name)
            }
        }
        MenuItem {
            text: "Move up"
            onTriggered: { App.moveGroup(groupMenu.groupId, -1); groupMenu.dismiss() }
        }
        MenuItem {
            text: "Move down"
            onTriggered: { App.moveGroup(groupMenu.groupId, 1); groupMenu.dismiss() }
        }
        MenuItem {
            // The channels themselves are untouched, as with a box and its
            // videos.
            text: "Delete the group"
            onTriggered: { App.deleteGroup(groupMenu.groupId); groupMenu.dismiss() }
        }
    }

    Menu {
        id: boxMenu
        property int boxId: -1
        property string boxName: ""

        MenuItem {
            text: "Rename"
            onTriggered: {
                var id = boxMenu.boxId, name = boxMenu.boxName
                boxMenu.dismiss()
                root.askForName("box", id, "", name)
            }
        }
        MenuItem {
            text: "Delete the box"
            onTriggered: { App.deleteBox(boxMenu.boxId); boxMenu.dismiss() }
        }
    }

    Popup {
        id: namePopup
        objectName: "namePopup"
        anchors.centerIn: parent
        width: 340
        padding: 16
        modal: true
        focus: true
        background: Rectangle {
            radius: 8
            color: Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border
        }

        readonly property bool aGroup: root.namingKind === "group"
        readonly property bool renaming: root.namingId >= 0

        function commit() {
            var name = nameField.text.trim()
            if (name === "") {
                namePopup.close()
                return
            }
            if (namePopup.renaming) {
                if (namePopup.aGroup)
                    App.renameGroup(root.namingId, name)
                else
                    App.renameBox(root.namingId, name)
            } else if (namePopup.aGroup) {
                var group = App.createGroup(name)
                if (group >= 0 && root.namingKey !== "")
                    App.addChannelToGroup(group, root.namingKey)
            } else {
                var box = App.createBox(name)
                if (box >= 0 && root.namingKey !== "")
                    App.addToBox(box, root.namingKey)
            }
            namePopup.close()
        }

        Column {
            width: parent.width
            spacing: 10

            Label {
                text: namePopup.renaming
                      ? (namePopup.aGroup ? "Rename the group" : "Rename the box")
                      : (namePopup.aGroup ? "Name the new group" : "Name the new box")
                color: Theme.colors.text
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }

            TextField {
                id: nameField
                objectName: "nameField"
                width: parent.width
                color: Theme.colors.text
                placeholderText: namePopup.aGroup ? "Music" : "Watch tonight"
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: nameField.activeFocus ? Theme.colors.accent : Theme.colors.border
                }
                onAccepted: namePopup.commit()
            }

            Row {
                spacing: 8
                anchors.right: parent.right
                FlatButton {
                    text: "Cancel"
                    onClicked: namePopup.close()
                }
                FlatButton {
                    text: namePopup.renaming ? "Rename" : "Create"
                    accent: true
                    onClicked: namePopup.commit()
                }
            }
        }
    }
}
