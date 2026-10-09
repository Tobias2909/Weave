"""The picture, drawn into the window's own scene.

mpv renders video inside whatever process holds it, and there is no way to lift
those frames out of a second one. Wayland has no protocol for embedding a
foreign window either. So the only route to a picture inside this page is
libmpv's render interface, drawing into the same scene Qt draws, which is what
this is.

The shape is the one mpvQC arrived at for the same stack, PySide with QML and
libmpv, and it is worth saying why rather than leaving it to look arbitrary.
The frames go into the scene's own framebuffer through a QQuickFramebufferObject,
whose renderer lives on the render thread with the GL context current, which is
the only place mpv may be asked to draw. Everything here is therefore split
between two threads on purpose: the item lives with the window, the renderer
with the scene graph, and mpv talks to neither directly.

The cost that shape is known for, the interface painting no faster than the
video, comes from one thing: mpv's render call waits for the frame's display
time, up to fifty milliseconds by default, and it is being called on the thread
that paints everything. So it is asked not to wait, and the player is told to
hand frames over at their display time (video-timing-offset). Each render is
then one draw, a millisecond or two, and Qt paints at its own rate.

The other half of the same trap is never to stop collecting frames while the
player is producing them. mpv's output thread waits two hundred milliseconds
for each frame to be collected before giving up on it, and the player's core
waits on that thread for a track change, so a surface that goes quiet with
video running stalls the player rather than sparing it. While the page does
not want frames drawn, they are still collected, only not painted.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, QRunnable, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QOpenGLContext
from PySide6.QtQuick import QQuickFramebufferObject, QQuickWindow

from .. import trace

# The players there are pictures of, by name: the music, and the videos played
# in the window rather than handed to mpv. Two players, two surfaces, two render
# contexts, MEASURED side by side before any of this was written: both drawing
# 1080p at once dropped no frame, held none and stalled nothing.
MUSIC, VIDEO = "music", "video"


class _Binding:
    """One player and everything its picture needs, kept apart from any one
    surface or renderer.

    mpv allows exactly one render context per player, and Qt is free to throw a
    renderer away and build another whenever the scene graph is rebuilt. Held
    here rather than on the renderer, so a second renderer finds the one that
    exists instead of asking for another and being refused with "Unspecified
    error".
    """

    __slots__ = ("context", "engine", "finished", "proc")

    def __init__(self) -> None:
        # The player whose frames this draws. Held here rather than threaded
        # through QML, which cannot carry a Python object that is not a QObject
        # property anyway. Set once while the window is built.
        self.engine = None
        self.context = None
        self.proc = None
        # Set once the picture has been taken down for good. Without it,
        # clearing the context simply invites the next paint to build another,
        # which is then alive when the player closes and takes the process with
        # it.
        self.finished = False


_bindings: dict[str, _Binding] = {MUSIC: _Binding(), VIDEO: _Binding()}


def _binding(name: str) -> _Binding:
    return _bindings.get(name) or _bindings[MUSIC]


def attach(engine, name: str = MUSIC) -> None:
    """Say which player a surface of that name draws. Called as the window is
    put up."""
    _binding(name).engine = engine


def engine(name: str = MUSIC):
    return _binding(name).engine


def get_process_address(_ctx, name: bytes) -> int:
    """Where a GL entry point lives, asked of whatever context is current.

    mpv resolves its own GL functions through this rather than linking them,
    which is what lets it draw into a context it did not create.
    """
    current = QOpenGLContext.currentContext()
    return int(current.getProcAddress(name)) if current else 0


def display_params() -> dict:
    """The native display handle, so mpv can reach hardware decoding.

    Without it mpv still draws, through software, and a music video at 1080p
    is then several times the processor it should be.
    """
    app = QGuiApplication.instance()
    if app is None:
        return {}
    try:
        # Not every application is a graphical one. A plain core application
        # has no native interface at all, and asking it raises rather than
        # answering nothing.
        native = app.nativeInterface()
    except AttributeError:
        return {}
    if native is None:
        return {}
    platform = QGuiApplication.platformName()
    try:
        if platform == "wayland":
            display = native.display()
            return {"wl_display": display} if display else {}
        if platform == "xcb":
            display = native.display()
            return {"x11_display": display} if display else {}
    except AttributeError:
        # The platform interfaces are not all present on every build, and an
        # absent one means no hardware handle rather than a fault.
        return {}
    return {}


class VideoSurface(QQuickFramebufferObject):
    """Where a player's picture is drawn. One for the music, on the Now playing
    page, and one for the videos, on the page they play on."""

    # Raised from mpv's own thread when a frame is waiting. The item cannot be
    # told to redraw from there, so it is bounced through here, which lands it
    # on the window's thread.
    frameReady = Signal()
    drawingChanged = Signal()
    playerChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._renderer: _Renderer | None = None
        # Which player this draws. Named once, by the page that makes it.
        self._player = MUSIC
        self._wanting = None
        # Whether frames are to be painted. Not the same as being visible:
        # hiding a framebuffer item makes Qt destroy its renderer and give the
        # graphics resources back, which is a synchronous cost paid at exactly
        # the moment the page is moving. So the item stays. Frames are always
        # collected from the player either way; this only says whether they
        # are drawn.
        self._drawing = True
        self.frameReady.connect(self._redraw)
        self._listen()
        # The window closing is what takes the picture down in a running
        # application, and nothing else does. Freed at destruction instead, the
        # context outlives the scene that made it and the process dies on the
        # way out, which looks like a fault in whatever ran last.
        self.windowChanged.connect(self._on_window)
        # One flip, not two. mpv draws into the framebuffer the right way up
        # for Qt already, so mirroring it as well turns the picture over.
        self.setMirrorVertically(False)

    def _listen(self) -> None:
        """Told to paint when the player has something to draw and nowhere to
        draw it, which is how the render context gets built at all."""
        if self._wanting is not None:
            try:
                self._wanting.surfaceWanted.disconnect(self._nudge)
            except (RuntimeError, TypeError):
                pass
            try:
                self._wanting.outputClosed.disconnect(self._tidy)
            except (AttributeError, RuntimeError, TypeError):
                pass
            self._wanting = None
        player = self.binding.engine
        if player is not None and hasattr(player, "surfaceWanted"):
            player.surfaceWanted.connect(self._nudge)
            if hasattr(player, "outputClosed"):
                player.outputClosed.connect(self._tidy)
            self._wanting = player

    @property
    def binding(self) -> _Binding:
        return _binding(self._player)

    def _get_player(self) -> str:
        return self._player

    def _set_player(self, name: str) -> None:
        name = name if name in _bindings else MUSIC
        if name == self._player:
            return
        self._player = name
        self._listen()
        self.playerChanged.emit()
        self.update()

    # "music" or "video". Set where the surface is declared and never changed.
    player = Property(str, _get_player, _set_player, notify=playerChanged)

    def _get_drawing(self) -> bool:
        return self._drawing

    def _set_drawing(self, wanted: bool) -> None:
        wanted = bool(wanted)
        if wanted == self._drawing:
            return
        self._drawing = wanted
        trace.mark("drawing", on=wanted)
        self.drawingChanged.emit()
        if wanted:
            # Nothing has asked it to paint while it was quiet, and it has no
            # reason of its own, so it is asked once here.
            self.update()

    # Set by the page. True while it is open and while it is travelling.
    drawing = Property(bool, _get_drawing, _set_drawing, notify=drawingChanged)

    @Slot()
    def _nudge(self) -> None:
        """Paint once more, while the page wants drawing. A closed page costs
        nothing: it builds its context the next time it is opened."""
        if self._drawing:
            trace.mark("surface_nudged")
            self.update()

    @Slot()
    def _tidy(self) -> None:
        """Paint once after the player closed its output, drawing or not.

        mpv gives back what it held for drawing the last picture on the next
        paint, and for a picture decoded on the graphics card that paint takes
        17-25 ms, MEASURED. Left to wait, it fell on the page opening again.
        Asked for now, it falls while the page is away, and a surface not
        drawing only collects, so nothing shows.
        """
        self.update()

    def _redraw(self) -> None:
        # A frame arrived. Always collected, whether or not it is painted,
        # because a frame left waiting holds the player's output thread for
        # two hundred milliseconds and the player's core behind it.
        self.update()

    def _on_window(self) -> None:
        window = self.window()
        if window is None:
            return
        # Raised on the render thread as the scene is torn down, which is both
        # the right moment and the only thread that may free the context.
        window.sceneGraphInvalidated.connect(
            self._let_go, Qt.ConnectionType.DirectConnection)

    def _let_go(self) -> None:
        held = self.binding
        held.finished = True
        context, held.context = held.context, None
        if held.engine is not None:
            held.engine.render_ready(False)
        if context is not None:
            try:
                context.free()
            except Exception:
                pass
        held.proc = None

    def createRenderer(self) -> QQuickFramebufferObject.Renderer:
        self._renderer = _Renderer(self)
        return self._renderer

    def release(self) -> None:
        """Take the picture down before the player goes.

        Order matters and a core dump is what gets it wrong: the player must be
        told there is nowhere to draw, then the context freed, and only then may
        the player itself be closed. Freed the other way round, mpv is still
        holding a context over a window that has gone.
        """
        held = self.binding
        held.finished = True
        self._renderer = None
        if held.engine is not None:
            held.engine.render_ready(False)
        context, held.context = held.context, None
        if context is None:
            held.proc = None
            return

        def let_go() -> None:
            try:
                context.free()
            except Exception:
                pass
            held.proc = None

        window = self.window()
        if window is None:
            let_go()
            return
        # Freed where it was made, which is the render thread. Freeing it from
        # this side while that thread may still be drawing through it is what
        # takes the whole process down, and it does so at the exit rather than
        # at the fault, which makes it look like something else entirely.
        window.scheduleRenderJob(
            QRunnable.create(let_go),
            QQuickWindow.RenderStage.BeforeSynchronizingStage)
        window.update()


class _Renderer(QQuickFramebufferObject.Renderer):
    """Lives on the render thread, where the GL context is current.

    The render context is built here rather than beside the player, because it
    can only be made where that context exists, and it is built on the first
    draw rather than at construction for the same reason.
    """

    def __init__(self, item: VideoSurface) -> None:
        super().__init__()
        self._item = item
        self._why = ""
        self._drawn = (0, 0)
        self._said_why = False

    def render(self) -> None:
        held = self._item.binding
        player = held.engine
        if player is None or not player.running() or held.finished:
            if held.context is None and not self._said_why:
                # Once, and only while there is no picture: a surface asked to
                # draw that never builds anything is otherwise silent.
                self._said_why = True
                trace.mark("render_waits", player=self._item.player,
                           engine=player is not None,
                           running=bool(player is not None and player.running()),
                           finished=held.finished)
            return
        self._said_why = False
        if held.context is None and not self._make_context(held):
            return
        context = held.context
        try:
            # Collected but not drawn. The player counts the frame as shown
            # and moves on, and whatever was last in the framebuffer stays.
            if not self._item.drawing:
                context.render(skip_rendering=True, block_for_target_time=False)
                return
            # The framebuffer's own size, in device pixels. The item's size is
            # in the window's logical units, and on a screen scaled by 1.7 the
            # player told that drew into 1/1.7 of each side and left the rest
            # of the box empty. Qt sizes the framebuffer for the screen the
            # window is on and makes it again when the window moves.
            target = self.framebufferObject()
            width, height = target.width(), target.height()
            if width <= 0 or height <= 0:
                return
            if (width, height) != self._drawn:
                self._drawn = (width, height)
                trace.mark("surface_size", w=width, h=height, player=self._item.player)
            # Never waits. The player is told to hand frames over at their
            # display time, and this returns the moment the draw is issued,
            # so the thread painting the window is held for one draw only.
            with trace.Timed():
                context.render(flip_y=False, block_for_target_time=False,
                                opengl_fbo={
                    "w": width, "h": height,
                    "fbo": int(target.handle()),
                })
        except Exception:
            # A frame that will not draw is not worth taking the window down
            # for. The player says separately when it has nothing to give.
            return

    def _make_context(self, held: _Binding) -> bool:
        player = held.engine
        try:
            import mpv
        except (ImportError, OSError):
            return False
        raw = getattr(player, "raw", None)
        if raw is None:
            return False
        # Wrapped as a C function pointer rather than handed over as it is.
        # mpv keeps this and calls it from its own side, and a plain Python
        # function is refused outright with "expected CFunctionType instance".
        held.proc = mpv.MpvGlGetProcAddressFn(get_process_address)
        try:
            held.context = mpv.MpvRenderContext(
                raw, "opengl",
                opengl_init_params={"get_proc_address": held.proc},
                **display_params())
        except Exception as exc:
            held.context = None
            # Said rather than swallowed. A picture that never appears with no
            # reason given is the hardest kind of fault to chase, and this one
            # cost a round of exactly that.
            self._why = f"{type(exc).__name__}: {exc}"
            trace.mark("render_context_failed", player=self._item.player, why=self._why)
            report = getattr(player, "render_failed", None)
            if report is not None:
                report(self._why)
            return False
        # mpv raises this from its own thread whenever a frame is ready, and
        # all it may do there is ask the window to come and draw.
        held.context.update_cb = self._item.frameReady.emit
        trace.mark("render_context_built", render_thread=threading.get_ident(),
                   player=self._item.player)
        player.render_ready(True)
        return True

    def release(self) -> None:
        """Nothing of its own to let go. The context outlives any one renderer
        and is released by the item, in an order the player survives."""


def shutdown() -> None:
    """Take every picture down before the players they draw are closed.

    Order rather than politeness. mpv closing while a render context still
    points at it takes the process with it, and it does so at the exit rather
    than at the fault, so it reads as a crash in whatever ran last.

    Rendering is stopped first so the render thread cannot enter a context
    again, and only then is it freed. MEASURED with two players: the picture
    switched off on both, both contexts freed from this thread, then mpv
    closed, exits cleanly.
    """
    for held in _bindings.values():
        held.finished = True
        if held.engine is not None:
            held.engine.render_ready(False)
    for held in _bindings.values():
        context, held.context = held.context, None
        if context is not None:
            try:
                context.free()
            except Exception:
                pass
        held.proc = None


def register() -> None:
    """Make the surface reachable from QML."""
    from PySide6.QtQml import qmlRegisterType

    qmlRegisterType(VideoSurface, "Weave", 1, 0, "VideoSurface")
