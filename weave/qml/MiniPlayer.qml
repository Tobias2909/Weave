import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Always there once something is queued, whichever view is showing, because
// music that stops when you look at your feed is not music you can use.
Rectangle {
    id: bar
    visible: Audio.hasQueue
    height: visible ? 64 : 0
    color: Qt.rgba(Theme.colors.surface.r, Theme.colors.surface.g,
                   Theme.colors.surface.b, Theme.washed ? 0.72 : 1.0)

    function clock(seconds) {
        if (!seconds || seconds < 0)
            return "0:00"
        var m = Math.floor(seconds / 60)
        var s = Math.floor(seconds % 60)
        return m + ":" + (s < 10 ? "0" : "") + s
    }

    Rectangle {
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: Theme.colors.border
    }

    // A live stream has no length, so it gets a bar that means nothing and is
    // better left out.
    // Thicker under the pointer, so it can actually be hit and dragged rather
    // than needing a three pixel target.
    Item {
        id: scrubber
        visible: Audio.length > 0
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 14

        HoverHandler { id: scrubHover }

        Rectangle {
            id: progressTrack
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: scrubHover.hovered || scrubDrag.active ? 8 : 3
            color: Theme.colors.border
            Behavior on height { NumberAnimation { duration: 90 } }

            Rectangle {
                width: parent.width * Audio.position
                height: parent.height
                color: Theme.colors.accent
            }

            Rectangle {
                visible: progressTrack.height > 3
                x: Math.max(0, parent.width * Audio.position - height / 2)
                anchors.verticalCenter: parent.verticalCenter
                width: 12
                height: 12
                radius: 6
                color: Theme.colors.accent
            }
        }

        TapHandler {
            onTapped: function (point) { Audio.seek(point.position.x / scrubber.width) }
        }
        DragHandler {
            id: scrubDrag
            target: null
            yAxis.enabled: false
            onCentroidChanged: if (active) Audio.seek(centroid.position.x / scrubber.width)
        }
    }

    Popup {
        id: upNext
        objectName: "upNext"
        y: -height - 8
        x: parent.width - width - 12
        width: 340
        height: Math.min(360, 46 + queued.count * 46)
        padding: 8
        modal: false
        background: Rectangle {
            radius: 8
            color: Theme.colors.surfaceRaised
            border.width: 1
            border.color: Theme.colors.border
        }

        Column {
            anchors.fill: parent
            spacing: 6

            Label {
                text: "QUEUE  ·  " + Audio.queue.length
                color: Theme.colors.textMuted
                font.pixelSize: 10
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }

            ListView {
                id: queued
                objectName: "queuedList"
                // Handed to the rows, because a delegate is built in its own
                // scope and cannot see an id declared out here. Reaching for
                // one raises a reference error and the row does nothing.
                property var owner: upNext
                width: parent.width
                height: parent.height - 22
                clip: true
                spacing: 2
                model: Audio.queue
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    id: queuedRow
                    required property var modelData
                    width: queued.width
                    height: 44
                    radius: 5
                    // The one playing stays marked, since the list holds
                    // everything rather than only what is still to come.
                    color: queuedRow.modelData.current ? Theme.colors.surfaceRaised
                                                       : (queuedHover.hovered
                                                          ? Theme.colors.surface
                                                          : "transparent")

                    HoverHandler { id: queuedHover }
                    // Skip straight to it rather than pressing next repeatedly.
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            Audio.jumpTo(queuedRow.modelData.at)
                            queuedRow.ListView.view.owner.close()
                        }
                    }

                    Row {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 8

                    RoundedImage {
                        width: 34
                        height: 34
                        radius: 4
                        anchors.verticalCenter: parent.verticalCenter
                        visible: (modelData.thumbnail || "") !== ""
                        source: modelData.thumbnail ? modelData.thumbnail : ""
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 46
                        spacing: 1
                        Label {
                            width: parent.width
                            text: modelData.title
                            color: Theme.colors.text
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                        Label {
                            width: parent.width
                            visible: (modelData.artist || "") !== "" || modelData.current
                            // The one playing says so, since the list holds
                            // what has been played as well as what has not.
                            text: modelData.current
                                  ? ("Playing now"
                                     + ((modelData.artist || "") !== ""
                                        ? "  ·  " + modelData.artist : ""))
                                  : modelData.artist
                            color: modelData.current ? Theme.colors.accent
                                                     : Theme.colors.textMuted
                            font.pixelSize: 10
                            font.weight: modelData.current ? Font.DemiBold : Font.Normal
                            elide: Text.ElideRight
                        }
                    }
                    }
                }
            }
        }
    }

    // Inset by the same amount above and below, so the row sits in the middle
    // of the bar. Room left for the scrub track on the top side alone pushed
    // the row down and left a band of empty bar over it. Ten clears the track
    // at its thickest and the handle on it, and the artwork fills the forty
    // four that are left.
    RowLayout {
        anchors.fill: parent
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 12

        RoundedImage {
            Layout.preferredWidth: 44
            Layout.preferredHeight: 44
            radius: 6
            visible: (Audio.track.thumbnail || "") !== ""
            source: Audio.track.thumbnail ? Audio.track.thumbnail : ""
        }

        ColumnLayout {
            Layout.preferredWidth: 240
            Layout.maximumWidth: 320
            spacing: 1

            Label {
                Layout.fillWidth: true
                text: Audio.track.title ? Audio.track.title : ""
                color: Theme.colors.text
                font.pixelSize: 12
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Label {
                Layout.fillWidth: true
                text: Audio.loading ? "loading"
                                    : (Audio.track.artist ? Audio.track.artist : "")
                color: Theme.colors.textMuted
                font.pixelSize: 11
                elide: Text.ElideRight
            }
        }

        FlatButton {
            text: "◀◀"
            Layout.preferredWidth: 42
            onClicked: Audio.previous()
        }
        FlatButton {
            // Fixed, because the pause and play marks are different widths and
            // everything to the right of it used to shuffle sideways.
            text: Audio.playing ? "❚❚" : "▶"
            accent: true
            Layout.preferredWidth: 46
            onClicked: Audio.toggle()
        }
        FlatButton {
            text: "▶▶"
            Layout.preferredWidth: 42
            onClicked: Audio.next()
        }

        Label {
            visible: Audio.length > 0
            text: bar.clock(Audio.elapsed) + " / " + bar.clock(Audio.length)
            color: Theme.colors.textMuted
            font.pixelSize: 11
        }
        Label {
            visible: Audio.length === 0
            text: "live"
            color: Theme.colors.live
            font.pixelSize: 11
            font.bold: true
        }

        Item { Layout.fillWidth: true }

        FlatButton {
            text: "Shuffle"
            accent: Audio.shuffle
            onClicked: Audio.setShuffle(!Audio.shuffle)
        }
        FlatButton {
            // Off, the whole queue, or the one track. A queue that repeats and
            // a track that repeats are different wants.
            text: Audio.repeatLabel
            accent: Audio.repeat > 0
            Layout.preferredWidth: 92
            onClicked: Audio.cycleRepeat()
        }
        FlatButton {
            // Two things playing at once is never wanted, but it is a choice.
            text: "Pause for video"
            accent: Audio.autoPause
            onClicked: Audio.setAutoPause(!Audio.autoPause)
        }

        Slider {
            id: volume
            // Long enough that a small change is a small movement.
            Layout.preferredWidth: 170
            from: 0
            to: 100
            value: Audio.volume
            onMoved: Audio.setVolume(value)

            // A notch is five, so it can be tuned without aiming.
            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                property real carried: 0
                onWheel: function (event) {
                    carried += event.angleDelta.y
                    while (carried >= 120) { carried -= 120; Audio.nudgeVolume(1) }
                    while (carried <= -120) { carried += 120; Audio.nudgeVolume(-1) }
                }
            }
        }

        FlatButton {
            text: "Queue"
            enabled: Audio.queue.length > 0
            onClicked: upNext.open()
        }

        FlatButton { text: "✕"; onClicked: Audio.stop() }
    }
}
