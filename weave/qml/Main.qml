import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

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

    // No bar from the system. The toolbar row below is the title bar, it
    // carries the window's own buttons, and the window is no taller for them.
    // The border goes with the bar, so the edges are drawn back in by
    // ResizeGrips.
    flags: Qt.Window | Qt.FramelessWindowHint

    ThemeBackground {
        anchors.fill: parent
        z: -1
    }

    // What the open view can do, if anything, shown as one button beside
    // Refresh.
    readonly property string viewActionText: {
        if (App.viewKind === "history") return "Read it again"
        if (App.viewKind === "recommended") return "Ask again"
        if (App.viewKind === "playlist") return "Read it again"
        if (App.viewKind === "search") return App.searchScope === "youtube"
                                              ? "Search again" : "Search YouTube"
        return ""
    }

    function doViewAction() {
        if (App.viewKind === "history") App.importHistory()
        else if (App.viewKind === "recommended") App.refreshRecommended()
        else if (App.viewKind === "playlist") App.refreshPlaylist()
        else if (App.viewKind === "search") App.searchYouTube()
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

    // ---- the window itself -----------------------------------------------

    // Maximised and full screen are the two states whose size is the screen's
    // rather than the window's own. Anything else, including the moment
    // before the window is first shown, counts as the ordinary state whose
    // shape is worth remembering.
    readonly property bool windowed: visibility !== Window.Maximized
                                     && visibility !== Window.FullScreen
                                     && visibility !== Window.Minimized

    // The shape to come back to. The geometry is stored on the way out by
    // reading the window, so a window closed while maximised would be
    // remembered as the size of the screen and could never be got back to its
    // own shape again. These follow the window only while it has its own
    // shape, and are put back before the window is read.
    property int restoredWidth: 0
    property int restoredHeight: 0
    property int restoredX: 0
    property int restoredY: 0

    function rememberShape() {
        if (!root.windowed)
            return
        root.restoredWidth = root.width
        root.restoredHeight = root.height
        root.restoredX = root.x
        root.restoredY = root.y
    }

    onWidthChanged: root.rememberShape()
    onHeightChanged: root.rememberShape()
    onXChanged: root.rememberShape()
    onYChanged: root.rememberShape()
    Component.onCompleted: root.rememberShape()

    function toggleMaximised() {
        if (root.visibility === Window.Maximized) {
            root.showNormal()
        } else {
            // Taken here rather than left to the change above, because the
            // order in which a compositor reports the new state and the new
            // size is its own business, and a size that arrives first would
            // be remembered as the shape to come back to.
            root.rememberShape()
            root.showMaximized()
        }
    }

    // Set once the window is on its way out, so stepping out of maximised
    // does not turn into a loop of refused closes.
    property bool leaving: false

    // Closing while maximised is refused once. The window steps back to its
    // own shape first, the compositor is given a moment to hand that shape
    // back, and only then does the close go through, so what is stored is the
    // shape to come back to and not the screen.
    onClosing: function (close) {
        if (root.windowed || root.leaving)
            return
        close.accepted = false
        root.leaving = true
        root.showNormal()
        leaveTimer.start()
    }

    Timer {
        id: leaveTimer
        objectName: "leaveTimer"
        interval: 120
        onTriggered: root.close()
    }

    // A quit that never went through the window at all, such as the last
    // window closing from elsewhere, leaves no chance to wait for the
    // compositor. The remembered shape is written straight back instead,
    // which is right wherever a geometry change takes effect at once.
    Connections {
        target: Qt.application
        function onAboutToQuit() {
            if (root.windowed)
                return
            root.showNormal()
            root.x = root.restoredX
            root.y = root.restoredY
            root.width = root.restoredWidth
            root.height = root.restoredHeight
        }
    }

    // The window's edges, over everything, so a corner is a corner whatever
    // happens to be drawn under it.
    ResizeGrips {
        objectName: "resizeGrips"
        target: root
        parent: Overlay.overlay
        anchors.fill: parent
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

        // The row, and behind it the surface that moves the window.
        //
        // Wrapped in one item rather than sitting in the bar side by side,
        // because a bar holding more than one thing takes its height from
        // neither of them and would collapse to nothing. The bar's own
        // background is no place for it either, since a control's background
        // is never offered any input.
        Item {
            id: titleArea
            objectName: "titleArea"
            anchors.fill: parent
            // The window's own buttons are no longer a cell of the row, so
            // the bar asks for room for the two of them side by side, and for
            // the three margins between and around them.
            implicitWidth: barRow.implicitWidth + windowControls.implicitWidth + 36
            implicitHeight: Math.max(barRow.implicitHeight, windowControls.implicitHeight)

            // Behind the row, so a press reaches it only where the row is
            // empty and the search boxes and the buttons above are untouched.
            // It takes the press itself rather than letting it fall through,
            // because the bar accepts every button it is offered and would
            // swallow it, which cancels both handlers below.
            MouseArea {
                id: titleDrag
                objectName: "titleDrag"
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton

                // The compositor does the moving. A move rolled by hand out of
                // pointer deltas cannot snap to a screen edge, and under
                // Wayland a window may not place itself at all. The handler
                // only says when to ask, on a drag rather than on a press, so
                // a double click still gets through.
                DragHandler {
                    objectName: "titleDragHandler"
                    target: null
                    onActiveChanged: if (active) root.startSystemMove()
                }

                TapHandler {
                    objectName: "titleTapHandler"
                    gesturePolicy: TapHandler.DragThreshold
                    onDoubleTapped: root.toggleMaximised()
                }
            }

            // Everything except the window's own buttons, in a strip that
            // stops short of them and is clipped at its edge. A row that
            // cannot fit its cells does not squeeze them: each cell keeps the
            // width it asks for, and what does not fit hangs off the right
            // end. Clipping is what keeps that overhang off the three buttons
            // whatever the row is asked to hold.
            RowLayout {
                id: barRow
                objectName: "barRow"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: windowControls.left
                anchors.leftMargin: 14
                anchors.rightMargin: 8
                clip: true
                spacing: 12

                // What goes as the window narrows, and in what order, is
                // decided here rather than left to the row, because a row
                // holds every cell at the width it asks for and simply
                // overflows. Only the two fields and the status below are
                // told they may be smaller than that, so everything else has
                // to be given up outright, and each width below is where what
                // remains stops fitting even once those three have shrunk as
                // far as they may.
                Label {
                    objectName: "wordmark"
                    // First to go. The name is decoration, and the task
                    // switcher says it anyway.
                    visible: root.width >= 1230
                    text: "Weave"
                    color: Theme.colors.text
                    font.pixelSize: 18
                    font.weight: Font.Bold
                }

                TextField {
                    id: addField
                    objectName: "addField"
                    // Sixth to go, and narrower than it asks for well before
                    // that. Never reached by dragging: the window cannot be
                    // made narrower than 760.
                    visible: root.width >= 710
                    // A cell is pinned to the width it asks for unless it is
                    // told to fill, so this says so and then caps itself, and
                    // the cap is what keeps it from growing into the room the
                    // spacer holds.
                    Layout.fillWidth: true
                    Layout.preferredWidth: 260
                    Layout.maximumWidth: 260
                    Layout.minimumWidth: 170
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
                    // Last of the row to go, and long past the narrowest
                    // window anyone can drag to.
                    visible: root.width >= 400
                    Layout.fillWidth: true
                    Layout.preferredWidth: 220
                    Layout.maximumWidth: 220
                    Layout.minimumWidth: 150
                    placeholderText: "Search yours, or YouTube with return"
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
                    // Emptied from the outside when the search view is left, so
                    // the box never describes somewhere you are no longer.
                    Connections {
                        target: App
                        function onSearchEnded() { searchField.text = "" }
                    }
                    // Typing searches what is stored, which costs nothing.
                    // Pressing return asks YouTube itself, which costs a request.
                    onAccepted: App.searchYouTube()
                    Keys.onEscapePressed: text = ""
                }

                FlatButton {
                    objectName: "importSubscriptions"
                    // Second to go. Read once and then rarely again.
                    visible: root.width >= 1160
                    text: "Import subscriptions"
                    onClicked: App.importSubscriptions()
                }

                FlatButton {
                    objectName: "themeButton"
                    // Fourth to go.
                    visible: root.width >= 990
                    text: Theme.current
                    onClicked: themeMenu.popup()
                }

                Item { Layout.fillWidth: true }

                Label {
                    objectName: "status"
                    // Third to go, and the one thing here allowed to be
                    // narrower than its text, so it elides away to nothing
                    // before it goes at all.
                    visible: root.width >= 1005
                    text: App.status
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    // Free to be narrower than its text, down to nothing, and
                    // never wider than it or than the room a bar can spare.
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: Math.min(380, implicitWidth)
                }

                Switch {
                    objectName: "hideWatched"
                    // Fifth to go.
                    visible: root.width >= 875
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

                // One button for whatever the open view can do, kept beside
                // Refresh so it is always in the same place rather than buried in
                // the middle of the bar.
                FlatButton {
                    objectName: "viewAction"
                    // Seventh to go, and only below the narrowest window
                    // anyone can drag to.
                    visible: root.viewActionText !== "" && root.width >= 530
                    text: root.viewActionText
                    onClicked: root.doViewAction()
                }

                FlatButton {
                    objectName: "refresh"
                    // The one thing in the row that never goes.
                    text: App.busy ? "Refreshing" : "Refresh"
                    accent: true
                    enabled: !App.busy
                    onClicked: App.refresh()
                }
            }

            // Not a cell of the row but anchored to the right edge of the
            // bar, with the row stopping short of them.
            //
            // As the last cell they were the first thing lost: a row given
            // less width than its cells ask for holds them at that width all
            // the same and lets the remainder hang off its right end, which
            // for the last cell means off the edge of the window. Anchored
            // here their room is not the row's to spend.
            WindowControls {
                id: windowControls
                objectName: "windowControls"
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                maximised: root.visibility === Window.Maximized
                onMinimiseRequested: root.showMinimized()
                onMaximiseRequested: root.toggleMaximised()
                onCloseRequested: root.close()
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

        // The panel moves the window as well, from the room its list does
        // not use, so a window with no bar of its own can be taken hold of on
        // either side of it.
        //
        // The surface is exactly that room: it begins where the list ends and
        // runs to the bottom of the panel. Keeping a row, a heading and a
        // plus out of a drag has to be done by shape like this rather than by
        // covering the panel and asking what was under the press, because a
        // press that lands on a row never arrives here to be asked about --
        // the row takes it -- while the handler below is offered it all the
        // same and would answer for it.
        //
        // First in the panel, so the list is drawn over it. The panel is a
        // plain rectangle, so a child of it is offered input at all: a
        // control would have kept its background out of reach.
        MouseArea {
            id: sidebarDrag
            objectName: "sidebarDrag"
            width: parent.width
            y: Math.min(parent.height,
                        sidebarFlick.y + sidebarColumn.height - sidebarFlick.contentY)
            height: Math.max(0, parent.height - y)
            acceptedButtons: Qt.LeftButton

            // The compositor does the moving, exactly as it does from the
            // toolbar. A move rolled by hand out of pointer deltas cannot
            // snap to a screen edge, and under Wayland a window may not place
            // itself at all. The handler only says when to ask, on a drag
            // rather than on a press.
            DragHandler {
                objectName: "sidebarDragHandler"
                target: null
                onActiveChanged: if (active) root.startSystemMove()
            }
        }

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
                objectName: "sidebarColumn"
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

                SidebarRow {
                    width: sidebarColumn.width
                    label: "How things are"
                    count: 0
                    selected: App.viewKind === "debug"
                    onActivated: App.showDebug()
                    onRevealRequested: root.revealRow(this)
                }

                Item { width: 1; height: 10 }

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

                Item { width: 1; height: 10 }

                SidebarHeading {
                    text: "Playlists"
                    // Read on request rather than at launch. These are
                    // YouTube's own lists and asking for them is a request,
                    // so it happens when you want it to.
                    // One action, two things to do with a list this long,
                    // so it opens a menu rather than doing one of them.
                    actionText: "\u22ef"
                    onAction: playlistMenu.popup()
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
                        onContextRequested: {
                            playlistRowMenu.playlistId = modelData.ext_id
                            playlistRowMenu.playlistName = modelData.title
                            playlistRowMenu.popup()
                        }
                    }
                }

                Label {
                    visible: App.playlists.length === 0
                    width: sidebarColumn.width - 28
                    x: 14
                    text: "Your YouTube playlists appear here. Read them from the menu above."
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

    DebugView {
        id: debugView
        objectName: "debugView"
        visible: App.viewKind === "debug"
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: liveBar.visible ? liveBar.bottom : parent.top
        anchors.topMargin: liveBar.visible ? 0 : banner.height
        anchors.bottom: miniPlayer.top
    }

    GridView {
        id: grid
        objectName: "grid"
        visible: App.viewKind !== "music" && App.viewKind !== "debug"
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

        // Cards grow with the window instead of snapping between sizes, so a
        // row always fills the width. Two is the fewest columns worth showing,
        // since one card a row reads as a list and wastes the width. The lower
        // bound on a cell only keeps a card from collapsing, and at any width
        // where three or more columns fit it never applies.
        readonly property int columnCount: Math.max(2, Math.floor(width / 330))
        cellWidth: Math.max(200, Math.floor(width / columnCount))
        cellHeight: cellWidth * 9 / 16 + 108
        model: feedModel
        cacheBuffer: 800

        // Asking only once the bottom is reached leaves the reader sitting at
        // the end while the next page is fetched, so ask about two rows early
        // and the rows are usually in place before they are reached. The bound
        // value changes only when the view crosses into or out of that band,
        // which is what keeps this from asking again on every pixel of
        // movement. Which views can answer at all is the bridge's business, so
        // this does not have to know.
        readonly property bool nearEnd: count > 0 && contentHeight > height
                                        && contentY + height >= contentHeight - cellHeight * 2
        onNearEndChanged: if (nearEnd) App.loadMore()

        // A backstop for what the band cannot cover, such as a feed short
        // enough to fit on screen whole.
        onAtYEndChanged: if (atYEnd && count > 0) App.loadMore()

        // Always on rather than only while moving. Knowing how much is above
        // and below is most of what a scroll bar is for, and a bar that only
        // appears once you are already moving cannot say it.
        ScrollBar.vertical: ScrollBar {
            id: gridBar
            policy: ScrollBar.AlwaysOn
            width: 10
            contentItem: Rectangle {
                implicitWidth: 6
                radius: 3
                color: gridBar.pressed ? Theme.colors.accent : Theme.colors.textMuted
                opacity: gridBar.hovered || gridBar.pressed ? 1.0 : 0.8
                Behavior on opacity { NumberAnimation { duration: 120 } }
            }
            background: Rectangle {
                color: Theme.colors.surface
                opacity: 0.35
            }
        }

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

    // Something is happening and there is nothing else on screen to say so.
    // Handing a video to mpv takes several seconds, and so does a search.
    Rectangle {
        id: noticeBar
        objectName: "noticeBar"
        visible: opacity > 0
        opacity: App.notice !== "" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        anchors.horizontalCenter: grid.horizontalCenter
        anchors.bottom: miniPlayer.top
        anchors.bottomMargin: 16
        z: 50
        radius: 16
        height: 32
        width: noticeRow.implicitWidth + 28
        color: Theme.colors.surfaceRaised
        border.width: 1
        border.color: Theme.colors.border

        Row {
            id: noticeRow
            anchors.centerIn: parent
            spacing: 8

            // A plain turning mark rather than a control, so it needs no
            // style and cannot be mistaken for something to press.
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 10
                height: 10
                radius: 2
                color: Theme.colors.accent
                RotationAnimator on rotation {
                    running: noticeBar.visible
                    loops: Animation.Infinite
                    from: 0
                    to: 360
                    duration: 1400
                }
            }

            Label {
                id: noticeText
                anchors.verticalCenter: parent.verticalCenter
                text: App.notice
                color: Theme.colors.text
                font.pixelSize: 12
            }
        }
    }

    // ---- menus and the name popup ---------------------------------------

    Menu {
        id: videoMenu
        objectName: "videoMenu"

        // Where the box entries go. Looked up rather than counted, so adding
        // an entry above the separator cannot quietly misplace every box.
        function slotAfter(item) {
            for (var i = 0; i < count; i++)
                if (itemAt(i) === item)
                    return i + 1
            return count
        }

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

        MenuSeparator { id: boxSeparator }

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
            onObjectAdded: (index, object) => {
                object.owner = videoMenu
                videoMenu.insertItem(videoMenu.slotAfter(boxSeparator) + index, object)
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
        id: playlistMenu
        objectName: "playlistMenu"

        MenuItem {
            text: "Read the list again"
            onTriggered: { App.refreshPlaylists(); playlistMenu.dismiss() }
        }
        MenuItem {
            text: "Choose which to show"
            onTriggered: { playlistMenu.dismiss(); playlistChooser.open() }
        }
    }

    Menu {
        id: playlistRowMenu
        objectName: "playlistRowMenu"
        property string playlistId: ""
        property string playlistName: ""

        MenuItem {
            text: "Read it again"
            onTriggered: {
                var id = playlistRowMenu.playlistId
                playlistRowMenu.dismiss()
                App.selectPlaylist(id)
                App.refreshPlaylist()
            }
        }
        MenuItem {
            // Hiding is not forgetting. It keeps its contents and comes back
            // from the chooser.
            text: "Hide it"
            onTriggered: {
                App.setPlaylistHidden(playlistRowMenu.playlistId, true)
                playlistRowMenu.dismiss()
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

    // A checklist rather than a menu, because a menu of a hundred playlists is
    // not something anyone can find anything in.
    Popup {
        id: playlistChooser
        objectName: "playlistChooser"
        anchors.centerIn: parent
        width: 420
        height: Math.min(520, root.height - 80)
        padding: 16
        modal: true
        focus: true
        onOpened: {
            reload()
            chooserFilter.text = ""
            chooserFilter.forceActiveFocus()
        }
        background: Rectangle {
            radius: 8
            color: Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border
        }

        // A snapshot taken when it opens, not a live binding. Ticking a box
        // changes the playlists, and a model that rebuilds itself sends the
        // list back to the top under the hand that just ticked it.
        property var all: []
        // Which are hidden, kept here so a tick does not have to rebuild the
        // model to be seen.
        property var away: ({})

        // Also called after a move, so the rows redraw in the new order
        // without the list being rebuilt underneath the pointer by a binding.
        function reload() {
            all = App.allPlaylists
            var map = {}
            for (var i = 0; i < all.length; i++)
                map[all[i].ext_id] = !!all[i].hidden
            away = map
        }

        // A fresh object every time. Putting the same one back changes
        // nothing as far as QML is concerned, so the boxes went on showing
        // what they showed before. It was invisible for a single tick, where
        // the box had already flipped itself under the pointer, and obvious
        // for Show every one, where nothing was clicked at all.
        function toggle(id, hidden) {
            var map = {}
            for (var key in away)
                map[key] = away[key]
            map[id] = hidden
            away = map
            App.setPlaylistHidden(id, hidden)
        }

        function setEveryOne(hidden) {
            var map = {}
            for (var i = 0; i < all.length; i++) {
                map[all[i].ext_id] = hidden
                if (!!away[all[i].ext_id] !== hidden)
                    App.setPlaylistHidden(all[i].ext_id, hidden)
            }
            away = map
        }

        function matching() {
            var text = chooserFilter.text.trim().toLowerCase()
            if (text === "")
                return all
            return all.filter(function (p) {
                return p.title.toLowerCase().indexOf(text) >= 0
            })
        }

        Column {
            anchors.fill: parent
            spacing: 10

            Label {
                text: "Which playlists to show"
                color: Theme.colors.text
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }

            TextField {
                id: chooserFilter
                objectName: "chooserFilter"
                width: parent.width
                placeholderText: "Filter by name"
                color: Theme.colors.text
                placeholderTextColor: Theme.colors.textMuted
                background: Rectangle {
                    radius: 6
                    color: Theme.colors.background
                    border.width: 1
                    border.color: chooserFilter.activeFocus ? Theme.colors.accent
                                                            : Theme.colors.border
                }
            }

            ListView {
                id: chooserList
                objectName: "chooserList"
                width: parent.width
                height: parent.height - y - closeRow.height - 20
                clip: true
                model: playlistChooser.matching()
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // Laid out here rather than left to the control. A CheckBox
                // with its own contentItem draws the box after the text, so a
                // long name ran straight into it.
                delegate: Item {
                    id: entry
                    objectName: "chooserRow"
                    required property var modelData
                    width: chooserList.width - 12
                    height: 30

                    CheckBox {
                        id: box
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        checked: !playlistChooser.away[entry.modelData.ext_id]
                        onToggled: playlistChooser.toggle(entry.modelData.ext_id, !checked)
                    }

                    Label {
                        anchors.left: box.right
                        anchors.leftMargin: 4
                        anchors.right: countLabel.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: entry.modelData.title
                        color: Theme.colors.text
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Label {
                        id: countLabel
                        anchors.right: order.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: entry.modelData.items ? entry.modelData.items + " videos" : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                    }

                    // The order here is the order in the sidebar. Reading the
                    // list again keeps whatever was chosen here, so this is
                    // not undone by a refresh.
                    Row {
                        id: order
                        anchors.right: parent.right
                        anchors.rightMargin: 2
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        FlatButton {
                            text: "\u25b2"
                            onClicked: {
                                App.movePlaylist(entry.modelData.ext_id, -1)
                                playlistChooser.reload()
                            }
                        }
                        FlatButton {
                            text: "\u25bc"
                            onClicked: {
                                App.movePlaylist(entry.modelData.ext_id, 1)
                                playlistChooser.reload()
                            }
                        }
                    }

                    // The whole row is the target, not just the box, but not
                    // the arrows, which do their own thing.
                    MouseArea {
                        anchors.left: box.right
                        anchors.right: countLabel.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        onClicked: playlistChooser.toggle(
                                       entry.modelData.ext_id,
                                       !playlistChooser.away[entry.modelData.ext_id])
                    }
                }
            }

            Row {
                id: closeRow
                spacing: 8
                anchors.right: parent.right
                FlatButton {
                    text: "Hide every one"
                    onClicked: playlistChooser.setEveryOne(true)
                }
                FlatButton {
                    text: "Show every one"
                    onClicked: playlistChooser.setEveryOne(false)
                }
                FlatButton {
                    text: "Done"
                    accent: true
                    onClicked: playlistChooser.close()
                }
            }
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
