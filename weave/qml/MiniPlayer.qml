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
    Rectangle {
        id: progressTrack
        visible: Audio.length > 0
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 3
        color: Theme.colors.border

        Rectangle {
            width: parent.width * Audio.position
            height: parent.height
            color: Theme.colors.accent
        }

        TapHandler {
            onTapped: function (point) { Audio.seek(point.position.x / progressTrack.width) }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.topMargin: 6
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

        FlatButton { text: "◀◀"; onClicked: Audio.previous() }
        FlatButton {
            text: Audio.playing ? "❚❚" : "▶"
            accent: true
            onClicked: Audio.toggle()
        }
        FlatButton { text: "▶▶"; onClicked: Audio.next() }

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
            Layout.preferredWidth: 90
            from: 0
            to: 100
            value: Audio.volume
            onMoved: Audio.setVolume(value)
        }

        FlatButton { text: "✕"; onClicked: Audio.stop() }
    }
}
