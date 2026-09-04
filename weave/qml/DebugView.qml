import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Why nothing is arriving. Every scraper failure here looks the same from the
// outside, exit zero with no items and no error, so this is the place where a
// quiet one has to show up.
Item {
    id: view

    // The palette has one red and one amber. Red for something that is
    // broken, amber for something worth a look, and the accent for fine.
    function markColour(state) {
        if (state === "fail") return Theme.colors.live
        if (state === "warn") return Theme.colors.error
        return Theme.colors.accent
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Label {
                text: "How things are"
                color: Theme.colors.text
                font.pixelSize: 18
                font.weight: Font.Bold
            }

            Item { Layout.fillWidth: true }

            FlatButton {
                text: "Check again"
                accent: true
                onClicked: App.runChecks(true)
            }
            FlatButton {
                // The two checks that make a request are the slow ones and the
                // only ones that cost anything.
                text: "Without asking YouTube"
                onClicked: App.runChecks(false)
            }
        }

        Flickable {
            id: sheet
            objectName: "debugSheet"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: body.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AlwaysOn; width: 10 }

            Column {
                id: body
                width: sheet.width - 16
                spacing: 14

                Repeater {
                    model: App.checks
                    Rectangle {
                        width: body.width
                        height: line.height + (why.visible ? why.height + 4 : 0) + 14
                        radius: 6
                        color: Theme.colors.surface
                        border.width: 1
                        border.color: Theme.colors.border

                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: 3
                            radius: 2
                            color: view.markColour(modelData.state)
                        }

                        Row {
                            id: line
                            x: 14
                            y: 7
                            spacing: 12
                            Label {
                                width: 190
                                text: modelData.name
                                color: Theme.colors.text
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Label {
                                width: body.width - 230
                                text: modelData.detail
                                color: Theme.colors.textMuted
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }
                        }

                        Label {
                            id: why
                            visible: modelData.fix !== "" && modelData.state !== "ok"
                            x: 14
                            anchors.top: line.bottom
                            anchors.topMargin: 4
                            width: body.width - 28
                            text: modelData.fix
                            color: view.markColour(modelData.state)
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                    }
                }

                Label {
                    visible: App.problems.length > 0
                    text: "What has gone wrong lately"
                    color: Theme.colors.text
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }

                Repeater {
                    model: App.problems
                    Label {
                        width: body.width
                        text: "•  " + modelData
                        color: Theme.colors.textMuted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                }

                Label {
                    text: "When each channel is asked"
                    color: Theme.colors.text
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }

                Label {
                    width: body.width
                    text: "In the order the poller will take them, so the top of this list is "
                          + "what the next few minutes will do."
                    color: Theme.colors.textMuted
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }

                Repeater {
                    model: App.schedule
                    Row {
                        width: body.width
                        spacing: 12
                        Label {
                            width: 240
                            text: modelData.title
                            color: Theme.colors.text
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                        Label {
                            width: 130
                            text: modelData.tier
                            color: Theme.colors.textMuted
                            font.pixelSize: 12
                        }
                        Label {
                            width: 140
                            text: "asked " + modelData.lastText
                            color: Theme.colors.textMuted
                            font.pixelSize: 12
                        }
                        Label {
                            width: 110
                            text: "next " + modelData.dueText
                            color: Theme.colors.textMuted
                            font.pixelSize: 12
                        }
                        Label {
                            text: modelData.error
                            color: Theme.colors.error
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
