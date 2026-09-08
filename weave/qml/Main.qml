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
        id: windowGround
        anchors.fill: parent
        z: -1
    }

    // What the open view can do, if anything, shown as one button beside
    // Refresh.
    readonly property string viewActionText: {
        if (App.viewKind === "history") return App.historyShowsMusic
                                              ? "Read the listening again"
                                              : "Read it again"
        // Recommended is not here. Its button sits on the page itself, where
        // what it acts on is, since nobody read a button in the bar as
        // belonging to the page under it.
        if (App.viewKind === "playlist") return "Read it again"
        if (App.viewKind === "search") return App.searchScope === "youtube"
                                              ? "Search again" : "Search YouTube"
        return ""
    }

    function doViewAction() {
        if (App.viewKind === "history") {
            if (App.historyShowsMusic) App.readMusicHistory()
            else App.importHistory()
        }
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
    // A pale bar keeps more of itself, or the colour of the gradient
    // shows through it and the dark text on it stops being readable.
    readonly property real panelOpacity: Theme.washed ? (Theme.light ? 0.9 : 0.62) : 1.0
    // The role arrives as text, so it is read as a colour before its parts
    // are asked for. Reading r, g and b off the text gives nothing, and a
    // colour built from nothing is black, which is what every translucent bar
    // in a theme with a gradient had quietly become.
    function panelColour(role) {
        var colour = Qt.color(role)
        return Qt.rgba(colour.r, colour.g, colour.b, root.panelOpacity)
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
                //
                // Two buttons left this row for the settings page, which gave
                // the rest 257 pixels back. The two widths that were measured
                // with those buttons in the way came down by what they took,
                // so each cell goes at the same squeeze it went at before,
                // and the order is unchanged.
                Label {
                    objectName: "wordmark"
                    // First to go. The name is decoration, and the task
                    // switcher says it anyway.
                    visible: root.width >= 975
                    text: "Weave"
                    color: Theme.colors.text
                    font.pixelSize: 18
                    font.weight: Font.Bold
                }

                TextField {
                    id: searchField
                    objectName: "searchField"
                    // Last of the row to go, and long past the narrowest
                    // window anyone can drag to. The only box in the bar now,
                    // so it needs no telling apart from anything.
                    visible: root.width >= 400
                    // Wide enough for what it says, measured rather than
                    // guessed at, and only where the bar can spare it. The 220
                    // it used to ask for cut its own placeholder in half.
                    TextMetrics {
                        id: searchHint
                        font: searchField.font
                        text: searchField.placeholderText
                    }
                    Layout.fillWidth: true
                    Layout.preferredWidth: Math.ceil(searchHint.width) + 24
                    Layout.maximumWidth: Math.ceil(searchHint.width) + 24
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
                        // Walked back onto a search, which put its results
                        // back. The box says which words they answer. The
                        // bridge drops the search this retypes, so the kept
                        // results survive it.
                        function onSearchRestored(words) { searchField.text = words }
                    }
                    // Typing searches what is stored, which costs nothing.
                    // Pressing return asks YouTube itself, which costs a request.
                    onAccepted: App.searchYouTube()
                    Keys.onEscapePressed: text = ""
                }

                Item { Layout.fillWidth: true }

                Label {
                    objectName: "status"
                    // Second to go, and the one thing here allowed to be
                    // narrower than its text, so it is down to a sliver of a
                    // line by the time it goes at all.
                    visible: root.width >= 905
                    text: App.status
                    color: Theme.colors.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    // The width owes nothing to the text. It used to be capped
                    // at the label's own implicit width, which is a loop: the
                    // cell is sized from the text, the text is elided to the
                    // cell, and a pass that runs while those two disagree
                    // leaves a line cut short with half the bar empty beside
                    // it. A constant ceiling and a right edge cannot do that.
                    horizontalAlignment: Text.AlignRight
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: 460
                }

                Switch {
                    objectName: "hideWatched"
                    // Third to go.
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
                    // Fourth to go, and only below the narrowest window
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
            // Stops above the update line, so pressing that opens the release
            // page rather than taking hold of the window.
            height: Math.max(0, parent.height - y
                                - (updateLine.visible ? updateLine.height : 0))
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

        // A newer release than the one running. At the foot of the panel
        // rather than in the toolbar, since it is news rather than a control,
        // and it is drawn only while there is something to say.
        Rectangle {
            id: updateLine
            objectName: "updateLine"
            visible: App.updateVersion !== ""
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: visible ? updateColumn.height + 16 : 0
            color: updateHover.hovered ? Theme.colors.surfaceRaised : "transparent"
            z: 2

            HoverHandler { id: updateHover }
            TapHandler { onTapped: App.openRelease() }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: Theme.colors.border
            }

            Column {
                id: updateColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 2

                Label {
                    objectName: "updateHeadline"
                    width: parent.width
                    text: "A new version is available"
                    color: Theme.colors.accent
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }

                Label {
                    width: parent.width
                    text: App.updateVersion + ", this one is " + App.version
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
        }

        Flickable {
            id: sidebarFlick
            anchors.fill: parent
            anchors.topMargin: 8
            anchors.bottomMargin: 8 + (updateLine.visible ? updateLine.height : 0)
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
                    id: channelsHeading
                    text: "Channels"
                    actionText: "+"
                    // Both of the things it could mean, since it sits above a
                    // list of groups that begins with All. Following a channel
                    // was a box in the toolbar until it turned out to read as
                    // a second search box.
                    onAction: channelsMenu.popup(channelsHeading, 0, channelsHeading.height)
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

                SidebarRow {
                    width: sidebarColumn.width
                    label: "Settings"
                    count: 0
                    selected: App.viewKind === "settings"
                    onActivated: App.showSettings()
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
                            playlistRowMenu.isMusic = modelData.is_music === 1
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

                // Somebody else's lists, kept off their channel page. Apart
                // from your own, because they are not yours and are not in
                // the feed that reads yours.
                Item { width: 1; height: App.keptPlaylists.length > 0 ? 10 : 0 }

                SidebarHeading {
                    id: keptHeading
                    objectName: "keptHeading"
                    visible: App.keptPlaylists.length > 0
                    height: visible ? implicitHeight : 0
                    text: "Linked playlists"
                    // The same one action as your own list above, and for the
                    // same reason: a list is ordered and pruned somewhere
                    // other than in a menu of every entry.
                    actionText: "\u22ef"
                    onAction: keptChooser.open()
                }

                Repeater {
                    model: App.keptPlaylists
                    SidebarRow {
                        width: sidebarColumn.width
                        label: modelData.title
                        count: modelData.items
                        selected: App.viewKind === "playlist"
                                  && App.viewPlaylist === modelData.ext_id
                        onActivated: App.selectPlaylist(modelData.ext_id)
                        onRevealRequested: root.revealRow(this)
                        onContextRequested: {
                            keptPlaylistMenu.playlistId = modelData.ext_id
                            keptPlaylistMenu.playlistName = modelData.title
                            keptPlaylistMenu.popup()
                        }
                    }
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
        objectName: "channelHeader"
        anchors.left: sidebar.right
        // The panel is drawn over this view, so step aside for it the way the
        // grid does rather than running underneath it. The banner is the
        // widest thing in the window and it was the one piece still doing so.
        anchors.right: detailPanel.visible ? detailPanel.left : parent.right
        anchors.top: liveBar.visible ? liveBar.bottom : parent.top
        anchors.topMargin: liveBar.visible ? 0 : banner.height
        info: App.channelInfo
        visible: App.viewKind === "channel"
        // Walk the history if there is any, so the button does what its
        // label promises. Falling back to the feed keeps it working on the
        // very first view, where there is nothing behind it yet.
        onCloseRequested: App.canGoBack ? App.goBack() : App.selectGroup(-1)
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
        // The panel is drawn over this view, so step aside for it the way the
        // grid does rather than running underneath it.
        anchors.right: detailPanel.visible ? detailPanel.left : parent.right
        anchors.top: liveBar.visible ? liveBar.bottom : parent.top
        anchors.topMargin: liveBar.visible ? 0 : banner.height
        anchors.bottom: miniPlayer.top
    }

    // Both pages are a column of rows rather than a grid of cards, and both
    // scrolled at whatever a Flickable does by itself, which is a third of
    // what a notch moves anywhere else in the window.
    SmoothScroll {
        flickable: debugView.scrolls
        step: grid.cellHeight * App.scrollRowsPerNotch
    }

    SettingsView {
        id: settingsView
        objectName: "settingsView"
        visible: App.viewKind === "settings"
        anchors.left: sidebar.right
        // The panel is drawn over this view, so step aside for it the way the
        // grid does rather than running underneath it.
        anchors.right: detailPanel.visible ? detailPanel.left : parent.right
        anchors.top: liveBar.visible ? liveBar.bottom : parent.top
        anchors.topMargin: liveBar.visible ? 0 : banner.height
        anchors.bottom: miniPlayer.top
        onPlaylistsRequested: playlistChooser.open()
    }

    SmoothScroll {
        flickable: settingsView.scrolls
        step: grid.cellHeight * App.scrollRowsPerNotch
    }

    // The row above the cards, for the two views that have one. Outside the
    // grid rather than its header: a view builds and drops its header as it
    // scrolls, and a header whose height is decided by a binding comes back
    // measured at nothing, which is how it went missing on the way back up.
    // Out here it is also simply always there, which is what it is for.
    Item {
        id: viewBar
        objectName: "gridHeader"
        readonly property bool onHistory: App.viewKind === "history"
        readonly property bool onSuggestions: App.viewKind === "recommended"
        readonly property bool onChannel: App.viewKind === "channel"
        // Only a playlist opened off a channel page. Your own were not opened
        // from anywhere and have nowhere to go back to.
        readonly property bool onPlaylist: App.viewKind === "playlist"
                                           && App.playlistView.channel_key !== undefined

        visible: onHistory || onSuggestions || onChannel || onPlaylist
        height: visible ? 42 : 0
        anchors.left: grid.left
        anchors.right: grid.right
        anchors.top: channelHeader.visible ? channelHeader.bottom
                                           : (liveBar.visible ? liveBar.bottom : parent.top)
        anchors.topMargin: channelHeader.visible ? 8
                                                 : (liveBar.visible ? 10 : banner.height + 10)

        Row {
            objectName: "historyHeader"
            visible: viewBar.onHistory
            anchors.left: parent.left
            anchors.leftMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            FlatButton {
                objectName: "historyVideos"
                text: "Videos"
                accent: !App.historyShowsMusic
                onClicked: App.showMusicInHistory(false)
            }
            FlatButton {
                objectName: "historyMusic"
                text: "Music"
                accent: App.historyShowsMusic
                onClicked: App.showMusicInHistory(true)
            }
        }

        // A channel has two halves. Walking between them is not walking
        // anywhere, so it is a pair of buttons rather than a view of its own.
        Row {
            objectName: "channelTabs"
            visible: viewBar.onChannel
            anchors.left: parent.left
            anchors.leftMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            FlatButton {
                objectName: "channelVideos"
                text: "Videos"
                accent: App.channelTab === "videos"
                onClicked: App.showChannelTab("videos")
            }
            // Only for a channel with a stream stored. Most channels have
            // never streamed, and a button onto an empty half is worse than
            // no button.
            FlatButton {
                objectName: "channelStreamsTab"
                visible: App.channelInfo.streams > 0
                text: "Streams"
                accent: App.channelTab === "streams"
                onClicked: App.showChannelTab("streams")
            }
            FlatButton {
                objectName: "channelPlaylistsTab"
                text: "Playlists"
                accent: App.channelTab === "playlists"
                onClicked: App.showChannelTab("playlists")
            }
        }

        // Somebody else's playlist, which was reached from their page and can
        // be kept or left. The mouse has a button for going back and not
        // every mouse does, so the way back is on the screen as well.
        Item {
            objectName: "playlistHeader"
            visible: viewBar.onPlaylist
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            height: 28

            FlatButton {
                id: backToChannel
                objectName: "playlistBack"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: "\u2190 " + (App.playlistView.channel_title || "channel")
                onClicked: App.openChannelPlaylists(App.playlistView.channel_key)
            }

            Label {
                objectName: "playlistHeaderTitle"
                anchors.left: backToChannel.right
                anchors.leftMargin: 12
                anchors.right: keepThis.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: App.playlistView.title || ""
                color: Theme.colors.text
                font.pixelSize: 13
                elide: Text.ElideRight
            }

            FlatButton {
                id: keepThis
                objectName: "playlistKeep"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: App.playlistView.kept ? "Kept" : "Keep"
                accent: App.playlistView.kept === true
                onClicked: App.keepPlaylist(App.playlistView.ext_id,
                                            !App.playlistView.kept)
            }
        }

        // The suggestions say where they came from and how old they
        // are, and the one thing that can be done about that sits
        // beside them rather than in the bar.
        Item {
            objectName: "recommendedHeader"
            visible: viewBar.onSuggestions
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            height: 28

            Label {
                objectName: "recommendedState"
                anchors.left: parent.left
                anchors.right: askAgain.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: App.recommendedText
                color: Theme.colors.textMuted
                font.pixelSize: 12
                elide: Text.ElideRight
            }

            FlatButton {
                id: askAgain
                objectName: "recommendedRefresh"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: "Fresh recommendations"
                // Not tied to App.busy. That flag belongs to the feed
                // poll, which has nothing to do with this page, and a
                // button that greys out once a minute for no visible
                // reason reads as broken.
                onClicked: App.refreshRecommended()
            }
        }
    }

    // The same row of buttons a group gets, which is not the bar above.
    //
    // History keeps its bar in place because the two words there are the whole
    // page: which history you are reading. A group's three are a filter over a
    // grid that is scrolled, so they go with the reading and come back the
    // moment you turn round. They are drawn over the top of the grid, and the
    // grid holds the same first row offset history has by carrying it as a
    // content margin instead, so the cards start in exactly the same place in
    // both. Nothing ever passes under the buttons at rest, since the margin is
    // as tall as they are; the ground under them appears only once the grid
    // has been scrolled and there is a card behind them to cover.
    Item {
        id: groupBarClip
        objectName: "groupBarClip"
        visible: App.viewKind === "group"
        clip: true
        z: 3
        anchors.left: grid.left
        anchors.right: grid.right
        anchors.top: grid.top
        height: barHeight + gap

        readonly property int barHeight: 42
        readonly property int gap: 8
        // How far the grid has been scrolled past its own top. Zero at rest,
        // whatever the content margin is.
        readonly property real past: Math.max(0, grid.contentY + grid.topMargin)
        // Pushed out of the way. Set from movement rather than bound to it, so
        // it survives the scroll stopping halfway.
        property bool away: false
        property real lastY: 0

        onVisibleChanged: { away = false; lastY = grid.contentY }

        // Arriving on another group is a fresh page, so the buttons are back
        // whatever the last one was scrolled to.
        Connections {
            target: App
            function onViewChanged() {
                groupBarClip.away = false
                groupBarClip.lastY = grid.contentY
            }
        }

        Connections {
            target: grid
            function onContentYChanged() {
                if (!groupBarClip.visible)
                    return
                var moved = grid.contentY - groupBarClip.lastY
                groupBarClip.lastY = grid.contentY
                // A few pixels of slack, or the settling of a glide counts as
                // a direction of its own.
                if (moved > 3 && groupBarClip.past > groupBarClip.barHeight)
                    groupBarClip.away = true
                else if (moved < -3)
                    groupBarClip.away = false
                if (groupBarClip.past <= 0)
                    groupBarClip.away = false
            }
        }

        Item {
            id: groupBar
            objectName: "groupBar"
            anchors.left: parent.left
            anchors.right: parent.right
            height: parent.barHeight + parent.gap
            // Its own y rather than an anchor, since an anchor cannot be
            // animated and the point of it is that it slides.
            y: groupBarClip.away ? -height : 0
            // The ground below is the whole window and is held still against
            // it, so without this it stayed behind when the buttons left and
            // went on painting a strip of empty window over the top of the
            // grid, hiding whatever card was passing under. Clipped to the
            // strip, it goes exactly where the strip goes and stays lined up
            // with the window while it is there.
            clip: true
            // Out of the way means out of reach as well, so a press cannot
            // land on a button that is not on the screen.
            enabled: !groupBarClip.away
            Behavior on y { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

            // The window's own ground, held still against the window while
            // the buttons over it slide, so the strip they sit in is painted
            // exactly what the window is painted at that height and a card
            // passing under them is hidden without a seam.
            //
            // A flat Theme.colors.background here was wrong and looked it.
            // That role is the base colour UNDER the gradient wash, and on a
            // washed theme, which is twelve of the fourteen shipped, the
            // window at this height is a colour the wash decides and not that
            // one. It only showed once the grid had been scrolled and the
            // ground came in, which is what he saw.
            //
            // Sized and placed off the window's own ground rather than off the
            // window, because inside an ApplicationWindow a child's parent is
            // the content item and the toolbar is the window's header, so the
            // two differ by the height of that bar.
            ThemeBackground {
                objectName: "groupBarGround"
                x: -(groupBarClip.x + groupBar.x)
                y: -(groupBarClip.y + groupBar.y)
                width: windowGround.width
                height: windowGround.height
            }

            // A line under the buttons once there is a card behind them, so
            // the row reads as something over the grid rather than a gap in
            // it. Nothing to divide while the strip above the first card is
            // empty, which is what it is at rest.
            Rectangle {
                objectName: "groupBarEdge"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.colors.border
                opacity: groupBarClip.past > 0 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 120 } }
            }

            Row {
                objectName: "groupHeader"
                anchors.left: parent.left
                anchors.leftMargin: 6
                anchors.top: parent.top
                anchors.topMargin: (groupBarClip.barHeight - height) / 2
                spacing: 8

                FlatButton {
                    objectName: "groupAll"
                    text: "All"
                    accent: App.groupShows === "all"
                    onClicked: App.showInGroup("all")
                }
                FlatButton {
                    objectName: "groupVideos"
                    text: "Videos"
                    accent: App.groupShows === "videos"
                    onClicked: App.showInGroup("videos")
                }
                FlatButton {
                    objectName: "groupStreams"
                    text: "Streams"
                    accent: App.groupShows === "streams"
                    onClicked: App.showInGroup("streams")
                }
            }
        }
    }

    ChannelPlaylists {
        id: channelPlaylistsView
        objectName: "channelPlaylistsView"
        visible: App.viewKind === "channel" && App.channelTab === "playlists"
        anchors.left: grid.left
        anchors.right: grid.right
        anchors.top: grid.top
        anchors.bottom: grid.bottom
    }

    // The same distance a notch moves the videos. Beside the view rather than
    // inside it, since a child of a Flickable rides in the content.
    SmoothScroll {
        flickable: channelPlaylistsView
        step: channelPlaylistsView.rowHeight * App.scrollRowsPerNotch
    }

    GridView {
        id: grid
        objectName: "grid"
        visible: App.viewKind !== "music" && App.viewKind !== "debug"
                 && App.viewKind !== "settings"
                 && !(App.viewKind === "channel" && App.channelTab === "playlists")
        anchors.left: sidebar.right
        anchors.right: detailPanel.visible ? detailPanel.left : parent.right
        // Under the row above, which holds the place the grid used to take
        // even when it has nothing to show, so nothing moves when it does.
        anchors.top: viewBar.bottom
        anchors.bottom: miniPlayer.top
        anchors.topMargin: viewBar.visible ? 8 : 0
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        clip: true
        // A group has its buttons drawn over the grid rather than above it, so
        // the room they take is content margin here instead. Same number
        // either way, so the first row of a group and the first row of the
        // history start at the same height.
        topMargin: groupBarClip.visible ? groupBarClip.height : 0

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

        // A private or a deleted entry never reaches the grid as a card, so
        // this is the only place either is mentioned at all. It sits after
        // the last row rather than always on screen, since it only matters
        // once you have scrolled far enough to wonder where a video went.
        // The history answers two questions with one view, so it says which
        // one it is answering and lets the other be asked. It rides above the
        // first row rather than sitting in the toolbar, which is already full
        // and has nothing to do with this view.
        footer: Component {
            Item {
                width: grid.width
                height: App.playlistSkippedText.length > 0 ? 34 : 0
                visible: App.playlistSkippedText.length > 0

                Label {
                    anchors.centerIn: parent
                    horizontalAlignment: Text.AlignHCenter
                    color: Theme.colors.textMuted
                    font.pixelSize: 13
                    text: App.playlistSkippedText
                }
            }
        }

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
                wasLive: model.wasLive
                isMembers: model.isMembers
                isUpcoming: model.isUpcoming
                scheduledText: model.scheduledText
                startsText: model.startsText
                // Where a press already listens, the headphone offers nothing.
                canListen: !App.pressIsMusic
                progress: model.progress
                starting: App.startingKey === model.key
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

    ThemedMenu {
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
        ThemedMenuItem {
            text: "Play in mpv"
            onTriggered: { App.play(root.menuKey); videoMenu.dismiss() }
        }
        ThemedMenuItem {
            text: "Open the channel"
            onTriggered: { App.openChannel(root.menuChannelKey); videoMenu.dismiss() }
        }
        ThemedMenuItem {
            objectName: "musicFavoriteEntry"
            // Only where a video is a song already, which is a playlist marked
            // as music and the listening history. Anywhere else a video is a
            // video and music favourites would mean nothing.
            visible: App.pressIsMusic
            height: visible ? implicitHeight : 0
            text: App.isFavorite(root.menuKey) ? "Remove from music favorites"
                                               : "Add to music favorites"
            onTriggered: { App.favoriteVideo(root.menuKey); videoMenu.dismiss() }
        }
        ThemedMenuItem {
            objectName: "copyLinkEntry"
            text: "Share"
            onTriggered: { App.copyLink(root.menuKey); videoMenu.dismiss() }
        }
        ThemedMenuItem {
            text: "Groups for this channel"
            onTriggered: {
                var key = root.menuChannelKey
                videoMenu.dismiss()
                root.askForGroups(key)
            }
        }
        ThemedMenuItem {
            text: root.menuWatched ? "Mark as not watched" : "Mark as watched"
            onTriggered: {
                if (root.menuWatched)
                    App.markUnwatched(root.menuKey)
                else
                    App.markWatched(root.menuKey)
                videoMenu.dismiss()
            }
        }

        ThemedMenuSeparator { id: boxSeparator }

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
            delegate: ThemedMenuItem {
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

        ThemedMenuItem {
            text: "Put in a new box"
            onTriggered: { videoMenu.dismiss(); root.askForName("box", -1, root.menuKey, "") }
        }
    }

    // The groups one channel is in, ticked, so one menu both adds and removes.
    // Opened from a video's menu and from the channel page.
    ThemedMenu {
        id: channelGroupMenu
        objectName: "channelGroupMenu"
        property string channelKey: ""

        Instantiator {
            id: channelGroupEntries
            // All is offered like any other list. It is not a row in the
            // groups table, but it holds channels in the sense this menu is
            // asking about, and a channel followed here has every reason to
            // sit beside a subscribed one.
            model: App.groups
            // A delegate created here does not inherit this file's id scope,
            // so the menu is handed to each entry from out here.
            onObjectAdded: (index, object) => {
                object.owner = channelGroupMenu
                channelGroupMenu.insertItem(index, object)
            }
            onObjectRemoved: (index, object) => channelGroupMenu.removeItem(object)
            delegate: ThemedMenuItem {
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

        ThemedMenuItem {
            text: "Put in a new group"
            onTriggered: {
                var key = channelGroupMenu.channelKey
                channelGroupMenu.dismiss()
                root.askForName("group", -1, key, "")
            }
        }
    }

    ThemedMenu {
        id: playlistMenu
        objectName: "playlistMenu"

        ThemedMenuItem {
            text: "Read the list again"
            onTriggered: { App.refreshPlaylists(); playlistMenu.dismiss() }
        }
        ThemedMenuItem {
            text: "Playlist settings"
            onTriggered: { playlistMenu.dismiss(); playlistChooser.open() }
        }
    }

    ThemedMenu {
        id: playlistRowMenu
        objectName: "playlistRowMenu"
        property string playlistId: ""
        property string playlistName: ""
        property bool isMusic: false

        ThemedMenuItem {
            objectName: "playlistMusicEntry"
            // A playlist of music is listened to rather than watched, so a
            // press on one of its videos goes where the headphone goes.
            text: playlistRowMenu.isMusic ? "Stop treating it as music"
                                          : "Treat it as music"
            onTriggered: {
                App.setPlaylistMusic(playlistRowMenu.playlistId, !playlistRowMenu.isMusic)
                playlistRowMenu.dismiss()
            }
        }
        ThemedMenuItem {
            text: "Read it again"
            onTriggered: {
                var id = playlistRowMenu.playlistId
                playlistRowMenu.dismiss()
                App.selectPlaylist(id)
                App.refreshPlaylist()
            }
        }
        ThemedMenuItem {
            // Hiding is not forgetting. It keeps its contents and comes back
            // from the chooser.
            text: "Hide it"
            onTriggered: {
                App.setPlaylistHidden(playlistRowMenu.playlistId, true)
                playlistRowMenu.dismiss()
            }
        }
    }

    ThemedMenu {
        id: channelsMenu
        objectName: "channelsMenu"
        implicitWidth: 190

        ThemedMenuItem {
            text: "Follow a channel"
            onTriggered: { channelsMenu.dismiss(); followChannel.open() }
        }
        ThemedMenuItem {
            text: "New group"
            onTriggered: { channelsMenu.dismiss(); root.askForName("group", -1, "", "") }
        }
    }

    ThemedMenu {
        id: keptPlaylistMenu
        objectName: "keptPlaylistMenu"
        property string playlistId: ""
        property string playlistName: ""

        ThemedMenuItem {
            text: "Read it again"
            onTriggered: {
                var id = keptPlaylistMenu.playlistId
                keptPlaylistMenu.dismiss()
                App.selectPlaylist(id)
                App.refreshPlaylist()
            }
        }
        ThemedMenuItem {
            // The playlist itself is untouched. This is only whether it is
            // kept here, the way a group keeps its channels.
            text: "Let it go"
            onTriggered: {
                var id = keptPlaylistMenu.playlistId
                keptPlaylistMenu.dismiss()
                App.keepPlaylist(id, false)
            }
        }
    }

    ThemedMenu {
        id: groupMenu
        objectName: "groupMenu"
        property int groupId: -1
        property string groupName: ""
        readonly property bool isAll: groupId < 0

        // All is not a group anybody made. It cannot be renamed, moved or
        // deleted, and the one thing it shares with a group is who is in it.
        ThemedMenuItem {
            visible: !groupMenu.isAll
            height: visible ? implicitHeight : 0
            text: "Rename"
            onTriggered: {
                var id = groupMenu.groupId, name = groupMenu.groupName
                groupMenu.dismiss()
                root.askForName("group", id, "", name)
            }
        }
        ThemedMenuItem {
            visible: !groupMenu.isAll
            height: visible ? implicitHeight : 0
            text: "Move up"
            onTriggered: { App.moveGroup(groupMenu.groupId, -1); groupMenu.dismiss() }
        }
        ThemedMenuItem {
            visible: !groupMenu.isAll
            height: visible ? implicitHeight : 0
            text: "Move down"
            onTriggered: { App.moveGroup(groupMenu.groupId, 1); groupMenu.dismiss() }
        }
        ThemedMenuItem {
            text: groupMenu.isAll ? "Manage All" : "Manage the group"
            onTriggered: {
                var id = groupMenu.groupId, name = groupMenu.groupName
                groupMenu.dismiss()
                manageGroup.groupId = id
                manageGroup.groupName = name
                manageGroup.open()
            }
        }
        ThemedMenuItem {
            // The channels themselves are untouched, as with a box and its
            // videos.
            visible: !groupMenu.isAll
            height: visible ? implicitHeight : 0
            text: "Delete the group"
            onTriggered: {
                var id = groupMenu.groupId, name = groupMenu.groupName
                groupMenu.dismiss()
                confirmDelete.ask("group", id, name)
            }
        }
    }

    ThemedMenu {
        id: boxMenu
        objectName: "boxMenu"
        property int boxId: -1
        property string boxName: ""

        ThemedMenuItem {
            text: "Rename"
            onTriggered: {
                var id = boxMenu.boxId, name = boxMenu.boxName
                boxMenu.dismiss()
                root.askForName("box", id, "", name)
            }
        }
        ThemedMenuItem {
            text: "Move up"
            onTriggered: { App.moveBox(boxMenu.boxId, -1); boxMenu.dismiss() }
        }
        ThemedMenuItem {
            text: "Move down"
            onTriggered: { App.moveBox(boxMenu.boxId, 1); boxMenu.dismiss() }
        }
        ThemedMenuItem {
            // The videos themselves are untouched, as with a group and its
            // channels.
            text: "Delete the box"
            onTriggered: {
                var id = boxMenu.boxId, name = boxMenu.boxName
                boxMenu.dismiss()
                confirmDelete.ask("box", id, name)
            }
        }
    }

    ManageGroup {
        id: manageGroup
    }

    ConfirmDelete {
        id: confirmDelete
    }

    FollowChannel {
        id: followChannel
    }

    // The ground behind the getting started pages. Drawn here rather than by
    // the popup, because the overlay a modal popup brings swallows every press
    // in the window, and this window has no frame of its own, so that takes
    // away moving and resizing it while the pages are open.
    //
    // So the dimming is a plain rectangle, which accepts nothing, and an area
    // inside it swallows what would otherwise reach a card. Both live in the
    // window's content, which is what makes this work: the toolbar is the
    // window's header and the resize grips are in the overlay, so neither is
    // covered by either of them. The bar can still be taken hold of, the
    // window buttons still work, the edges still resize, and a press anywhere
    // else stops here instead of playing something behind the pages.
    Rectangle {
        objectName: "wizardDim"
        anchors.fill: parent
        visible: App.wizardOpen
        color: Qt.rgba(0, 0, 0, 0.45)
        z: 60

        MouseArea {
            objectName: "wizardShield"
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            hoverEnabled: true
            // Nothing at all. The point is that the press stops here rather
            // than reaching a card and playing something behind the pages.
            onWheel: function (event) { event.accepted = true }
        }
    }

    // Shown on a fresh install and never again once there is something to
    // show. Last of the popups, so it is drawn over the rest of them.
    Wizard {
        id: wizard
    }

    // A checklist rather than a menu, because a menu of a hundred playlists is
    // not something anyone can find anything in.
    Popup {
        id: playlistChooser
        objectName: "playlistChooser"
        anchors.centerIn: parent
        // The same size as the one for the linked playlists below. Two
        // windows that do the same thing to two lists are one window as far
        // as the eye is concerned, and a step in size between them reads as a
        // step in importance.
        width: Math.min(560, root.width - 80)
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

                    // A tick here sends a press on one of this playlist's
                    // videos to the music player instead of mpv. The word is
                    // a label of its own rather than the box's own text,
                    // which this style draws in a colour of its choosing.
                    CheckBox {
                        id: musicBox
                        objectName: "chooserMusicBox"
                        anchors.right: order.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        checked: entry.modelData.is_music === 1
                        onToggled: {
                            App.setPlaylistMusic(entry.modelData.ext_id, checked)
                            playlistChooser.reload()
                        }
                    }

                    Label {
                        id: musicLabel
                        anchors.right: musicBox.left
                        anchors.rightMargin: 2
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Music"
                        color: musicBox.checked ? Theme.colors.accent : Theme.colors.textMuted
                        font.pixelSize: 11
                    }

                    Label {
                        id: countLabel
                        anchors.right: musicLabel.left
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

    // The same shape as the chooser above, for the playlists kept off somebody
    // else's channel. Without the tick that hides one: these are here because
    // they were kept, and the thing to do with one you no longer want is to
    // let it go rather than to hide it.
    Popup {
        id: keptChooser
        objectName: "keptChooser"
        anchors.centerIn: parent
        width: Math.min(560, root.width - 80)
        height: Math.min(520, root.height - 80)
        padding: 16
        modal: true
        focus: true
        onOpened: reload()
        background: Rectangle {
            radius: 8
            color: Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border
        }

        // A snapshot, like the other one. A live model rebuilds itself under
        // the hand that just pressed an arrow and sends the list to the top.
        property var all: []

        function reload() { all = App.keptPlaylists }

        Column {
            anchors.fill: parent
            spacing: 10

            Label {
                text: "Linked playlists"
                color: Theme.colors.text
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }

            Label {
                width: parent.width
                text: "Playlists you kept from somebody else's channel."
                color: Theme.colors.textMuted
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }

            ListView {
                id: keptList
                objectName: "keptList"
                width: parent.width
                height: parent.height - y - keptCloseRow.height - 20
                clip: true
                model: keptChooser.all
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Item {
                    id: keptEntry
                    required property var modelData
                    width: keptList.width
                    height: 34

                    Label {
                        id: keptName
                        anchors.left: parent.left
                        anchors.leftMargin: 4
                        anchors.right: keptCount.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: keptEntry.modelData.title
                        color: Theme.colors.text
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Label {
                        id: keptCount
                        anchors.right: keptMusicLabel.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: keptEntry.modelData.items ? keptEntry.modelData.items + " videos" : ""
                        color: Theme.colors.textMuted
                        font.pixelSize: 11
                    }

                    Label {
                        id: keptMusicLabel
                        anchors.right: keptMusicBox.left
                        anchors.rightMargin: 2
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Music"
                        color: keptMusicBox.checked ? Theme.colors.accent : Theme.colors.textMuted
                        font.pixelSize: 11
                    }

                    CheckBox {
                        id: keptMusicBox
                        objectName: "keptMusicBox"
                        anchors.right: keptOrder.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        checked: keptEntry.modelData.is_music === 1
                        onToggled: {
                            App.setPlaylistMusic(keptEntry.modelData.ext_id, checked)
                            keptChooser.reload()
                        }
                    }

                    Row {
                        id: keptOrder
                        anchors.right: keptDrop.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        FlatButton {
                            objectName: "keptUp"
                            text: "\u25b2"
                            onClicked: {
                                App.movePlaylist(keptEntry.modelData.ext_id, -1)
                                keptChooser.reload()
                            }
                        }
                        FlatButton {
                            objectName: "keptDown"
                            text: "\u25bc"
                            onClicked: {
                                App.movePlaylist(keptEntry.modelData.ext_id, 1)
                                keptChooser.reload()
                            }
                        }
                    }

                    FlatButton {
                        id: keptDrop
                        objectName: "keptDrop"
                        anchors.right: parent.right
                        anchors.rightMargin: 2
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Let it go"
                        onClicked: {
                            App.keepPlaylist(keptEntry.modelData.ext_id, false)
                            keptChooser.reload()
                        }
                    }
                }
            }

            Label {
                visible: keptChooser.all.length === 0
                width: parent.width
                text: "Nothing kept. A playlist on a channel page has a Keep button."
                color: Theme.colors.textMuted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }

            Row {
                id: keptCloseRow
                spacing: 8
                anchors.right: parent.right

                FlatButton {
                    text: "Done"
                    accent: true
                    onClicked: keptChooser.close()
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
