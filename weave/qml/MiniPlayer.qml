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
                text: "UP NEXT  ·  " + Audio.upcoming.length
                color: Theme.colors.textMuted
                font.pixelSize: 10
                font.letterSpacing: 1.2
                font.weight: Font.DemiBold
            }

            ListView {
                id: queued
                width: parent.width
                height: parent.height - 22
                clip: true
                spacing: 2
                model: Audio.upcoming
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Row {
                    required property var modelData
                    width: queued.width
                    height: 44
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
                            visible: (modelData.artist || "") !== ""
                            text: modelData.artist
                            color: Theme.colors.textMuted
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.topMargin: 14
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
            text: "Repeat"
            accent: Audio.repeat
            onClicked: Audio.setRepeat(!Audio.repeat)
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
            text: "Up next"
            enabled: Audio.upcoming.length > 0
            onClicked: upNext.open()
        }

        FlatButton { text: "✕"; onClicked: Audio.stop() }
    }
}
