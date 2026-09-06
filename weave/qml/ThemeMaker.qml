import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Making a theme by moving dots. One dot is the ground the window is built
// on, one is what it is accented with, and the third is only the far end of
// the gradient. Left where it is, the third follows the accent, which is what
// wanting only an accent and a gradient amounts to.
Item {
    id: maker

    implicitHeight: layout.implicitHeight

    // Each dot is a place on the disc, kept as hue and how far from the middle
    // it sits. Lightness is not on the disc at all, because a ground has to be
    // dark or light rather than a colour of a certain brightness.
    property real groundHue: 0.72
    property real groundSpread: 0.35
    property real accentHue: 0.72
    property real accentSpread: 0.85
    property real secondHue: 0.78
    property real secondSpread: 0.85
    property bool lightWindow: false
    property int held: -1

    readonly property color groundColour: Qt.hsla(
        groundHue, groundSpread * 0.55, lightWindow ? 0.94 : 0.07, 1.0)
    readonly property color accentColour: Qt.hsva(accentHue, accentSpread, 1.0, 1.0)
    readonly property color secondColour: Qt.hsva(secondHue, secondSpread, 1.0, 1.0)

    function hex(colour) {
        return colour.toString().substring(0, 7)
    }

    // Asked for on a short delay. A dot dragged across the disc would
    // otherwise ask for a whole theme on every pixel it passes.
    Timer {
        id: settle
        interval: 40
        onTriggered: App.previewTheme(maker.hex(maker.groundColour),
                                      maker.hex(maker.accentColour),
                                      maker.hex(maker.secondColour))
    }

    // While the dots are being put where a theme already is, moving them must
    // not ask for a draft of the theme that is already on screen.
    property bool adopting: false

    function refresh() {
        if (!adopting)
            settle.restart()
    }

    // Put the dots where they would have to be to make the theme in use.
    // Pressing one of the themes offered above therefore moves them, and a
    // theme can be taken as the starting point for one of your own.
    function adoptCurrent() {
        adopting = true
        // The roles are handed over as text, so they are read as colours
        // before anything is asked of them.
        var ground = Qt.color(Theme.colors.background)
        var accent = Qt.color(Theme.colors.accent)
        var stops = Theme.gradient && Theme.gradient.stops ? Theme.gradient.stops : []
        var far = stops.length > 0 ? Qt.color(stops[0].color) : accent

        lightWindow = ground.hslLightness > 0.5
        groundHue = ground.hsvHue < 0 ? 0 : ground.hsvHue
        // The ground's colour is damped when it is derived, so the same
        // damping is taken back off here and the dot lands where it was.
        groundSpread = Math.min(1, ground.hsvSaturation / 0.55)
        accentHue = accent.hsvHue < 0 ? 0 : accent.hsvHue
        accentSpread = accent.hsvSaturation
        secondHue = far.hsvHue < 0 ? 0 : far.hsvHue
        secondSpread = far.hsvSaturation
        adopting = false
    }

    Component.onCompleted: adoptCurrent()

    onGroundHueChanged: refresh()
    onGroundSpreadChanged: refresh()
    onAccentHueChanged: refresh()
    onAccentSpreadChanged: refresh()
    onSecondHueChanged: refresh()
    onSecondSpreadChanged: refresh()
    onLightWindowChanged: refresh()

    ColumnLayout {
        id: layout
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 12

        RowLayout {
            spacing: 18

            Item {
                Layout.preferredWidth: 190
                Layout.preferredHeight: 190

                ColourWheel {
                    id: disc
                    objectName: "colourWheel"
                    anchors.fill: parent
                    layer.enabled: true
                    layer.smooth: true
                }

                // The disc is round and the item is square, so a press in a
                // corner belongs to nothing.
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    // The page this sits on scrolls, and a drag begun here
                    // would otherwise be taken from us and read as a scroll
                    // the moment the pointer moved a few pixels.
                    preventStealing: true
                    onPressed: function (mouse) {
                        if (!disc.inside(mouse.x, mouse.y)) {
                            maker.held = -1
                            return
                        }
                        maker.held = maker.nearest(mouse.x, mouse.y)
                        maker.moveHeld(mouse.x, mouse.y)
                    }
                    onPositionChanged: function (mouse) {
                        if (maker.held >= 0)
                            maker.moveHeld(mouse.x, mouse.y)
                    }
                    onReleased: maker.held = -1
                }

                Repeater {
                    model: 3
                    Rectangle {
                        id: dot
                        required property int index
                        readonly property point place: disc.placeOf(
                            index === 0 ? maker.groundColour
                            : index === 1 ? maker.accentColour : maker.secondColour)
                        objectName: "themeDot" + index
                        width: 20
                        height: 20
                        radius: 10
                        x: place.x - 10
                        y: place.y - 10
                        color: index === 0 ? maker.groundColour
                               : index === 1 ? maker.accentColour : maker.secondColour
                        border.width: 2
                        border.color: maker.held === index ? Theme.colors.text : "#ffffff"
                        scale: maker.held === index ? 1.15 : 1.0

                        Behavior on scale {
                            NumberAnimation { duration: 90 }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    text: "Move the dots. The first is the window, the second what "
                          + "it is accented with, the third the far end of the light."
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                RowLayout {
                    spacing: 8
                    Repeater {
                        model: [{"name": "Window", "which": 0},
                                {"name": "Accent", "which": 1},
                                {"name": "Light", "which": 2}]
                        RowLayout {
                            required property var modelData
                            spacing: 5
                            Rectangle {
                                width: 12
                                height: 12
                                radius: 6
                                color: modelData.which === 0 ? maker.groundColour
                                       : modelData.which === 1 ? maker.accentColour
                                                               : maker.secondColour
                                border.width: 1
                                border.color: Theme.colors.border
                            }
                            Label {
                                text: modelData.name
                                color: Theme.colors.textMuted
                                font.pixelSize: 11
                            }
                        }
                    }
                }

                Switch {
                    objectName: "lightWindowSwitch"
                    text: "A light window"
                    checked: maker.lightWindow
                    onToggled: maker.lightWindow = checked
                    contentItem: Label {
                        text: parent.text
                        color: Theme.colors.text
                        font.pixelSize: 12
                        leftPadding: parent.indicator.width + 6
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    TextField {
                        id: named
                        objectName: "themeName"
                        Layout.fillWidth: true
                        placeholderText: "Name it"
                        color: Theme.colors.text
                        placeholderTextColor: Theme.colors.textMuted
                        background: Rectangle {
                            radius: 6
                            color: Theme.colors.background
                            border.width: 1
                            border.color: named.activeFocus ? Theme.colors.accent
                                                            : Theme.colors.border
                        }
                    }

                    FlatButton {
                        objectName: "saveTheme"
                        text: "Save"
                        accent: true
                        enabled: named.text.trim() !== ""
                        onClicked: {
                            if (App.saveTheme(named.text, maker.hex(maker.groundColour),
                                              maker.hex(maker.accentColour),
                                              maker.hex(maker.secondColour)))
                                named.text = ""
                        }
                    }

                    FlatButton {
                        objectName: "stopPreview"
                        text: "Put it down"
                        onClicked: App.stopPreview()
                    }
                }
            }
        }
    }

    // Which dot a press belongs to, by which is nearest to it.
    function nearest(px, py) {
        var places = [disc.placeOf(groundColour), disc.placeOf(accentColour),
                      disc.placeOf(secondColour)]
        var best = 0
        var bestGap = Number.MAX_VALUE
        for (var i = 0; i < places.length; i++) {
            var dx = places[i].x - px
            var dy = places[i].y - py
            var gap = dx * dx + dy * dy
            if (gap < bestGap) {
                bestGap = gap
                best = i
            }
        }
        return best
    }

    function moveHeld(px, py) {
        var picked = disc.colourAt(px, py)
        if (held === 0) {
            groundHue = picked.hsvHue < 0 ? 0 : picked.hsvHue
            groundSpread = picked.hsvSaturation
        } else if (held === 1) {
            accentHue = picked.hsvHue < 0 ? 0 : picked.hsvHue
            accentSpread = picked.hsvSaturation
        } else if (held === 2) {
            secondHue = picked.hsvHue < 0 ? 0 : picked.hsvHue
            secondSpread = picked.hsvSaturation
        }
    }
}
