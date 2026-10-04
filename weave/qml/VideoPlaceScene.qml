import QtQuick

// A press on a card and what follows it, drawn small and on a loop, for the
// welcome page that asks where videos play: an mpv window coming out beside
// the window, or the video's page rising inside it. Drawn rather than
// recorded, so it wears whichever theme is in use like the rest of the window.
Item {
    id: scene

    // "mpv" or "weave".
    property string place: "weave"
    property bool running: false
    readonly property bool inMpv: place === "mpv"

    implicitWidth: 252
    implicitHeight: 150

    // Where the loop is, from 0 to 1. Everything below is drawn from this one
    // number, so no part of the scene can drift out of step with another.
    property real phase: still
    // Stopped, it shows the moment that says the most on its own.
    readonly property real still: 0.7
    NumberAnimation on phase {
        id: loop
        from: 0
        to: 1
        duration: 4800
        loops: Animation.Infinite
        running: scene.running
    }
    onRunningChanged: if (!running) phase = still

    function span(from, to) {
        return Math.max(0, Math.min(1, (phase - from) / (to - from)))
    }
    function ease(x) {
        return x * x * (3 - 2 * x)
    }

    // The pointer goes to a card, presses it, and what the press opens comes
    // and plays a while before it all goes round again.
    readonly property real reach: ease(span(0.04, 0.28))
    readonly property real press: span(0.30, 0.33) - span(0.36, 0.40)
    readonly property real open: ease(span(0.36, 0.50)) - ease(span(0.86, 0.96))
    readonly property real played: span(0.48, 0.88)

    // A video, as far as a picture this size can say it: a sky going down
    // behind two hills, and the line of how much of it has played.
    component Picture: Rectangle {
        id: picture
        property real played: 0
        clip: true
        gradient: Gradient {
            GradientStop {
                position: 0
                color: Theme.washOver(Theme.colors.accent, 0.25, "#24324f")
            }
            GradientStop {
                position: 1
                color: Theme.washOver(Theme.colors.accent, 0.7, "#3a2018")
            }
        }
        Rectangle {
            width: picture.height * 0.3
            height: width
            radius: width / 2
            x: picture.width * 0.6
            y: picture.height * (0.14 + 0.22 * picture.played)
            color: Qt.rgba(1, 0.94, 0.82, 0.92)
        }
        Rectangle {
            width: picture.width * 1.1
            height: picture.height * 0.9
            radius: height / 2
            x: -picture.width * 0.35
            y: picture.height * 0.58
            color: Theme.washOver(Theme.colors.accent, 0.3, "#16121a")
        }
        Rectangle {
            width: picture.width
            height: picture.height * 0.8
            radius: height / 2
            x: picture.width * 0.32
            y: picture.height * 0.7
            color: "#0e0b10"
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 2
            color: Qt.rgba(1, 1, 1, 0.25)
            Rectangle {
                width: parent.width * picture.played
                height: parent.height
                color: Theme.colors.accent
            }
        }
    }

    // ---- the window, with its cards -----------------------------------------
    Rectangle {
        id: home
        x: scene.inMpv ? 4 : 8
        y: scene.inMpv ? 6 : 4
        width: scene.inMpv ? 172 : scene.width - 16
        height: scene.inMpv ? 106 : scene.height - 8
        radius: 4
        clip: true
        color: Theme.colors.surface
        border.width: 1
        border.color: Theme.colors.border

        Rectangle {
            width: parent.width
            height: 8
            color: Theme.wash(Theme.colors.text, 0.06)
        }

        Column {
            x: 6
            y: 15
            spacing: 5
            Repeater {
                model: 4
                Rectangle {
                    width: 14
                    height: 2
                    radius: 1
                    color: Theme.wash(Theme.colors.text, 0.32)
                }
            }
        }

        Grid {
            id: cards
            x: 28
            y: 15
            columns: 3
            spacing: 5
            readonly property real cardWidth: (home.width - x - 6 - 2 * spacing) / 3
            readonly property real cardHeight: cardWidth * 0.62
            // The one pressed, in the middle of the second row.
            readonly property int pressed: 4

            Repeater {
                model: 6
                Rectangle {
                    required property int index
                    readonly property bool target: index === cards.pressed
                    width: cards.cardWidth
                    height: cards.cardHeight
                    radius: 2
                    scale: target ? 1 - 0.08 * scene.press : 1
                    color: target && scene.open > 0.02
                           ? Theme.colors.accent : Theme.wash(Theme.colors.accent, 0.42)
                    border.width: target && scene.press > 0 ? 1 : 0
                    border.color: Theme.colors.text
                }
            }
        }

        // The video's page, rising over the cards the way it does in the
        // window: the picture, the words under it and the queue beside it.
        Rectangle {
            id: page
            visible: !scene.inMpv && scene.open > 0
            x: 24
            y: 9 + (home.height - 9) * (1 - scene.open)
            width: home.width - 24
            height: home.height - 9
            color: Theme.colors.surface

            Picture {
                id: pagePicture
                x: 6
                y: 6
                width: page.width * 0.64
                height: width * 9 / 16
                played: scene.played
            }
            Column {
                x: pagePicture.x
                y: pagePicture.y + pagePicture.height + 6
                spacing: 4
                Rectangle {
                    width: pagePicture.width * 0.8
                    height: 4
                    radius: 2
                    color: Theme.wash(Theme.colors.text, 0.55)
                }
                Rectangle {
                    width: pagePicture.width * 0.5
                    height: 3
                    radius: 1.5
                    color: Theme.wash(Theme.colors.text, 0.3)
                }
            }
            Column {
                x: pagePicture.x + pagePicture.width + 6
                y: pagePicture.y
                spacing: 5
                Repeater {
                    model: 5
                    Rectangle {
                        required property int index
                        width: page.width - pagePicture.width - 18
                        height: 9
                        radius: 2
                        color: index === 0 ? Theme.wash(Theme.colors.accent, 0.7)
                                           : Theme.wash(Theme.colors.text, 0.14)
                    }
                }
            }
        }
    }

    // ---- mpv, in a window of its own ----------------------------------------
    Rectangle {
        id: mpvWindow
        visible: scene.inMpv && scene.open > 0
        x: 116
        y: 54
        width: 130
        height: width * 9 / 16 + 10
        radius: 3
        color: "#101010"
        border.width: 1
        border.color: "#2c2c2c"
        opacity: scene.open
        scale: 0.6 + 0.4 * scene.open
        transformOrigin: Item.TopLeft

        Text {
            x: 5
            y: 1
            text: "mpv"
            color: "#c8c8c8"
            font.pixelSize: 7
        }
        Picture {
            x: 1
            y: 10
            width: parent.width - 2
            height: parent.height - 11
            played: scene.played
        }
    }

    // ---- the hand -------------------------------------------------------------
    Canvas {
        id: pointer
        readonly property real fromX: scene.width - 24
        readonly property real fromY: scene.height - 6
        readonly property real toX: home.x + cards.x + 1.5 * cards.cardWidth + cards.spacing
        readonly property real toY: home.y + cards.y + 1.5 * cards.cardHeight + cards.spacing
        x: fromX + (toX - fromX) * scene.reach
        y: fromY + (toY - fromY) * scene.reach
        width: 12
        height: 17
        opacity: scene.span(0, 0.04) - scene.span(0.84, 0.9)
        scale: 1 - 0.15 * scene.press
        transformOrigin: Item.TopLeft
        onPaint: {
            var g = getContext("2d")
            g.reset()
            g.beginPath()
            g.moveTo(1, 1)
            g.lineTo(1, 14)
            g.lineTo(4.2, 11)
            g.lineTo(6.6, 16)
            g.lineTo(8.8, 15)
            g.lineTo(6.4, 10)
            g.lineTo(10.6, 10)
            g.closePath()
            g.fillStyle = "#ffffff"
            g.strokeStyle = "#111111"
            g.lineWidth = 1.1
            g.fill()
            g.stroke()
        }
    }
}
