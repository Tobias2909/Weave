import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Everything that arranges the music page, gathered off it. The page itself
// is for listening, and the shelves were already a long column without a
// pair of arrows on every one of them. Opened from the dots beside Music in
// the sidebar.
Item {
    id: view

    // A box is named, renamed and thrown away in the window's own popups, so
    // they are asked for from here rather than opened from here.
    signal newBoxRequested()
    signal renameRequested(int boxId, string name)
    signal deleteRequested(int boxId, string name)

    readonly property Flickable scrolls: sheet
    // One width for the left hand word of every stated fact, the same as the
    // main settings page.
    readonly property int wordWidth: 130

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true

            Label {
                text: "Music settings"
                color: Theme.colors.text
                font.pixelSize: 18
                font.weight: Font.Bold
            }

            Item { Layout.fillWidth: true }

            FlatButton {
                objectName: "musicSettingsBack"
                text: "Back to music"
                onClicked: App.showMusic()
            }
        }

        Flickable {
            id: sheet
            objectName: "musicSettingsSheet"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: body.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 10 }

            Column {
                id: body
                width: sheet.width - 16
                spacing: 14

                // ---- boxes ----------------------------------------------------
                Rectangle {
                    width: body.width
                    height: boxesCard.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: boxesCard
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "Boxes"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Label {
                            width: parent.width
                            text: "Songs thrown together by hand, for tonight or for later. "
                                  + "Put one in from a song's right click menu, or keep the "
                                  + "whole queue from beside its Clear. Favorites is the first "
                                  + "box and always stays. A box ticked Keep on disk has its "
                                  + "songs written to disk as they play, so they start at once "
                                  + "the next time."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        ListView {
                            id: boxList
                            objectName: "musicBoxList"
                            width: parent.width
                            height: count * 36
                            interactive: false
                            acceptedButtons: Qt.NoButton
                            model: App.musicBoxes

                            // Favorites stays first, so nothing is dropped
                            // above it.
                            DragOrder {
                                id: boxOrder
                                objectName: "musicBoxOrder"
                                parent: boxList
                                list: boxList
                                rowHeight: 36
                                rowCount: boxList.count
                                inset: 0
                                onDropped: (from, to) => {
                                    var boxes = App.musicBoxes
                                    var target = Math.max(1, to)
                                    if (from !== target)
                                        App.moveMusicBoxTo(boxes[from].id, boxes[target].id)
                                }
                            }

                            delegate: Item {
                                id: boxRow
                                objectName: "musicBoxRow"
                                required property var modelData
                                required property int index
                                width: boxList.width
                                height: 36
                                opacity: boxOrder.from === boxRow.index ? 0.35 : 1.0

                                DragGrip {
                                    id: boxGrip
                                    objectName: "musicBoxGrip"
                                    visible: !boxRow.modelData.fixed
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    onBegan: (y, pressY) => boxOrder.begin(boxRow.index,
                                                                           boxRow.modelData.name,
                                                                           y, pressY)
                                    onCarried: (y) => boxOrder.carry(y)
                                    onEnded: boxOrder.finish()
                                }

                                Label {
                                    id: boxName
                                    anchors.left: parent.left
                                    anchors.leftMargin: 24
                                    anchors.right: boxCount.left
                                    anchors.rightMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: boxRow.modelData.fixed
                                          ? "♥  " + boxRow.modelData.name
                                          : boxRow.modelData.name
                                    color: Theme.colors.text
                                    font.pixelSize: 13
                                    elide: Text.ElideRight
                                }

                                Label {
                                    id: boxCount
                                    anchors.right: keepLabel.left
                                    anchors.rightMargin: 14
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: boxRow.modelData.count === 1
                                          ? "1 song" : boxRow.modelData.count + " songs"
                                    color: Theme.colors.textMuted
                                    font.pixelSize: 11
                                }

                                Label {
                                    id: keepLabel
                                    anchors.right: keepBox.left
                                    anchors.rightMargin: 2
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "Keep on disk"
                                    color: keepBox.checked ? Theme.colors.accent
                                                           : Theme.colors.textMuted
                                    font.pixelSize: 11
                                }

                                CheckBox {
                                    id: keepBox
                                    objectName: "musicBoxKeep"
                                    anchors.right: renameButton.left
                                    anchors.rightMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: boxRow.modelData.keep
                                    onToggled: App.setMusicBoxKeep(boxRow.modelData.id, checked)

                                    HintBubble {
                                        parent: keepBox
                                        shown: keepBox.hovered
                                        words: "Write its songs to disk as they play, so the "
                                               + "next play starts at once"
                                    }
                                }

                                FlatButton {
                                    id: renameButton
                                    objectName: "musicBoxRename"
                                    anchors.right: deleteButton.left
                                    anchors.rightMargin: 6
                                    anchors.verticalCenter: parent.verticalCenter
                                    // Kept in its place for Favorites, so the
                                    // boxes beside each other line up.
                                    opacity: boxRow.modelData.fixed ? 0 : 1
                                    enabled: !boxRow.modelData.fixed
                                    text: "Rename"
                                    onClicked: view.renameRequested(boxRow.modelData.id,
                                                                    boxRow.modelData.name)
                                }

                                FlatButton {
                                    id: deleteButton
                                    objectName: "musicBoxDelete"
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    opacity: boxRow.modelData.fixed ? 0 : 1
                                    enabled: !boxRow.modelData.fixed
                                    text: "Delete"
                                    onClicked: view.deleteRequested(boxRow.modelData.id,
                                                                    boxRow.modelData.name)
                                }
                            }
                        }

                        FlatButton {
                            objectName: "musicBoxNew"
                            text: "+  New box"
                            onClicked: view.newBoxRequested()
                        }
                    }
                }

                // ---- shelves --------------------------------------------------
                Rectangle {
                    width: body.width
                    height: shelvesCard.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: shelvesCard
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "Shelves"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        Label {
                            width: parent.width
                            text: "What the music page shows, top to bottom. Untick one to put "
                                  + "it out of sight, and drag one by its row to change the order. "
                                  + "A shelf YouTube Music adds later goes on the end."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Label {
                            visible: shelfList.count === 0
                            width: parent.width
                            text: "The shelves have not been read yet. Open the music page once "
                                  + "and they are listed here."
                            color: Theme.colors.textMuted
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }

                        ListView {
                            id: shelfList
                            objectName: "shelfSettingsList"
                            width: parent.width
                            height: count * 32
                            interactive: false
                            acceptedButtons: Qt.NoButton
                            model: App.shelfSettings

                            DragOrder {
                                id: shelfOrder
                                objectName: "shelfOrder"
                                parent: shelfList
                                list: shelfList
                                rowHeight: 32
                                rowCount: shelfList.count
                                inset: 0
                                onDropped: (from, to) => {
                                    var shelves = App.shelfSettings
                                    App.moveShelfTo(shelves[from].title, shelves[to].title)
                                }
                            }

                            delegate: Item {
                                id: shelfRow
                                objectName: "shelfSettingsRow"
                                required property var modelData
                                required property int index
                                width: shelfList.width
                                height: 32
                                opacity: shelfOrder.from === shelfRow.index ? 0.35 : 1.0

                                DragGrip {
                                    id: shelfGrip
                                    objectName: "shelfGrip"
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    onBegan: (y, pressY) => shelfOrder.begin(shelfRow.index,
                                                                             shelfRow.modelData.title,
                                                                             y, pressY)
                                    onCarried: (y) => shelfOrder.carry(y)
                                    onEnded: shelfOrder.finish()
                                }

                                CheckBox {
                                    id: showBox
                                    objectName: "shelfShowBox"
                                    anchors.left: shelfGrip.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: !shelfRow.modelData.hidden
                                    onToggled: App.setShelfHidden(shelfRow.modelData.title, !checked)

                                    HintBubble {
                                        parent: showBox
                                        shown: showBox.hovered
                                        words: "Show it on the music page"
                                    }
                                }

                                Label {
                                    anchors.left: showBox.right
                                    anchors.leftMargin: 4
                                    anchors.right: shelfCount.left
                                    anchors.rightMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: shelfRow.modelData.title
                                    color: shelfRow.modelData.hidden ? Theme.colors.textMuted
                                                                     : Theme.colors.text
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }

                                Label {
                                    id: shelfCount
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: shelfRow.modelData.count === 1
                                          ? "1 entry" : shelfRow.modelData.count + " entries"
                                    color: Theme.colors.textMuted
                                    font.pixelSize: 11
                                }
                            }
                        }

                        FlatButton {
                            objectName: "resetShelfOrder"
                            text: "Put back YouTube Music's order"
                            onClicked: App.resetShelfOrder()
                        }
                    }
                }

                // ---- what is kept and what is told ---------------------------
                Rectangle {
                    width: body.width
                    height: keeping.height + 28
                    radius: 6
                    color: Theme.colors.surface
                    border.width: 1
                    border.color: Theme.colors.border

                    Column {
                        id: keeping
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 10

                        Label {
                            text: "Videos and listening"
                            color: Theme.colors.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }

                        SettingsHeading { text: "Music videos on disk"; rule: false }

                        Label {
                            width: parent.width
                            text: "The music player fetches a picture only while the Now "
                                  + "playing page is open, and never for anything over a "
                                  + "quarter of an hour. This is the tallest it will ask "
                                  + "for. A song offered only smaller is shown at what it "
                                  + "has, and a new ceiling takes hold at the next song."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Quality"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                id: videoCeilingButton
                                objectName: "videoCeiling"
                                text: App.videoCeilingText + "  \u25be"
                                onClicked: videoCeilingMenu.popup(videoCeilingButton, 0,
                                                                  videoCeilingButton.height + 2)

                                ThemedMenu {
                                    id: videoCeilingMenu
                                    objectName: "videoCeilingMenu"
                                    implicitWidth: 160

                                    Repeater {
                                        model: App.videoChoices

                                        ThemedMenuItem {
                                            required property var modelData

                                            // The tick marks the one in force, the same as
                                            // the picture cache's own menu does it.
                                            text: modelData.height === App.videoCeiling
                                                  ? modelData.label + "   \u2713"
                                                  : modelData.label
                                            onTriggered: {
                                                App.setVideoCeiling(modelData.height)
                                                videoCeilingMenu.dismiss()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Label {
                            width: parent.width
                            text: "A song in a box kept on disk has its video written to "
                                  + "disk the first time you watch it, so every play after "
                                  + "that starts at once and pulls nothing. Only songs in a "
                                  + "box ticked Keep on disk above, and only while a page is "
                                  + "open to show a picture. The one played longest ago goes "
                                  + "first when the room runs out."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Kept"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            Label {
                                objectName: "videosKept"
                                height: 28
                                text: App.videosKeptText
                                color: Theme.colors.text
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Ceiling"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                id: keepCeilingButton
                                objectName: "videoKeepCeiling"
                                // Written on the Python side, the same way
                                // every other sentence in this window is, so
                                // the button and the line above it cannot
                                // disagree about what a gigabyte is.
                                text: App.videoKeepCeilingText + "  \u25be"
                                onClicked: keepCeilingMenu.popup(keepCeilingButton, 0,
                                                                 keepCeilingButton.height + 2)

                                ThemedMenu {
                                    id: keepCeilingMenu
                                    objectName: "videoKeepCeilingMenu"
                                    implicitWidth: 160

                                    Repeater {
                                        model: App.videoKeepChoices

                                        ThemedMenuItem {
                                            required property var modelData

                                            text: modelData.mb === App.videoKeepCeiling
                                                  ? modelData.label + "   \u2713"
                                                  : modelData.label
                                            onTriggered: {
                                                App.setVideoKeepCeiling(modelData.mb)
                                                keepCeilingMenu.dismiss()
                                            }
                                        }
                                    }
                                }
                            }

                            FlatButton {
                                objectName: "forgetKeptVideos"
                                text: "Drop the kept videos"
                                onClicked: App.forgetKeptVideos()
                            }
                        }


                        SettingsHeading { text: "YouTube Music" }

                        Row {
                            spacing: 8

                            Label {
                                width: view.wordWidth
                                height: 28
                                text: "Your listening"
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }

                            FlatButton {
                                objectName: "reportListens"
                                text: App.reportListens ? "Told to YouTube Music"
                                                        : "Kept to Weave"
                                accent: App.reportListens
                                onClicked: App.setReportListens(!App.reportListens)
                            }
                        }

                        // What switching it on writes, said in full, since it
                        // is the one thing Weave can write to an account.
                        Label {
                            objectName: "reportListensWords"
                            width: parent.width
                            text: "Off, Weave writes nothing to your account. On, a song you "
                                  + "listen to for 30 seconds is added to your YouTube Music "
                                  + "history with the same note its own player sends, so the "
                                  + "history and the suggestions on your other devices follow "
                                  + "what you heard here. A song skipped sooner is never sent, "
                                  + "and nothing else is written."
                            color: Theme.colors.textMuted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }
}
