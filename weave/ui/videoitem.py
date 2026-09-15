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

The known cost, and it is theirs as much as ours: one framebuffer shared between
the interface and the video ties Qt's paint rate to the video's, so a film at 24
frames a second paints the menus at 24 as well. They built a second, offscreen
one to break that and took it out again. Nothing here tries to be cleverer.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, QRunnable, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QOpenGLContext
from PySide6.QtQuick import QQuickFramebufferObject, QQuickWindow

from .. import trace

# The player whose frames this draws. One music player exists, so it is held
# here rather than threaded through QML, which cannot carry a Python object
# that is not a QObject property anyway. Set once while the window is built.
_engine = None

# mpv allows exactly one render context per player, and Qt is free to throw a
# renderer away and build another whenever the scene graph is rebuilt. Held here
# rather than on the renderer, so a second renderer finds the one that exists
# instead of asking for another and being refused with "Unspecified error".
_context = None
_proc = None
# Set once the picture has been taken down for good. Without it, clearing
# the context simply invites the next paint to build another, which is
# then alive when the player closes and takes the process with it.
_finished = False


def attach(engine) -> None:
    """Say which player the surface draws. Called as the window is put up."""
    global _engine
    _engine = engine


def engine():
    return _engine


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
    """Where the video is drawn. One of these, on the Now playing page."""

    # Raised from mpv's own thread when a frame is waiting. The item cannot be
    # told to redraw from there, so it is bounced through here, which lands it
    # on the window's thread.
    frameReady = Signal()
    drawingChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._renderer: _Renderer | None = None
        # Whether frames are wanted right now. Not the same as being visible:
        # hiding a framebuffer item makes Qt destroy its renderer and give the
        # graphics resources back, which is a synchronous cost paid at exactly
        # the moment the page is moving. So the item stays, and this says
        # whether to do any work.
        self._drawing = True
        self.frameReady.connect(self._redraw)
        # The window closing is what takes the picture down in a running
        # application, and nothing else does. Freed at destruction instead, the
        # context outlives the scene that made it and the process dies on the
        # way out, which looks like a fault in whatever ran last.
        self.windowChanged.connect(self._on_window)
        # One flip, not two. mpv draws into the framebuffer the right way up
        # for Qt already, so mirroring it as well turns the picture over.
        self.setMirrorVertically(False)

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

    # Set by the page. False while it is travelling, and while it is away.
    drawing = Property(bool, _get_drawing, _set_drawing, notify=drawingChanged)

    @Slot()
    def _redraw(self) -> None:
        # A frame arrived. Ignored while the page is moving, so mpv's own rate
        # cannot drive repaints of a window that is busy animating.
        if self._drawing:
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
        global _context, _proc, _finished
        _finished = True
        context, _context = _context, None
        if _engine is not None:
            _engine.render_ready(False)
        if context is not None:
            try:
                context.free()
            except Exception:
                pass
        _proc = None

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
        global _context, _proc, _finished
        _finished = True
        self._renderer = None
        if _engine is not None:
            _engine.render_ready(False)
        context, _context = _context, None
        if context is None:
            _proc = None
            return

        def let_go() -> None:
            global _proc
            try:
                context.free()
            except Exception:
                pass
            _proc = None

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
        self._size = (0, 0)
        self._why = ""

    def render(self) -> None:
        player = _engine
        if player is None or not player.running() or _finished:
            return
        # Painted, but not redrawn from the player. Whatever was last in the
        # framebuffer stays there, which costs nothing and is covered anyway.
        if not self._item.drawing:
            return
        if _context is None and not self._make_context(player):
            return
        width, height = self._size
        if width <= 0 or height <= 0:
            return
        try:
            with trace.Timed():
                _context.render(flip_y=False, opengl_fbo={
                    "w": width, "h": height,
                    "fbo": int(self.framebufferObject().handle()),
                })
        except Exception:
            # A frame that will not draw is not worth taking the window down
            # for. The player says separately when it has nothing to give.
            return

    def _make_context(self, player) -> bool:
        global _context, _proc
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
        _proc = mpv.MpvGlGetProcAddressFn(get_process_address)
        try:
            _context = mpv.MpvRenderContext(
                raw, "opengl",
                opengl_init_params={"get_proc_address": _proc},
                **display_params())
        except Exception as exc:
            _context = None
            # Said rather than swallowed. A picture that never appears with no
            # reason given is the hardest kind of fault to chase, and this one
            # cost a round of exactly that.
            self._why = f"{type(exc).__name__}: {exc}"
            report = getattr(player, "render_failed", None)
            if report is not None:
                report(self._why)
            return False
        # mpv raises this from its own thread whenever a frame is ready, and
        # all it may do there is ask the window to come and draw.
        _context.update_cb = self._item.frameReady.emit
        trace.mark("render_context_built", render_thread=threading.get_ident())
        player.render_ready(True)
        return True

    def synchronize(self, item: VideoSurface) -> None:
        self._size = (int(item.width()), int(item.height()))

    def createFramebufferObject(self, size):
        self._size = (size.width(), size.height())
        return super().createFramebufferObject(size)

    def release(self) -> None:
        """Nothing of its own to let go. The context outlives any one renderer
        and is released by the item, in an order the player survives."""


def shutdown() -> None:
    """Take the picture down before the player it draws is closed.

    Order rather than politeness. mpv closing while a render context still
    points at it takes the process with it, and it does so at the exit rather
    than at the fault, so it reads as a crash in whatever ran last.

    Rendering is stopped first so the render thread cannot enter the context
    again, and only then is it freed.
    """
    global _context, _proc, _finished
    _finished = True
    if _engine is not None:
        _engine.render_ready(False)
    context, _context = _context, None
    if context is not None:
        try:
            context.free()
        except Exception:
            pass
    _proc = None


def register() -> None:
    """Make the surface reachable from QML."""
    from PySide6.QtQml import qmlRegisterType

    qmlRegisterType(VideoSurface, "Weave", 1, 0, "VideoSurface")
