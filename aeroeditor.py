"""
Aero - a seamless carousel editor for Instagram / Facebook albums, for desktop.
Run:  pip install PySide6 numpy   then   python aeroeditor.py
Optional: pip install rembg (AI background removal), pillow pillow-heif (iPhone HEIC photos).
"""
import os, sys, json, base64, uuid, math, random, hashlib, time, shutil, subprocess, tempfile, threading, weakref, atexit, queue, gc
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):     # numpy's helper libraries otherwise spin on every core
    os.environ.setdefault(_v, str(max(1, min(4, (os.cpu_count() or 4) // 3))))
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtGui import QCursor
from PySide6.QtCore import QEvent, QThread, QObject, Signal, Slot, QEventLoop, QElapsedTimer, QPoint, Qt, QRectF, QPointF, QSizeF, QUrl, QBuffer, QIODevice, QSettings, QSize, QTimer, QVariantAnimation, QEasingCurve, QStandardPaths
from PySide6.QtGui import (QColor, QPainter, QPen, QPixmap, QImage, QKeySequence,
                           QAction, QFont, QPolygonF, QLinearGradient, QBrush, QImageReader, QTransform, QIcon,
                           QPainterPath, QPalette, QTextCursor, QTextBlockFormat, QTextCharFormat, QRadialGradient, QPainterPathStroker, QFontMetricsF)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QGraphicsTextItem, QToolBar, QFileDialog, QSizePolicy, QColorDialog, QFontDialog, QSpinBox,
    QGraphicsItem, QInputDialog, QProgressDialog, QDialog, QTabWidget, QGridLayout, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QDialogButtonBox, QFormLayout, QComboBox, QLabel, QSlider, QDoubleSpinBox, QWidget, QVBoxLayout, QDockWidget, QMessageBox, QScrollArea, QToolButton, QMenu,
    QStyleOptionGraphicsItem, QCheckBox, QGraphicsDropShadowEffect, QHBoxLayout, QLineEdit, QRadioButton, QStackedWidget, QFrame,
    QStyledItemDelegate, QStyle, QButtonGroup, QFontComboBox, QMenuBar,
)

try:
    import numpy as np
except ImportError:
    np = None

try:
    import cv2
except ImportError:
    cv2 = None
HAS_VIDEO = cv2 is not None and np is not None      # video is decoded with OpenCV (the same decoder the export uses)

PRESETS = {
    "1080 x 1350 (4:5)": (1080, 1350),
    "1080 x 1080 (1:1)": (1080, 1080),
    "1080 x 1920 (9:16)": (1080, 1920),
    "1080 x 1440 (3:4)": (1080, 1440),
    "1920 x 1080 (16:9)": (1920, 1080),
}
FILTER = "Carousel project (*.carousel)"
DEFAULT = {"pw": 1080, "ph": 1350, "n": 3, "bg": "#ffffff", "items": []}


IMG_EXT = "*.png *.jpg *.jpeg *.jfif *.jpe *.webp *.bmp *.heic *.heif"
VID_EXT = "*.mp4 *.mov *.m4v *.3gp *.hevc *.h264 *.mkv *.avi *.webm"


def read_image(path):
    """File bytes. iPhone HEIC/HEIF is converted to a high-quality JPEG (orientation applied)."""
    if Path(path).suffix.lower() in (".heic", ".heif"):
        import io
        from PIL import Image, ImageOps
        import pillow_heif
        pillow_heif.register_heif_opener()
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=95)
        return buf.getvalue()
    return Path(path).read_bytes()


def to_pixmap(raw):
    """Bytes -> QPixmap, honouring EXIF rotation (iPhone JPEGs)."""
    buf = QBuffer()
    buf.setData(raw)
    buf.open(QIODevice.ReadOnly)
    rd = QImageReader(buf)
    rd.setAutoTransform(True)
    img = rd.read()
    return QPixmap.fromImage(img) if not img.isNull() else QPixmap()


def apply_flip(it):
    """Mirror a layer about its own centre (data keys: 2 = flip horizontally, 3 = flip vertically)."""
    c = it.boundingRect().center()
    t = QTransform()
    t.translate(c.x(), c.y())
    t.scale(-1 if it.data(2) else 1, -1 if it.data(3) else 1)
    t.translate(-c.x(), -c.y())
    it.setTransform(t)


def set_swatch(btn, color, text=None):
    """Colour button: a rounded colour chip as the icon (the button itself keeps the normal look)."""
    pm = QPixmap(40, 40)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 90), 2))
    c = QColor(color)
    if c.alpha() < 255:      # show transparency as a checkerboard under the colour
        chip = QPainterPath()
        chip.addRoundedRect(QRectF(3, 3, 34, 34), 9, 9)
        p.save()
        p.setClipPath(chip)
        for yy in range(0, 40, 8):
            for xx in range(0, 40, 8):
                p.fillRect(xx, yy, 8, 8, QColor(200, 200, 200) if (xx + yy) // 8 % 2 else QColor(120, 120, 120))
        p.restore()
    p.setBrush(c)
    p.drawRoundedRect(QRectF(3, 3, 34, 34), 9, 9)
    p.end()
    btn.setIcon(QIcon(pm))
    btn.setIconSize(QSize(20, 20))
    if text is not None:
        btn.setText(text)


def slider_spin(lay, label, lo, hi, on_value, on_release=None):
    """Draggable slider with a whole-number box under it. on_value(v, dragging). Returns (slider, spin, set_quietly)."""
    if label:
        lay.addWidget(QLabel(label))
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    sp = QSpinBox()
    sp.setRange(lo, hi)
    sp.setKeyboardTracking(False)

    def moved(v):
        sp.blockSignals(True)
        sp.setValue(v)
        sp.blockSignals(False)
        on_value(v, s.isSliderDown())
    s.valueChanged.connect(moved)
    sp.valueChanged.connect(s.setValue)
    if on_release:
        s.sliderReleased.connect(on_release)
    lay.addWidget(s)
    lay.addWidget(sp)

    def set_quiet(v):
        for w in (s, sp):
            w.blockSignals(True)
            w.setValue(int(v))
            w.blockSignals(False)
    return s, sp, set_quiet


ALIGNS = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight, "justify": Qt.AlignJustify}


class TextItem(QGraphicsTextItem):
    """Text layer. Not editable until double-clicked (so it can be selected / dragged normally)."""
    def __init__(self, text=""):
        super().__init__(text)
        self.align, self.box_w = "left", 0          # box_w 0 = auto width, >0 = manual wrap width
        self.line_h, self.indent = 100, 0            # line spacing in percent, indent level (0..10)
        self.outline_w, self.outline = 0, QColor("#000000")   # text outline width (px) + colour
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self._fitting = False
        self.document().contentsChanged.connect(self.fit_width)

    pad_bottom = 0

    def boundingRect(self):
        """Tight line spacing shrinks Qt's line boxes, so glyphs poke out below the text box and were clipped.
        Extend the box by that overhang so nothing is cut."""
        return super().boundingRect().adjusted(0, 0, 0, self.pad_bottom)

    def fit_width(self):
        """Auto width: size the box to the widest line. Without a text width Qt ignores alignment entirely."""
        if self.box_w > 0 or self._fitting:
            return
        self._fitting = True
        self.setTextWidth(-1)
        self.setTextWidth(math.ceil(self.document().idealWidth()) + 1)
        self._fitting = False

    def apply_layout(self):
        spacing = QFontMetricsF(self.font()).lineSpacing()
        pad = math.ceil(spacing * max(0.0, 1 - self.line_h / 100.0)) + math.ceil(self.outline_w / 2)
        if pad != self.pad_bottom:
            self.prepareGeometryChange()
            self.pad_bottom = pad
        doc = self.document()
        opt = doc.defaultTextOption()
        opt.setAlignment(ALIGNS.get(self.align, Qt.AlignLeft))
        doc.setDefaultTextOption(opt)
        doc.setDocumentMargin(4 + math.ceil(self.outline_w / 2))   # keeps the outline inside the box
        doc.setIndentWidth(40)
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        cur.select(QTextCursor.SelectionType.Document)
        bf = QTextBlockFormat()
        bf.setLineHeight(float(self.line_h), 1)      # 1 = ProportionalHeight (percent of normal)
        bf.setIndent(int(self.indent))
        cur.mergeBlockFormat(bf)
        cf = QTextCharFormat()
        cf.setTextOutline(QPen(self.outline, self.outline_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                          if self.outline_w > 0 else QPen(Qt.NoPen))
        cur.mergeCharFormat(cf)
        cur.endEditBlock()
        if self.box_w > 0:
            self.setTextWidth(self.box_w)
        else:
            self.fit_width()
        self.sync_origin()

    def sync_origin(self):
        """Keep the rotate/scale/flip origin on the box centre after the box size changed, WITHOUT moving the text
        (its top-left corner stays put). A stale origin made rebuilt layers (undo/redo/snapshots) jump."""
        c = self.boundingRect().center()
        if self.transformOriginPoint() == c:
            return
        p0 = self.mapToScene(QPointF(0, 0))
        self.setTransformOriginPoint(c)
        apply_flip(self)
        p1 = self.mapToScene(QPointF(0, 0))
        if p0 != p1:
            self.moveBy(p0.x() - p1.x(), p0.y() - p1.y())

    def mouseDoubleClickEvent(self, e):
        if self.data(1):                              # locked layer: no editing
            return
        if self.textInteractionFlags() == Qt.NoTextInteraction:
            self.setTextInteractionFlags(Qt.TextEditorInteraction)   # also makes the item focusable
        self.setFocus(Qt.MouseFocusReason)
        super().mouseDoubleClickEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        cur = self.textCursor()
        cur.clearSelection()
        self.setTextCursor(cur)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.apply_layout()                           # re-assert spacing / indent / outline on typed text
        sc = self.scene()
        if sc and sc.on_change:
            sc.on_change()


class GridItem(QGraphicsItem):
    """Collage grid: rows x cols cells with gap + rounded corners. Cells hold photos (cover-fit) or a flat colour."""
    def __init__(self, rows=2, cols=2, w=800, h=800, gap=5, radius=0, fill="#d9d9d9", ids=None, pms=None):
        super().__init__()
        self.rows, self.cols, self.w, self.h, self.gap, self.radius = rows, cols, w, h, gap, radius
        self.fill = QColor(fill)
        self.cells = None                       # custom layout: list of (x0, y0, x1, y1) fractions; None = rows x cols
        self.skip = None                        # cell whose photo is being cropped (drawn empty meanwhile)
        n = rows * cols
        self.ids = (list(ids or []) + [None] * n)[:n]
        self.pms = (list(pms or []) + [None] * n)[:n]    # what is painted: the photo after crop + adjustments
        self.adjs = [{} for _ in range(n)]               # per-photo Edit Image settings
        self.crops = [None] * n                          # per-photo crop [l, t, r, b] fractions of the original
        self.fills = [None] * n                          # per-cell empty colour override (hex string); None = grid colour

    def fit_lists(self):
        n = self.count()
        self.ids = (self.ids + [None] * n)[:n]
        self.pms = (self.pms + [None] * n)[:n]
        self.adjs = (self.adjs + [{} for _ in range(n)])[:n]
        self.crops = (self.crops + [None] * n)[:n]
        self.fills = (self.fills + [None] * n)[:n]

    def boundingRect(self):
        return QRectF(0, 0, self.w, self.h)

    def count(self):
        return len(self.cells) if self.cells else self.rows * self.cols

    def cell_at(self, pt):
        """Index of the cell under pt (grid coordinates), or None (gap / outside)."""
        for i in range(self.count()):
            if self.cell_rect(i).contains(pt):
                return i
        return None

    def swap_cells(self, i, j):
        for lst in (self.ids, self.pms, self.adjs, self.crops, self.fills):
            lst[i], lst[j] = lst[j], lst[i]

    def set_cells(self, cells):
        self.cells = [tuple(c) for c in cells] if cells else None
        self.fit_lists()

    def set_dims(self, rows, cols):
        self.cells = None
        self.rows, self.cols = rows, cols
        self.fit_lists()

    def cell_rect(self, i):
        if self.cells:
            x0, y0, x1, y1 = self.cells[i]
            g = self.gap / 2
            return QRectF(x0 * self.w + (g if x0 > 1e-6 else 0), y0 * self.h + (g if y0 > 1e-6 else 0),
                          (x1 - x0) * self.w - (g if x0 > 1e-6 else 0) - (g if x1 < 1 - 1e-6 else 0),
                          (y1 - y0) * self.h - (g if y0 > 1e-6 else 0) - (g if y1 < 1 - 1e-6 else 0))
        r, c = divmod(i, self.cols)
        cw = (self.w - self.gap * (self.cols - 1)) / self.cols
        ch = (self.h - self.gap * (self.rows - 1)) / self.rows
        return QRectF(c * (cw + self.gap), r * (ch + self.gap), cw, ch)

    def paint(self, p, opt, widget=None):
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        for i in range(self.count()):
            rect = self.cell_rect(i)
            path = QPainterPath()
            path.addRoundedRect(rect, self.radius, self.radius)
            pm = self.pms[i] if i != self.skip else None
            if pm is not None and not pm.isNull():
                p.save()
                p.setClipPath(path, Qt.IntersectClip)
                s = max(rect.width() / pm.width(), rect.height() / pm.height())
                tw, th = pm.width() * s, pm.height() * s
                p.drawPixmap(QRectF(rect.center().x() - tw / 2, rect.center().y() - th / 2, tw, th),
                             pm, QRectF(pm.rect()))
                p.restore()
            else:
                p.fillPath(path, QColor(self.fills[i]) if i < len(self.fills) and self.fills[i] else self.fill)


class CellRef:
    """Stands in for an image layer so the Edit Image panel can edit ONE photo inside a grid."""
    def __init__(self, grid, i):
        self.grid, self.i = grid, i

    def data(self, k):
        g = self.grid
        if k == 0:
            return g.ids[self.i]
        if k == 5:
            return json.dumps(g.adjs[self.i] or {})
        if k == 6:
            return json.dumps(g.crops[self.i])
        return None

    def setData(self, k, v):
        if k == 5:
            self.grid.adjs[self.i] = json.loads(v or "{}")

    def refresh(self, main, preview):
        if self.grid.scene() is None:
            raise RuntimeError("grid removed")
        main.rebuild_cell(self.grid, self.i, preview)


class ShapeItem(QGraphicsItem):
    """Rectangle / ellipse / line. Fill, per-corner radius, shadow, and a border (style, thickness, joins, position)."""
    def __init__(self, kind="rect", w=500, h=300, fill="#ff5078", border="#000000", bw=0):
        super().__init__()
        self.kind, self.w, self.h, self.bw = kind, w, h, bw
        self.fill, self.border = QColor(fill), QColor(border)
        self.radius, self.corners = 0, [True, True, True, True]      # corners: top-left, top-right, bottom-right, bottom-left
        self.dash, self.bpos, self.bjoin = "solid", "center", "miter"  # solid|dash|dot, center|inside|outside, miter|round|bevel
        self.shadow = False
        self.no_fill, self.no_border = False, False     # transparent inside (frame) / invisible border

    def set_shadow(self, on):
        self.shadow = bool(on)
        if on:
            fx = QGraphicsDropShadowEffect()
            fx.setBlurRadius(30)
            fx.setOffset(12, 16)
            fx.setColor(QColor(0, 0, 0, 150))
            self.setGraphicsEffect(fx)
        else:
            self.setGraphicsEffect(None)

    def margin(self):
        if self.kind == "line":
            return max(self.bw, 4) / 2
        if self.bw <= 0:
            return 0
        m = {"inside": 0, "center": self.bw / 2, "outside": self.bw}.get(self.bpos, self.bw / 2)
        return m + (self.bw * 0.25 if self.bjoin == "miter" and self.bpos != "inside" else 0)

    def boundingRect(self):
        m = self.margin()
        return QRectF(-m, -m, self.w + 2 * m, self.h + 2 * m)

    def shape_path(self):
        r, path = QRectF(0, 0, self.w, self.h), QPainterPath()
        if self.kind == "ellipse":
            path.addEllipse(r)
            return path
        rad = max(0.0, min(self.radius, r.width() / 2, r.height() / 2))
        tl, tr, br, bl = [rad if c else 0 for c in self.corners]
        path.moveTo(r.left() + tl, r.top())
        path.lineTo(r.right() - tr, r.top())
        if tr:
            path.arcTo(r.right() - 2 * tr, r.top(), 2 * tr, 2 * tr, 90, -90)
        path.lineTo(r.right(), r.bottom() - br)
        if br:
            path.arcTo(r.right() - 2 * br, r.bottom() - 2 * br, 2 * br, 2 * br, 0, -90)
        path.lineTo(r.left() + bl, r.bottom())
        if bl:
            path.arcTo(r.left(), r.bottom() - 2 * bl, 2 * bl, 2 * bl, 270, -90)
        path.lineTo(r.left(), r.top() + tl)
        if tl:
            path.arcTo(r.left(), r.top(), 2 * tl, 2 * tl, 180, -90)
        path.closeSubpath()
        return path

    def make_pen(self, width, k=1.0):
        """k scales dash lengths (0.5 when the stroke is doubled for inside / outside borders)."""
        pen = QPen(self.border, width)
        pen.setJoinStyle({"miter": Qt.MiterJoin, "round": Qt.RoundJoin, "bevel": Qt.BevelJoin}.get(self.bjoin, Qt.MiterJoin))
        if self.dash == "dash":
            pen.setCapStyle(Qt.FlatCap)
            pen.setDashPattern([4 * k, 2.5 * k])
        elif self.dash == "dot":
            pen.setCapStyle(Qt.RoundCap)
            pen.setDashPattern([0.01, 2.2 * k])
        else:
            pen.setCapStyle(Qt.RoundCap if self.kind == "line" else Qt.FlatCap)
        return pen

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        if self.kind == "line":
            if self.no_border:
                return
            p.setPen(self.make_pen(max(self.bw, 4)))
            p.drawLine(QPointF(0, self.h / 2), QPointF(self.w, self.h / 2))
            return
        path = self.shape_path()
        if not self.no_fill:
            p.setPen(Qt.NoPen)
            p.setBrush(self.fill)
            p.drawPath(path)
        if self.bw <= 0 or self.no_border:
            return
        p.setBrush(Qt.NoBrush)
        if self.bpos == "center":
            p.setPen(self.make_pen(self.bw))
            p.drawPath(path)
            return
        p.save()                                   # inside / outside: stroke double width, keep only the wanted half
        if self.bpos == "inside":
            p.setClipPath(path, Qt.IntersectClip)
        else:
            big = QPainterPath()
            big.addRect(QRectF(0, 0, self.w, self.h).adjusted(-self.bw * 3, -self.bw * 3, self.bw * 3, self.bw * 3))
            p.setClipPath(big.subtracted(path), Qt.IntersectClip)
        p.setPen(self.make_pen(self.bw * 2, 0.5))
        p.drawPath(path)
        p.restore()

    def shape(self):
        """A frame (transparent inside) is only clickable on its border, so photos inside it stay selectable."""
        if self.no_fill and self.kind != "line" and self.bw > 0 and not self.no_border:
            st = QPainterPathStroker()
            st.setWidth(max(self.bw * 2, 28))
            return st.createStroke(self.shape_path())
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def mouseDoubleClickEvent(self, e):
        sc = self.scene()
        if sc and sc.on_shape_edit and not self.data(1):
            sc.on_shape_edit()


def frame_pixmap(img, crop, adj, maxdim=None):
    """One video frame -> picture after crop + Edit Image settings (filters / adjustments)."""
    W, H = img.width(), img.height()
    if crop:
        x0, y0 = int(crop[0] * W), int(crop[1] * H)
        img = img.copy(x0, y0, max(1, int(crop[2] * W) - x0), max(1, int(crop[3] * H) - y0))
    if maxdim and max(img.width(), img.height()) > maxdim:
        img = img.scaled(maxdim, maxdim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if adj and np is not None:
        rgb, alpha = qimage_to_np(img)
        return np_to_pixmap(adjust_rgb(rgb, adj), alpha)
    return QPixmap.fromImage(img)


_WORKERS = weakref.WeakSet()


def stop_all_video_workers():
    for w in list(_WORKERS):
        try:
            w.shutdown()
        except Exception:
            pass


atexit.register(stop_all_video_workers)

_WATCH = []          # (worker, weak reference to its video layer): strong refs keep a thread alive until it is stopped
_SWEEP = {"timer": None}


def _sweep_workers():
    """Stop the thread of any video layer that no longer exists (deleted, undone, scene cleared)."""
    for entry in list(_WATCH):
        w, ref = entry
        it = ref()
        try:
            gone = it is None or (it.scene() is None and it.was_in_scene)
        except RuntimeError:
            gone = True
        if gone:
            w.shutdown()
            _WATCH.remove(entry)


def watch_worker(worker, item):
    _WATCH.append((worker, weakref.ref(item)))
    if _SWEEP["timer"] is None and QApplication.instance() is not None:
        t = QTimer(QApplication.instance())
        t.setInterval(1000)
        t.timeout.connect(_sweep_workers)
        t.start()
        _SWEEP["timer"] = t

if HAS_VIDEO:
    class VideoWorker(QThread):
        """Decodes, crops, filters and paces one video on its own thread, so the editor never waits for a frame.
        The window only receives finished pictures (queued signal) - no decoding or filtering happens on the GUI thread."""
        ready = Signal(object, int, int, int, int)  # picture, position ms, native width, native height, sequence number
        failed = Signal(str)

        def __init__(self, path):
            super().__init__()
            self.path = path
            self.crop, self.adj, self.trim = None, {}, None
            self.playing, self.seek_to, self.redo, self.stop_flag = True, None, False, False
            self.dur_ms, self.fps, self.pos_ms, self.W, self.H = 0, 30.0, 0, 0, 0
            self.raw = None                      # last decoded full-size frame (BGR)
            self.wake = threading.Event()
            self.fails = 0
            self.lim = 512                       # preview size while playing with filters: adapts to the PC's speed
            self.avg = 0.0                       # average time to filter one frame
            self.seq, self.inflight = 0, 0
            self.lock = threading.Lock()
            self.pool = None
            self.settle = False
            self.pool_n = max(1, min(4, (os.cpu_count() or 2) // 2))
            _WORKERS.add(self)

        def shutdown(self):
            self.stop_flag = True
            self.wake.set()
            if self.isRunning() and QThread.currentThread() is not self:
                self.wait(1500)

        def poke(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
            if kw.get("playing") is False:
                self.settle = True
            self.wake.set()

        def frame_range(self):
            if self.trim:
                a = int(self.trim[0] / 1000.0 * self.fps)
                b = int(self.trim[1] / 1000.0 * self.fps)
            else:
                a, b = 0, self.n
            a = min(max(a, 0), max(self.n - 1, 0))
            return a, min(max(b, a + 1), self.n)

        def make_picture(self, fr, lim=None):
            crop, adj = self.crop, self.adj
            H, W = fr.shape[:2]
            if crop:
                x0, y0 = int(crop[0] * W), int(crop[1] * H)
                fr = fr[y0:max(y0 + 1, int(crop[3] * H)), x0:max(x0 + 1, int(crop[2] * W))]
            lim = lim or (int(self.lim) if adj else 1280)
            h, w = fr.shape[:2]
            if max(h, w) > lim:
                k = lim / max(h, w)
                fr = cv2.resize(fr, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
            if adj:
                try:
                    rgb = (np.clip(adjust_rgb(rgb.astype(np.float32) / 255.0, adj), 0, 1) * 255 + 0.5).astype(np.uint8)
                    self.fails = 0
                except Exception as e:           # never let a filter take the app down
                    self.fails += 1
                    if self.fails >= 3:
                        self.adj = {}
                        self.failed.emit(f"This filter could not be applied to the video preview ({e}). Preview shown without it.")
            rgb = np.ascontiguousarray(rgb)
            h, w = rgb.shape[:2]
            return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()

        def emit_frame(self, fr, idx, sharp=False):
            """Still frame (seek / paused / settings changed): done right here at high quality."""
            self.raw = fr
            self.pos_ms = int(idx / self.fps * 1000)
            self.seq += 1
            self.ready.emit(self.make_picture(fr, 1280 if sharp else None), self.pos_ms, self.W, self.H, self.seq)

        def submit_frame(self, fr, idx):
            """Playing: filter the frame on a pool thread so decoding keeps its pace; the preview size adapts."""
            self.raw = fr
            pos = int(idx / self.fps * 1000)
            self.pos_ms = pos
            if not self.adj:
                self.seq += 1
                self.ready.emit(self.make_picture(fr), pos, self.W, self.H, self.seq)
                return
            if self.pool is None:
                from concurrent.futures import ThreadPoolExecutor
                self.pool = ThreadPoolExecutor(max_workers=self.pool_n)
            self.seq += 1
            with self.lock:
                self.inflight += 1
            self.pool.submit(self.filter_job, fr, pos, self.seq)

        def filter_job(self, fr, pos, seq):
            try:
                t0 = time.perf_counter()
                img = self.make_picture(fr)
                dt = time.perf_counter() - t0
                self.avg = dt if self.avg == 0 else self.avg * 0.8 + dt * 0.2
                budget = self.pool_n / self.fps                        # time each frame may take to keep real time
                if self.avg > budget * 0.85:
                    self.lim = max(288, self.lim * 0.88)
                elif self.avg < budget * 0.45 and self.lim < 640:
                    self.lim = min(640, self.lim * 1.06)
                if not self.stop_flag:
                    self.ready.emit(img, pos, self.W, self.H, seq)
            except Exception as e:
                self.fails += 1
                if self.fails >= 3:
                    self.adj = {}
                    self.failed.emit(f"This filter could not be applied to the video preview ({e}).")
            finally:
                with self.lock:
                    self.inflight -= 1

        def run(self):
            try:
                cap = cv2.VideoCapture(self.path)
                if not cap.isOpened():
                    self.failed.emit(f"Could not open {Path(self.path).name}. HEVC / H.265 videos may need the Microsoft 'HEVC Video Extensions'.")
                    return
                self.n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                self.W, self.H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.dur_ms = int(self.n / self.fps * 1000) if self.n else 0
                a, b = self.frame_range()
                idx = a
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                due = None
                while not self.stop_flag:
                    a, b = self.frame_range()
                    if self.seek_to is not None:
                        idx = min(max(int(self.seek_to / 1000.0 * self.fps), 0), max(self.n - 1, 0))
                        self.seek_to = None
                        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                        ok, fr = cap.read()
                        if ok:
                            self.emit_frame(fr, idx)
                            idx += 1
                        due = None
                        continue
                    if self.redo:
                        self.redo = False
                        if self.raw is not None:
                            self.emit_frame(self.raw, int(round(self.pos_ms / 1000.0 * self.fps)), sharp=True)
                        continue
                    if not self.playing:
                        if self.settle and self.raw is not None:       # just paused: redraw this frame sharp
                            self.settle = False
                            self.emit_frame(self.raw, int(round(self.pos_ms / 1000.0 * self.fps)), sharp=True)
                        self.wake.wait(0.05)
                        self.wake.clear()
                        due = None
                        continue
                    now = time.monotonic()
                    if due is None:
                        due = now
                    if now < due:
                        time.sleep(min(due - now, 0.01))
                        continue
                    if idx >= b or idx < a:
                        idx = a
                        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    behind = int((now - due) * self.fps)
                    if behind >= 2:                  # filters / slow PC: drop frames to stay in time instead of lagging
                        skip = min(behind, b - idx - 1)
                        for _ in range(max(skip, 0)):
                            cap.grab()
                            idx += 1
                        due += max(skip, 0) / self.fps
                    if self.adj and self.inflight >= self.pool_n:      # filters are busy: skip this frame, keep real time
                        cap.grab()
                        idx += 1
                        due += 1.0 / self.fps
                        continue
                    ok, fr = cap.read()
                    if not ok:
                        idx = a
                        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                        due = None
                        time.sleep(0.02)
                        continue
                    self.submit_frame(fr, idx)
                    idx += 1
                    due += 1.0 / self.fps
                cap.release()
                if self.pool is not None:
                    self.pool.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                self.failed.emit(f"Video playback stopped: {e}")

    class VideoBridge(QObject):
        """Lives on the GUI thread: receives the worker's pictures and hands them to the item."""
        def __init__(self, item):
            super().__init__()
            self.ref = weakref.ref(item)

        @Slot(object, int, int, int, int)
        def on_ready(self, img, pos, W, H, seq):
            it = self.ref()
            if it is not None:
                try:
                    it.got_frame(img, W, H, seq)
                except RuntimeError:
                    pass

        @Slot(str)
        def on_failed(self, msg):
            it = self.ref()
            if it is not None:
                try:
                    sc = it.scene()
                    if sc and sc.on_error:
                        sc.on_error(f"{Path(it.path).name}: {msg}")
                except RuntimeError:
                    pass

    class VideoItem(QGraphicsItem):
        """Video layer. Plays silently in the editor; shows the cropped part with Edit Image filters applied live.
        crop = [l, t, r, b] fractions of the frame; trim = (start_ms, end_ms) part of the clip that is kept;
        data(5) = Edit Image settings (same as photos)."""
        def __init__(self, path, size=None, fit_w=864, crop=None, adj=None, trim=None, muted=False):
            super().__init__()
            self.muted = bool(muted)             # True = this video adds no sound to the exported slide
            self.path, self.fit_w = path, (fit_w if size is None else None)
            self._size = QSizeF(size or QSizeF(640, 360))
            self.crop, self.trim = crop, (tuple(trim) if trim else None)
            self.setData(5, json.dumps(adj or {}))
            self.disp = None                     # latest finished picture (QImage)
            self.native = (0, 0)
            self._still = None
            self.worker = VideoWorker(path)
            self.worker.crop, self.worker.adj, self.worker.trim = self.crop, self.adj(), self.trim
            self.bridge = VideoBridge(self)
            self.worker.ready.connect(self.bridge.on_ready)
            self.worker.failed.connect(self.bridge.on_failed)
            self.was_in_scene = False
            self.last_seq = 0
            watch_worker(self.worker, self)

        def itemChange(self, change, value):
            if change == QGraphicsItem.ItemSceneHasChanged:
                if value is not None:
                    self.was_in_scene = True
                if value is not None and not self.worker.isRunning():
                    self.worker.stop_flag = False
                    self.worker.start()
                elif value is None:
                    self.worker.shutdown()       # removed from the canvas (delete / undo): stop its thread
            return super().itemChange(change, value)

        # ---- geometry
        def size(self):
            return QSizeF(self._size)

        def setSize(self, sz):
            self.prepareGeometryChange()
            self._size = QSizeF(sz)
            self.update()

        def boundingRect(self):
            return QRectF(0, 0, self._size.width(), self._size.height())

        def adj(self):
            return json.loads(self.data(5) or "{}")

        # ---- playback
        def duration(self):
            return self.worker.dur_ms

        def pause(self):
            self.worker.poke(playing=False)

        def play(self):
            self.worker.poke(playing=True)

        def toggle_play(self):
            self.worker.poke(playing=not self.worker.playing)

        def seek(self, ms):
            self.worker.poke(playing=False, seek_to=int(ms))

        def set_trim(self, trim):
            self.trim = tuple(trim) if trim else None
            self.worker.trim = self.trim
            self.worker.poke(seek_to=self.trim[0] if self.trim else 0)

        def refresh(self, preview=True):
            """Edit Image settings or crop changed: redraw the current frame."""
            self._still = None
            self.worker.crop, self.worker.adj = self.crop, self.adj()
            self.worker.poke(redo=True)

        def poster(self):
            """The current frame at full size (QImage), for cropping."""
            fr = self.worker.raw
            if fr is None:
                return None
            rgb = np.ascontiguousarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
            h, w = rgb.shape[:2]
            return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()

        # ---- drawing
        def got_frame(self, img, W, H, seq=0):
            if seq and seq < self.last_seq:      # a slower, older frame arriving late: never show it
                return
            self.last_seq = seq
            self.disp = img
            self.native = (W, H)
            if self.fit_w and W > 0:             # first frame: size the layer to the (cropped) picture
                c = self.crop or [0, 0, 1, 1]
                rw, rh = (c[2] - c[0]) * W, (c[3] - c[1]) * H
                if rw > 0:
                    self.setSize(QSizeF(self.fit_w, self.fit_w * rh / rw))
                    self.fit_w = None
                    self.setTransformOriginPoint(self.boundingRect().center())
                    if self.scene() and self.scene().on_change:
                        self.scene().on_change()
            self.update()

        def paint(self, p, opt, w=None):
            r = self.boundingRect()
            sc = self.scene()
            if getattr(sc, "exporting", False) and not getattr(sc, "live_preview", False) and self.worker.raw is not None:     # still-image export: full detail
                key = (self.worker.pos_ms, json.dumps(self.crop), self.data(5))
                if self._still is None or self._still[0] != key:
                    self._still = (key, frame_pixmap(self.poster(), self.crop, self.adj(), None))
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawPixmap(r, self._still[1], QRectF(self._still[1].rect()))
            elif self.disp is not None:
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawImage(r, self.disp)
            else:
                p.fillRect(r, QColor(20, 20, 24))

LAYERS = (QGraphicsPixmapItem, TextItem, ShapeItem, GridItem) + ((VideoItem,) if HAS_VIDEO else ())


class Canvas(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.pw, self.ph, self.n, self.rows = 1080, 1350, 3, 1
        self.bg2, self.bg_angle, self.bg_mode = QColor('#7b5cff'), 0, 'solid'
        self.bg_tex, self.tex_pm = None, None
        self.bg = QColor("white")
        self.show_guides = True
        self.on_change = None
        self.on_transform = None
        self.on_error = None
        self.on_shape_edit = None
        self.crop_overlay = None
        self.exporting = False
        self.gdrag = None                        # photo being carried from one grid cell to another
        self.gtimer = QTimer()
        self.gtimer.setSingleShot(True)
        self.gtimer.timeout.connect(self.grid_pickup)
        self.drag = None
        self.move = None
        self.snap_lines = []
        self.snap_enabled = True
        self.resize_canvas()

    def resize_canvas(self):
        self.setSceneRect(-2000, -2000, self.n * self.pw + 4000, self.rows * self.ph + 4000)
        self.update()

    def canvas_rect(self):
        return QRectF(0, 0, self.n * self.pw, self.rows * self.ph)

    def drawBackground(self, p, rect):
        p.fillRect(rect, PASTEBOARD)
        if not self.exporting:                       # soft dot grid on the workspace (like design tools), zoom aware
            px = self.px()
            step = 24.0 * px
            sp = 20.0 * 2 ** math.ceil(math.log2(max(step / 20.0, 0.05)))
            x0, y0 = math.floor(rect.left() / sp) * sp, math.floor(rect.top() / sp) * sp
            nx, ny = int(rect.width() / sp) + 2, int(rect.height() / sp) + 2
            if 0 < nx * ny < 12000:
                pen = QPen(UI_DOT, 1.6 * px)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawPoints(QPolygonF([QPointF(x0 + i * sp, y0 + j * sp) for j in range(ny) for i in range(nx)]))
        r = self.canvas_rect()
        if self.bg_mode == "gradient":
            a = math.radians(self.bg_angle)
            hl = abs(r.width() / 2 * math.cos(a)) + abs(r.height() / 2 * math.sin(a))
            d = QPointF(math.cos(a), math.sin(a)) * hl
            g = QLinearGradient(r.center() - d, r.center() + d)   # spans ALL slides = seamless
            g.setColorAt(0, self.bg)
            g.setColorAt(1, self.bg2)
            p.fillRect(r, QBrush(g))
        elif self.bg_mode == "texture" and self.tex_pm:
            p.fillRect(r, QBrush(self.tex_pm))
        else:
            p.fillRect(r, self.bg)

    # ---------- on-canvas handles ----------
    def px(self):
        v = self.views()
        return 1 / v[0].transform().m11() if v else 1.0

    def single(self):
        sel = self.selectedItems()
        return sel[0] if len(sel) == 1 else None

    def handle_points(self, it):
        br = it.boundingRect()
        corners = [it.mapToScene(q) for q in (br.topLeft(), br.topRight(), br.bottomRight(), br.bottomLeft())]
        top = it.mapToScene(QPointF(br.center().x(), br.top()))
        c = it.mapToScene(it.transformOriginPoint())
        v = top - c
        ln = math.hypot(v.x(), v.y())
        v = QPointF(0, -1) if ln == 0 else v / ln
        return corners, top, top + v * 36 * self.px(), c

    def hit(self, pos):
        it = self.single()
        if not it or it.data(1) or self.crop_overlay is not None:
            return None
        corners, _, rot, _ = self.handle_points(it)
        tol = 10 * self.px()
        near = lambda q: math.hypot(pos.x() - q.x(), pos.y() - q.y()) < tol
        if near(rot):
            return "rot"
        return "scale" if any(near(q) for q in corners) else None

    def drawForeground(self, p, rect):
        if self.exporting:
            return
        gd = self.gdrag
        if gd and gd["active"] and gd["grid"].scene() is self:
            g, px = gd["grid"], self.px()
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            poly = lambda i: g.mapToScene(QPolygonF(g.cell_rect(i)))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawPolygon(poly(gd["src"]))
            if gd["dst"] is not None and gd["dst"] != gd["src"]:
                pen = QPen(QColor("#2ee66b"), 4)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.setBrush(QColor(46, 230, 107, 60))
                p.drawPolygon(poly(gd["dst"]))
            pm = g.pms[gd["src"]]
            if pm is not None and not pm.isNull():
                wd = 150 * px
                hh = wd * pm.height() / pm.width()
                r = QRectF(gd["cur"].x() - wd / 2, gd["cur"].y() - hh / 2, wd, hh)
                p.setOpacity(0.92)
                p.drawPixmap(r, pm, QRectF(pm.rect()))
                p.setOpacity(1)
                pen = QPen(QColor("white"), 3)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
            p.restore()
        if self.show_guides:
            pen = QPen(QColor(255, 80, 120), 3, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            for i in range(1, self.n):
                p.drawLine(i * self.pw, 0, i * self.pw, self.rows * self.ph)
            for j in range(1, self.rows):
                p.drawLine(0, j * self.ph, self.n * self.pw, j * self.ph)
            pen = QPen(QColor(200, 200, 200), 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawRect(self.canvas_rect())
        px = self.px()                                # slide names above each slide
        f = QFont(p.font())
        f.setPixelSize(max(1, int(round(12 * px))))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(UI_LABEL)
        for k in range(self.n * self.rows):
            p.drawText(QPointF((k % self.n) * self.pw + 2 * px, (k // self.n) * self.ph - 9 * px), f"Slide {k + 1}")
        if self.snap_lines:
            pen = QPen(QColor(0, 220, 200), 2)
            pen.setCosmetic(True)
            p.setPen(pen)
            for kind, t in self.snap_lines:
                if kind == "v":
                    p.drawLine(QPointF(t, -40), QPointF(t, self.rows * self.ph + 40))
                elif kind == "h":
                    p.drawLine(QPointF(-40, t), QPointF(self.n * self.pw + 40, t))
                else:   # rotation guide: line through the layer centre at the snapped angle
                    cx, cy, ang = t
                    v = QPointF(math.sin(math.radians(ang)), -math.cos(math.radians(ang))) * 3000
                    p.drawLine(QPointF(cx, cy) - v, QPointF(cx, cy) + v)
        it = self.single()
        if it:
            px = self.px()
            corners, top, rot, _ = self.handle_points(it)
            p.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(255, 170, 40) if it.data(1) else QColor(80, 160, 255), 2)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(QPolygonF(corners))
            if not it.data(1) and self.crop_overlay is None:
                p.drawLine(top, rot)
                p.setBrush(QColor("white"))
                for q in corners:
                    p.drawRect(QRectF(q.x() - 5 * px, q.y() - 5 * px, 10 * px, 10 * px))
                p.drawEllipse(rot, 6 * px, 6 * px)

    def snap_targets(self, exclude):
        xt = [i * self.pw / 2 for i in range(2 * self.n + 1)]       # slide edges + centers
        yt = [j * self.ph / 2 for j in range(2 * self.rows + 1)]
        for o in self.items():
            if isinstance(o, LAYERS) and o not in exclude:           # other layers' edges + centers
                r = o.sceneBoundingRect()
                xt += [r.left(), r.center().x(), r.right()]
                yt += [r.top(), r.center().y(), r.bottom()]
                if isinstance(o, GridItem):                          # every cell of a grid is a guide too
                    for i in range(o.count()):
                        c = o.mapToScene(o.cell_rect(i)).boundingRect()
                        xt += [c.left(), c.center().x(), c.right()]
                        yt += [c.top(), c.center().y(), c.bottom()]
        return {"v": xt, "h": yt}

    @staticmethod
    def snap_axis(feats, targets, thr):
        best = None
        for f in feats:
            for t in targets:
                d = t - f
                if abs(d) < thr and (best is None or abs(d) < abs(best[0])):
                    best = (d, t)
        return best if best else (0.0, None)

    def do_move(self, e):
        mv = self.move
        items = [t for t in mv["items"] if t[0].scene() is self]
        delta = e.scenePos() - mv["m0"]
        for it, p0 in items:
            it.setPos(p0 + delta)
        self.snap_lines = []
        if self.snap_enabled and not (e.modifiers() & Qt.AltModifier) and items:
            r = QRectF()
            for it, _ in items:
                r = r.united(it.sceneBoundingRect())
            thr = 8 * self.px()
            tg = self.snap_targets([t[0] for t in items])
            xt, yt = tg["v"], tg["h"]
            dx, tx = self.snap_axis((r.left(), r.center().x(), r.right()), xt, thr)
            dy, ty = self.snap_axis((r.top(), r.center().y(), r.bottom()), yt, thr)
            for it, _ in items:
                it.setPos(it.pos() + QPointF(dx, dy))
            if tx is not None:
                self.snap_lines.append(("v", tx))
            if ty is not None:
                self.snap_lines.append(("h", ty))
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            kind = self.hit(e.scenePos())
            if kind:
                it = self.single()
                c = it.mapToScene(it.transformOriginPoint())
                m = e.scenePos()
                self.drag = {"kind": kind, "item": it, "c": c, "s0": it.scale(), "r0": it.rotation(),
                             "d0": max(math.hypot(m.x() - c.x(), m.y() - c.y()), 1e-6),
                             "a0": math.degrees(math.atan2(m.y() - c.y(), m.x() - c.x()))}
                e.accept()
                return
        super().mousePressEvent(e)
        self.move = None
        if e.button() == Qt.LeftButton:
            g = self.mouseGrabberItem()
            sel = [i for i in self.selectedItems() if isinstance(i, LAYERS) and not i.data(1)]
            if g is not None and g in sel and not (isinstance(g, TextItem) and g.hasFocus()):
                self.move = {"items": [(i, QPointF(i.pos())) for i in sel], "m0": e.scenePos()}
            self.gdrag = None
            if isinstance(g, GridItem) and not g.data(1) and not (e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)):
                i = g.cell_at(g.mapFromScene(e.scenePos()))
                if i is not None and g.pms[i] is not None and not g.pms[i].isNull():
                    self.gdrag = {"grid": g, "src": i, "dst": None, "p0": e.scenePos(), "cur": e.scenePos(), "active": False}
                    self.gtimer.start(280)             # hold ~0.3 s on a photo to pick it up

    def grid_pickup(self):
        gd = self.gdrag
        if gd and not gd["active"] and self.drag is None:
            gd["active"] = True
            self.move = None                           # the grid itself stays put
            for v in self.views():
                v.viewport().setCursor(Qt.ClosedHandCursor)
            self.update()

    def mouseMoveEvent(self, e):
        d = self.drag
        gd = self.gdrag
        if gd and (e.buttons() & Qt.LeftButton):
            if gd["active"]:                           # carrying a photo: follow the pointer, highlight the target cell
                g = gd["grid"]
                gd["cur"] = e.scenePos()
                gd["dst"] = g.cell_at(g.mapFromScene(e.scenePos()))
                self.update()
                e.accept()
                return
            m = e.scenePos() - gd["p0"]
            if abs(m.x()) + abs(m.y()) > 6 * self.px():  # moved before the hold time: it is a normal grid move
                self.gdrag = None
                self.gtimer.stop()
        if d is None and self.move and (e.buttons() & Qt.LeftButton):
            self.do_move(e)
            e.accept()
            return
        if d is None:
            kind = self.hit(e.scenePos())
            cur = {"rot": Qt.CrossCursor, "scale": Qt.SizeFDiagCursor}.get(kind, Qt.ArrowCursor)
            if self.crop_overlay is not None:
                cur = self.crop_overlay.cursor_at(e.scenePos())
            for v in self.views():
                v.viewport().setCursor(cur)
            super().mouseMoveEvent(e)
            return
        it = d["item"]
        if it.scene() is not self:
            self.drag = None
            return
        m, c = e.scenePos(), d["c"]
        free = not self.snap_enabled or bool(e.modifiers() & Qt.AltModifier)
        self.snap_lines = []
        if d["kind"] == "scale":
            f = math.hypot(m.x() - c.x(), m.y() - c.y()) / d["d0"]
            ns = max(0.02, min(10.0, d["s0"] * f))
            it.setScale(ns)
            if not free:   # snap the layer's edges (growing from its centre) to slides / other layers
                r = it.sceneBoundingRect()
                ctr = r.center()
                tg = self.snap_targets([it])
                thr = 8 * self.px()
                best = None
                for edge, cen, ax in ((r.left(), ctr.x(), "v"), (r.right(), ctr.x(), "v"),
                                      (r.top(), ctr.y(), "h"), (r.bottom(), ctr.y(), "h")):
                    for t in tg[ax]:
                        if abs(t - edge) < thr and abs(edge - cen) > 1e-6:
                            k = (t - cen) / (edge - cen)
                            if k > 0 and (best is None or abs(t - edge) < best[0]):
                                best = (abs(t - edge), k, ax, t)
                if best:
                    it.setScale(max(0.02, min(10.0, ns * best[1])))
                    self.snap_lines.append((best[2], best[3]))
        else:
            a = math.degrees(math.atan2(m.y() - c.y(), m.x() - c.x()))
            r = d["r0"] + a - d["a0"]
            if e.modifiers() & Qt.ShiftModifier:
                r = round(r / 15) * 15
            elif not free:   # magnetic snap to 0 / 45 / 90 ... degrees
                nr = round(r / 45) * 45
                if abs(r - nr) < 4:
                    r = nr
                    self.snap_lines.append(("rot", (c.x(), c.y(), nr)))
            it.setRotation((r + 180) % 360 - 180)
        e.accept()
        self.update()
        if self.on_transform:
            self.on_transform()

    def mouseReleaseEvent(self, e):
        gd, self.gdrag = self.gdrag, None
        self.gtimer.stop()
        if gd and gd["active"]:
            super().mouseReleaseEvent(e)
            self.move = None
            g, src, dst = gd["grid"], gd["src"], gd["dst"]
            if g.scene() is self and dst is not None and dst != src:
                g.swap_cells(src, dst)                 # moves into an empty cell, or swaps with a filled one
                g.update()
            for v in self.views():
                v.viewport().setCursor(Qt.ArrowCursor)
            e.accept()
            self.update()
            if self.on_change:
                self.on_change()
            return
        if self.drag is not None:
            self.drag = None
            e.accept()
        else:
            super().mouseReleaseEvent(e)
        self.move = None
        if self.snap_lines:
            self.snap_lines = []
            self.update()
        if self.on_change:
            self.on_change()  # commits only if something actually changed

    def add_item(self, item, center):
        item.setFlags(QGraphicsPixmapItem.ItemIsMovable | QGraphicsPixmapItem.ItemIsSelectable)
        item.setTransformOriginPoint(item.boundingRect().center())
        item.setPos(center - item.boundingRect().center())
        item.setZValue(max([i.zValue() for i in self.items()] + [0]) + 1)
        self.addItem(item)
        self.clearSelection()
        item.setSelected(True)


def setup_gpu(view):
    """Draw the canvas with the graphics card (OpenGL): photos are uploaded once and scaled by the GPU, which keeps
    panning, zooming and dragging smooth with many layers. A guard flag turns it off automatically if the previous
    start with GPU on did not finish cleanly (driver problem). Returns (active, note)."""
    c = cfg()
    if c.value("gpu", "true") != "true":
        return False, "off (Settings)"
    if QApplication.platformName() in ("offscreen", "minimal"):
        return False, "not available here"
    if c.value("gpu_guard", "0") == "1":
        c.setValue("gpu", "false")
        c.setValue("gpu_guard", "0")
        return False, "turned off automatically after a graphics problem"
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
        from PySide6.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        fmt.setSwapInterval(1)
        gl = QOpenGLWidget()
        gl.setFormat(fmt)
        c.setValue("gpu_guard", "1")
        view.setViewport(gl)
        view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        QTimer.singleShot(6000, lambda: cfg().setValue("gpu_guard", "0"))     # still alive after 6 s = driver is fine
        return True, "on"
    except Exception as e:
        c.setValue("gpu_guard", "0")
        return False, f"unavailable ({e})"


class View(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.on_delete = None
        self.on_nudge = None
        self.on_context = None
        self.on_key = None
        self.on_resize = None
        self.panning, self.pan_last = False, None
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.on_resize:
            self.on_resize()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:            # middle button + drag = move the workspace
            self.panning, self.pan_last = True, e.position().toPoint()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.panning:
            pt = e.position().toPoint()
            d = pt - self.pan_last
            self.pan_last = pt
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.panning and e.button() == Qt.MiddleButton:
            self.panning = False
            self.viewport().setCursor(Qt.ArrowCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        if self.on_context:
            self.on_context(e.globalPos(), self.mapToScene(e.pos()))
            e.accept()

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def keyPressEvent(self, e):
        if self.on_key and self.on_key(e.key()):
            return
        fi = self.scene().focusItem()
        typing = isinstance(fi, TextItem) and fi.hasFocus()
        arrows = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if e.key() == Qt.Key_Delete and not typing and self.on_delete:
            self.on_delete()
        elif e.key() in arrows and not typing and self.on_nudge and self.scene().selectedItems():
            st = 10 if e.modifiers() & Qt.ShiftModifier else 1
            self.on_nudge(arrows[e.key()][0] * st, arrows[e.key()][1] * st)
        else:
            super().keyPressEvent(e)


DEFAULT_SOLIDS = ["#000000", "#111111", "#2e2e2e", "#4a4a4a", "#666666", "#808080", "#adadad", "#ffffff",
                  "#ff0000", "#ff7f00", "#ffd700", "#adff10", "#1be83c", "#00ff80", "#00ffff", "#0088ff",
                  "#0000ff", "#8a00ff", "#ff00ff", "#ff0a8c", "#ff2040", "#ffa020", "#ffee50", "#90ff9a"]
DEFAULT_GRADS = [("#bfe9f7", "#1fa0d8"), ("#d7f5a0", "#6cc92e"), ("#fff0cf", "#ffc98a"), ("#ff9a8a", "#ff3b1f"),
                 ("#c8f0a8", "#58b83c"), ("#e6d3b8", "#7a4a1c"), ("#ffd0ff", "#d65cff"), ("#b6f0dc", "#34b88c"),
                 ("#ff6e9c", "#a8c070"), ("#8ad8a0", "#1890c8"), ("#18c880", "#68c840"), ("#2858d8", "#e8b070"),
                 ("#f0a070", "#c83860"), ("#ffa0a0", "#ff3818"), ("#a8c828", "#78b830"), ("#a878ff", "#e060ff"),
                 ("#ff8068", "#fff0f0"), ("#9890d8", "#88a8d8"), ("#c8a020", "#f08030"), ("#20c070", "#e8b0c0"),
                 ("#c8d0e8", "#6890c8"), ("#ffc0a0", "#ee9078"), ("#d8e8f8", "#f0f0d0"), ("#ff3070", "#ff0040")]
TEXTURES = [("Paper", "#e4e4e4", "noise"), ("Crumpled", "#f2f2f2", "crumple"), ("Cardboard", "#b09878", "streak"),
            ("Linen", "#dcdcdc", "weave"), ("Kraft", "#a98a5c", "streak"), ("Charcoal", "#2b2b2b", "weave"),
            ("Brown Paper", "#c99a62", "noise"), ("Peach", "#f0a070", "noise"), ("Wood", "#d8a868", "wood"),
            ("Cotton", "#f6f6f6", "weave"), ("Black", "#141414", "noise"), ("Black Crumple", "#2a2a2a", "crumple"),
            ("Sand", "#c8bba4", "noise"), ("Mocha", "#7a5d50", "noise"), ("Stone", "#b0aaa0", "noise"),
            ("Marble", "#ececec", "marble")]
TEXDEF = {n: (b, k) for n, b, k in TEXTURES}


def make_texture(base, kind, size=128):
    """Procedural seamless-ish tile (our own, generated in code)."""
    rnd, c = random.Random(7), QColor(base)
    img = QImage(size, size, QImage.Format_RGB32)
    for y in range(size):
        bias = rnd.randint(-9, 9) if kind in ("streak", "wood") else 0
        for x in range(size):
            n = rnd.randint(-12, 12) + bias
            if kind == "weave":
                n += 9 if (x // 2 + y // 2) % 2 else -9
            elif kind == "crumple":
                n += int(18 * math.sin(x * 0.11 + math.sin(y * 0.07) * 3) * math.sin(y * 0.09 + x * 0.05))
            elif kind == "marble":
                n += int(22 * math.sin((x + 40 * math.sin(y * 0.03)) * 0.05))
            elif kind == "wood":
                n += int(14 * math.sin(y * 0.35 + math.sin(x * 0.02) * 4))
            img.setPixel(x, y, QColor(*(max(0, min(255, v + n)) for v in (c.red(), c.green(), c.blue()))).rgb())
    return img


def round_icon(brush, circle=True):
    pm = QPixmap(40, 40)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(120, 120, 120), 1))
    p.setBrush(brush)
    p.drawEllipse(2, 2, 36, 36) if circle else p.drawRoundedRect(2, 2, 36, 36, 9, 9)
    p.end()
    return QIcon(pm)


def grad_brush(c1, c2):
    g = QLinearGradient(0, 0, 0, 40)
    g.setColorAt(0, QColor(c1))
    g.setColorAt(1, QColor(c2))
    return QBrush(g)


class BackgroundPanel(QDialog):
    """Solid / Gradient / Texture picker with Brand, Saved and Default swatches."""
    def __init__(self, m):
        super().__init__(m)
        self.m, self.cfg, self.tex_icons = m, QSettings("CarouselStudio", "Editor"), {}
        self.setWindowTitle("Background")
        self.setFixedWidth(470)
        self.resize(470, 560)
        self.tabs = QTabWidget()
        QVBoxLayout(self).addWidget(self.tabs)

    def lst(self, key):
        try:
            return json.loads(self.cfg.value(key, "[]"))
        except (ValueError, TypeError):
            return []

    def push(self, key, val, n=8):
        items = [v for v in self.lst(key) if v != val]
        items.insert(0, val)
        self.cfg.setValue(key, json.dumps(items[:n]))

    def drop(self, key, val):
        self.cfg.setValue(key, json.dumps([v for v in self.lst(key) if v != val]))
        self.refresh()

    def sw(self, icon, tip, fn, rm=None):
        b = QPushButton()
        b.setIcon(icon)
        b.setIconSize(QSize(40, 40))
        b.setFixedSize(46, 46)
        b.setFlat(True)
        b.setToolTip(tip)
        b.clicked.connect(lambda: fn())
        if rm:
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _: rm())
        return b

    def grid(self, widgets, cols=8):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        for i, x in enumerate(widgets):
            g.addWidget(x, i // cols, i % cols)
        return w

    def refresh(self):
        i = max(self.tabs.currentIndex(), 0)
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        for name, fn in (("Solid", self.solid_tab), ("Gradient", self.grad_tab), ("Texture", self.tex_tab)):
            self.tabs.addTab(fn(), name)
        self.tabs.setCurrentIndex(i)

    def page(self, button_text, button_fn):
        w = QWidget()
        l = QVBoxLayout(w)
        if button_text:
            b = QPushButton(button_text)
            b.clicked.connect(lambda: button_fn())
            l.addWidget(b)
        return w, l

    # --- solid
    def solid_tab(self):
        w, l = self.page("Custom Color...", self.custom_color)
        l.addWidget(QLabel("Brand Colors   (+ adds one, right-click removes)"))
        brand = [self.sw(round_icon(QColor(c)), c, lambda c=c: self.solid(c), lambda c=c: self.drop("brand", c))
                 for c in self.lst("brand")]
        add = QPushButton("+")
        add.setFixedSize(40, 40)
        add.clicked.connect(self.add_brand)
        l.addWidget(self.grid(brand + [add]))
        l.addWidget(QLabel("Saved"))
        l.addWidget(self.grid([self.sw(round_icon(QColor(c)), c, lambda c=c: self.solid(c)) for c in self.lst("saved_colors")]))
        l.addWidget(QLabel("Defaults"))
        l.addWidget(self.grid([self.sw(round_icon(QColor(c)), c, lambda c=c: self.solid(c)) for c in DEFAULT_SOLIDS]))
        l.addStretch()
        return w

    def solid(self, c):
        self.m.set_bg_solid(c)
        self.push("saved_colors", c)
        self.refresh()

    def custom_color(self):
        c = QColorDialog.getColor(self.m.scene.bg, self, "Background color")
        if c.isValid():
            self.solid(c.name())

    def add_brand(self):
        c = QColorDialog.getColor(QColor("white"), self, "Brand color")
        if c.isValid():
            self.push("brand", c.name(), 12)
            self.refresh()

    # --- gradient
    def grad_tab(self):
        w, l = self.page("Custom Gradient...", self.custom_grad)
        icon = lambda g: round_icon(grad_brush(g[0], g[1]))
        l.addWidget(QLabel("Saved"))
        l.addWidget(self.grid([self.sw(icon(g), "saved", lambda g=g: self.grad(*g)) for g in self.lst("saved_grads")]))
        l.addWidget(QLabel("Defaults"))
        l.addWidget(self.grid([self.sw(icon(g), "gradient", lambda g=g: self.grad(g[0], g[1], 90)) for g in DEFAULT_GRADS]))
        l.addStretch()
        return w

    def grad(self, c1, c2, ang=90):
        self.m.set_bg_gradient(c1, c2, ang)
        self.push("saved_grads", [c1, c2, ang])
        self.refresh()

    def custom_grad(self):
        sc = self.m.scene
        c1 = QColorDialog.getColor(sc.bg, self, "Gradient color 1")
        c2 = QColorDialog.getColor(sc.bg2, self, "Gradient color 2") if c1.isValid() else c1
        if not (c1.isValid() and c2.isValid()):
            return
        ang, ok = QInputDialog.getInt(self, "Gradient", "Angle (0 = left to right, 90 = top to bottom):", sc.bg_angle, 0, 359)
        if ok:
            self.grad(c1.name(), c2.name(), ang)

    # --- texture
    def tex_tab(self):
        w, l = self.page("From Image File...", self.m.bg_texture_from_file)
        l.addWidget(QLabel("Textures"))
        sws = []
        for name, base, kind in TEXTURES:
            if name not in self.tex_icons:
                img = make_texture(base, kind).scaled(40, 40, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self.tex_icons[name] = round_icon(QBrush(QPixmap.fromImage(img)), circle=False)
            sws.append(self.sw(self.tex_icons[name], name, lambda n=name: self.m.set_bg_texture(n)))
        l.addWidget(self.grid(sws, 5))
        l.addStretch()
        return w


# ---------------------------------------------------------------- film emulations (procedural approximations)
# Each film is a small parameter set: black lift, highlight ceiling, contrast, gamma, saturation, warm/cool + tint
# shift, shadow / highlight colour casts, grain, vignette, optional B&W channel weights, optional channel mix.
FILM_BASE = {
    # name: dict(...)  (defaults filled in by film_params)
    "Agfa Optima": dict(con=.95, sat=.95, lift=.03, temp=.02, hl=(.01, .005, -.01)),
    "Agfa Vista": dict(con=1.1, sat=1.25, temp=.03, sh=(-.01, .015, .0)),
    "Fuji Natura": dict(con=.95, sat=1.0, lift=.03, temp=-.02, tint=.015, sh=(-.01, .015, .02)),
    "Fuji Pro 160ns": dict(con=.92, sat=.9, lift=.035, temp=-.01, tint=.01, sh=(-.01, .015, .02), hl=(.01, .0, -.005)),
    "Fuji Pro 400h": dict(con=.94, sat=.95, lift=.04, temp=-.015, tint=.02, sh=(-.015, .02, .025), grain=.05),
    "Fuji Superia 200": dict(con=1.1, sat=1.15, temp=-.01, tint=.015, sh=(-.015, .02, .02), hl=(.015, -.005, .005)),
    "Fuji Superia 400": dict(con=1.1, sat=1.15, temp=-.01, tint=.02, sh=(-.015, .02, .02), grain=.08),
    "Fuji Superia 800": dict(con=1.12, sat=1.15, temp=-.01, tint=.02, sh=(-.015, .02, .02), grain=.14),
    "Kodak Ektar": dict(con=1.15, sat=1.4, temp=.015, gam=1.02),
    "Kodak Gold 200": dict(con=1.08, sat=1.15, temp=.06, hl=(.02, .01, -.02), lift=.015),
    "Kodak Gold 800": dict(con=1.06, sat=1.12, temp=.06, hl=(.02, .01, -.02), lift=.02, grain=.14),
    "Kodak Portra 160": dict(con=.95, sat=.9, lift=.02, temp=.02, gam=1.04, hl=(.01, .005, -.005)),
    "Kodak Portra 400": dict(con=1.0, sat=1.0, lift=.03, temp=.03, gam=1.03, grain=.05),
    "Kodak Portra 800": dict(con=1.0, sat=1.0, lift=.03, temp=.035, gam=1.03, grain=.12),
    "Kodak Ultramax 400": dict(con=1.12, sat=1.2, temp=.04, hl=(.015, .005, -.015), grain=.09),
    "Rollei Digibase CN 200": dict(con=1.04, sat=1.05, temp=-.015, tint=.005),
    "Agfa Precisa": dict(con=1.2, sat=1.25, lift=-.01),
    "Agfa RSX": dict(con=1.18, sat=1.3, temp=.03),
    "Agfa Ultra": dict(con=1.2, sat=1.5, temp=.01, tint=-.015),
    "Fuji Astia": dict(con=1.08, sat=1.05, temp=.005),
    "Fuji Fortia": dict(con=1.2, sat=1.5, temp=.01, tint=-.01),
    "Fuji Provia": dict(con=1.15, sat=1.2, temp=-.01),
    "Fuji Sensia": dict(con=1.1, sat=1.15, temp=.005),
    "Fuji Velvia": dict(con=1.25, sat=1.55, temp=.005, gam=1.03),
    "Kodak E100G": dict(con=1.1, sat=1.15, temp=-.02, sh=(-.005, 0, .015)),
    "Kodak E200": dict(con=1.12, sat=1.2, temp=.025, grain=.05),
    "Kodak Elite Chrome": dict(con=1.12, sat=1.25, temp=.02),
    "Fuji FP 100C": dict(con=1.05, sat=1.05, lift=.05, temp=.01, sh=(-.02, .015, .025), hl=(.02, .01, -.015), vig=.12),
    "Fuji Instax Mini": dict(con=1.0, sat=1.2, lift=.04, tint=.015, temp=.01, vig=.25, hl=(.01, .015, -.01)),
    "Polaroid 600": dict(con=.98, sat=.92, lift=.06, temp=.02, sh=(-.015, .015, .03), vig=.3, hl=(.02, .01, -.02)),
    "Polaroid 669": dict(con=1.05, sat=.95, lift=.05, tint=.03, temp=.015, sh=(-.02, .02, .02), vig=.2),
    "Polaroid 690": dict(con=.95, sat=.95, lift=.06, temp=.04, vig=.25, hl=(.02, .005, -.02)),
    "Autochrome": dict(con=.9, sat=.7, lift=.09, tint=.02, temp=.015, sh=(.02, -.01, .02), grain=.12, gam=1.05),
    "Autochrome 50s": dict(con=.95, sat=.8, lift=.07, tint=.015, temp=.03, grain=.1),
    "Agfacolor 40s": dict(con=.95, sat=.8, lift=.07, temp=.05, tint=-.01, vig=.15, grain=.08),
    "Agfacolor 50s": dict(con=1.0, sat=.9, lift=.05, temp=.03, sh=(-.01, .01, .02), grain=.07),
    "Agfacolor 60s": dict(con=1.0, sat=.95, lift=.04, temp=.025, tint=.01, grain=.07),
    "Agfacolor XP 160": dict(con=1.05, sat=1.0, lift=.03, temp=.02, sh=(-.01, .01, .02), grain=.06),
    "Kodachrome 70s": dict(con=1.18, sat=1.2, temp=.04, gam=1.02, grain=.05, hl=(.01, .0, -.01)),
    "Kodachrome 1958": dict(con=1.1, sat=1.0, lift=.04, temp=.045, grain=.08, vig=.1),
    "Kodachrome": dict(con=1.2, sat=1.2, temp=.035, gam=1.02, sh=(.0, -.005, .015), grain=.05),
    "Technicolor 2": dict(con=1.1, sat=1.2, lift=.03, mix="tech2", grain=.05),
    "Technicolor 4": dict(con=1.1, sat=1.25, lift=.02, temp=.01, mix="tech4", grain=.04),
    "Agfa Scala 200": dict(bw=(.30, .59, .11), con=1.25, lift=-.01, tone=(-.005, 0, .01), grain=.05),
    "Ilford Delta 100": dict(bw=(.30, .59, .11), con=1.1, grain=.03),
    "Ilford Delta 400": dict(bw=(.30, .59, .11), con=1.1, grain=.09),
    "Ilford Delta 800": dict(bw=(.30, .59, .11), con=1.12, grain=.15),
    "Ilford Delta 3200": dict(bw=(.30, .59, .11), con=1.15, grain=.28, lift=.04),
    "Ilford FP4": dict(bw=(.28, .60, .12), con=1.05, grain=.04),
    "Ilford HP5": dict(bw=(.30, .56, .14), con=1.1, grain=.12),
    "Kodak Tri-X 200": dict(bw=(.33, .53, .14), con=1.2, grain=.1, vig=.1),
}
FILM_LIST = [
    ("Negative Films", [
        ("Agfa Optima", "Agfa Optima 100", [""]),
        ("Agfa Optima", "Agfa Optima 200", ["", "v2", "v3", "v3 faded", "v4", "faded", "HC", "muted", "warm"]),
        ("Agfa Vista", "Agfa Vista 100", [""]),
        ("Fuji Natura", "Fuji Natura 1600", ["", "II"]),
        ("Fuji Pro 160ns", "Fuji Pro 160ns", ["", "v2", "v2 HC", "v3", "v4", "faded"]),
        ("Fuji Pro 400h", "Fuji Pro 400h", ["", "v2", "faded"]),
        ("Fuji Superia 200", "Fuji Superia 200", ["", "v2", "v2 normalised", "v2 normalised +", "v2 normalised HC", "v2 warm", "v3", "v4", "v5", "v6", "v6 HC"]),
        ("Fuji Superia 400", "Fuji Superia 400", ["", "v2", "faded"]),
        ("Fuji Superia 800", "Fuji Superia 800", [""]),
        ("Kodak Ektar", "Kodak Ektar 100", ["", "v2", "v3", "v4", "cool fade", "warm fade"]),
        ("Kodak Gold 200", "Kodak Gold 200", ["", "v2", "v3", "v4", "v5", "v6"]),
        ("Kodak Gold 800", "Kodak Gold 800", ["", "faded", "soft red cast"]),
        ("Kodak Portra 160", "Kodak Portra 160", ["", "II", "III", "IV", "v2", "v2 warm fade", "v3", "v3 faded", "v4", "v5", "v5 HC"]),
        ("Kodak Portra 400", "Kodak Portra 400", ["", "v2", "normalised", "warm"]),
        ("Kodak Portra 800", "Kodak Portra 800", ["", "v2", "v3", "v4"]),
        ("Kodak Ultramax 400", "Kodak Ultramax 400", ["", "v2", "v3"]),
        ("Rollei Digibase CN 200", "Rollei Digibase CN 200", ["", "v2", "warm"]),
    ]),
    ("Slide Films", [
        ("Agfa Precisa", "Agfa Precisa 100", ["", "II"]),
        ("Agfa RSX", "Agfa RSX II", ["", "v2", "v3"]),
        ("Agfa Ultra", "Agfa Ultra 100", ["", "v2", "warm"]),
        ("Fuji Astia", "Fuji Astia 100F", ["", "v2", "v3", "v4", "v4 warm", "v5"]),
        ("Fuji Fortia", "Fuji Fortia SP", ["", "v2"]),
        ("Fuji Provia", "Fuji Provia 100F", [""]),
        ("Fuji Sensia", "Fuji Sensia 200", [""]),
        ("Fuji Velvia", "Fuji Velvia 100F", [""]),
        ("Kodak E100G", "Kodak E 100G", ["", "v2"]),
        ("Kodak E200", "Kodak E 200", ["", "v2"]),
        ("Kodak Elite Chrome", "Kodak Elite Chrome", [""]),
    ]),
    ("Instant Films", [
        ("Fuji FP 100C", "Fuji FP 100C", ["", "v2", "v3", "v4", "v5", "v5 HC", "v6", "v6 expired", "v6 faded"]),
        ("Fuji Instax Mini", "Fuji Instax Mini", ["", "normalised"]),
        ("Polaroid 600", "Polaroid 600", ["", "v2", "v3", "expired"]),
        ("Polaroid 669", "Polaroid 669", ["", "terribly expired"]),
        ("Polaroid 690", "Polaroid 690", ["", "v2", "v2 expired", "v3 expired", "expired", "muted"]),
    ]),
    ("Vintage Films", [
        ("Autochrome", "Autochrome", ["", "v2", "v3", "v4", "v5"]),
        ("Autochrome 50s", "Autochrome 50s", ["", "plus"]),
        ("Agfacolor 40s", "Agfacolor 40s", ["", "aged", "warm"]),
        ("Agfacolor 50s", "Agfacolor 50s", ["", "HC", "muted"]),
        ("Agfacolor 60s", "Agfacolor 60s", ["", "faded"]),
        ("Agfacolor XP 160", "Agfacolor XP 160", ["", "v2", "vibrant", "normalised"]),
        ("Kodachrome 70s", "Kodachrome 70s", ["", "v2", "v3"]),
        ("Kodachrome 1958", "Kodachrome 1958", [""]),
        ("Kodachrome", "Kodachrome Generic", ["", "v2", "v3", "v4", "v4 muted", "v4 muted faded", "v4 normalised", "v5", "v6", "faded"]),
        ("Kodachrome", "Kodachrome", ["HC", "v2 HC"]),
        ("Technicolor 2", "Technicolor 2", ["", "v2", "HC"]),
        ("Technicolor 4", "Technicolor 4", ["faded"]),
    ]),
    ("B&W Films", [
        ("Agfa Scala 200", "Agfa Scala 200", ["", "+", "++", "faded", "faded HC", "faded plus"]),
        ("Ilford Delta 100", "Ilford Delta 100", ["", "faded", "HC"]),
        ("Ilford Delta 400", "Ilford Delta 400", ["", "faded", "HC"]),
        ("Ilford Delta 800", "Ilford Delta 800", ["", "faded", "HC"]),
        ("Ilford Delta 3200", "Ilford Delta 3200", [""]),
        ("Ilford FP4", "Ilford FP4", ["", "faded"]),
        ("Ilford HP5", "Ilford HP5", ["", "faded"]),
        ("Kodak Tri-X 200", "Kodak Tri-X 200", ["", "HC"]),
    ]),
]
FILM_DEFAULT = dict(lift=0.0, hi=1.0, con=1.0, gam=1.0, sat=1.0, temp=0.0, tint=0.0, sh=(0, 0, 0), hl=(0, 0, 0),
                    grain=0.0, vig=0.0, bw=None, tone=(0, 0, 0), mix=None)
AERO_PERMS = [(0, 1, 2), (1, 0, 2), (1, 2, 0), (2, 1, 0), (2, 0, 1), (0, 2, 1)]       # which input feeds R, G, B
AERO_TONES = [dict(), dict(con=1.2, sat=1.25), dict(lift=.06, hi=.95, sat=.85, temp=.03)]
FILM_PARAMS = {}
FILM_NAMES = {}


def _film_variant(P, label, name):
    P = dict(P)
    h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    jit = lambda k, amt: ((h >> k) % 2001 - 1000) / 1000.0 * amt
    toks = label.split()
    for i, t in enumerate(toks):
        if t in ("faded", "fade"):
            P["lift"] += .05; P["hi"] -= .05; P["con"] *= .9; P["sat"] *= .88
        elif t == "HC":
            P["con"] *= 1.18; P["sat"] *= 1.12; P["lift"] *= .5
        elif t == "muted":
            P["sat"] *= .8; P["con"] *= .95
        elif t == "warm":
            P["temp"] += .05; P["tint"] += .008
        elif t == "cool":
            P["temp"] -= .05
        elif t == "normalised":
            P["con"] = 1 + (P["con"] - 1) * .5; P["sat"] = 1 + (P["sat"] - 1) * .6; P["temp"] *= .4; P["tint"] *= .4
            P["sh"] = tuple(c * .4 for c in P["sh"]); P["hl"] = tuple(c * .4 for c in P["hl"])
        elif t in ("+", "plus"):
            P["con"] *= 1.1; P["sat"] *= 1.05
        elif t == "++":
            P["con"] *= 1.2; P["sat"] *= 1.1
        elif t == "expired":
            k = 2 if "terribly" in toks else 1
            P["lift"] += .07 * k; P["sat"] *= .82 ** k; P["tint"] += .02 * k; P["temp"] += .03 * k
            P["grain"] += .08 * k; P["vig"] += .12 * k; P["hi"] -= .03 * k
        elif t == "vibrant":
            P["sat"] *= 1.25
        elif t == "aged":
            P["lift"] += .05; P["sat"] *= .85; P["temp"] += .035; P["vig"] += .15; P["grain"] += .05
        elif t == "soft":
            P["con"] *= .95
        elif t == "red":
            P["sh"] = (P["sh"][0] + .02, P["sh"][1], P["sh"][2]); P["temp"] += .01
        elif t in ("v2", "v3", "v4", "v5", "v6", "II", "III", "IV"):
            P["temp"] += jit(3, .014); P["tint"] += jit(7, .01); P["con"] *= 1 + jit(11, .05)
            P["sat"] *= 1 + jit(15, .06); P["lift"] += jit(19, .008)
    return P


def _build_films():
    groups = []
    for grp, rows in FILM_LIST:
        names = []
        for base, prefix, labels in rows:
            for lab in labels:
                name = f"{prefix} {lab}".strip()
                P = dict(FILM_DEFAULT)
                P.update(FILM_BASE[base])
                FILM_PARAMS[name] = _film_variant(P, lab, name)
                names.append(name)
        groups.append((grp, names))
    ir = []
    for i in range(18):
        name = f"Aerochrome {i + 1:02d}"
        P = dict(FILM_DEFAULT)
        P.update(AERO_TONES[i // 6])
        P["mix"] = ("ir", AERO_PERMS[i % 6])
        FILM_PARAMS[name] = P
        ir.append(name)
    groups.append(("Infrared Films", ir))
    return groups


FILM_GROUPS = _build_films()


def apply_look(x, P, size):
    """Render a film look (see FILM_PARAMS) on float RGB 0..1."""
    h, w = x.shape[:2]
    mix = P.get("mix")
    if mix == "tech2":
        x = x @ np.array([[1.05, -.05, 0], [.1, .65, .25], [.05, .55, .4]], np.float32).T
    elif mix == "tech4":
        x = x @ np.array([[1.05, -.03, -.02], [0, 1.0, 0], [-.02, -.03, 1.08]], np.float32).T
    elif mix:                                                     # infrared false colour: foliage glows
        ir = np.clip(.25 * x[..., 0] + 1.1 * x[..., 1] - .45 * x[..., 2], 0, 1)
        src = np.stack([ir, x[..., 0], x[..., 1]], -1)
        x = src[..., list(mix[1])]
    if P["bw"]:
        g = x @ np.array(P["bw"], np.float32)
        x = np.repeat(g[..., None], 3, 2)
    x = np.clip(x, 0, 1)                      # from here on x is our own array, so it can be changed in place
    x -= .5
    x *= P["con"]
    x += .5
    if P["gam"] != 1.0:
        x = np.clip(x, 0, 1)
        x = x ** (1.0 / P["gam"])
    if not P["bw"]:
        L = lumv(x)
        x -= L
        x *= P["sat"]
        x += L
        x += np.array([P["temp"], P["tint"], -P["temp"]], np.float32)
    L = np.clip(lumv(x), 0, 1)
    iL = 1 - L
    tmp = np.multiply(iL * iL, np.array(P["sh"], np.float32))
    x += tmp
    np.multiply(L * L, np.array(P["hl"], np.float32), out=tmp)
    x += tmp
    if P["bw"]:
        x += np.array(P["tone"], np.float32)
    x = np.clip(x, 0, 1)
    x *= (P["hi"] - P["lift"])
    x += P["lift"]
    if P["vig"] > 0:
        x *= vignette_mask(h, w, P["vig"])
    if P["grain"] > 0:
        k = 2 if size > 1.2 else 1
        n = grain_cells(h, w, k)
        Lm = np.clip(lumv(x), 0, 1)
        x += n * (P["grain"] * .22 * (1 - np.abs(Lm - .5) * 1.2))
    return x


_VIG, _CELLS = {}, {}


def vignette_mask(h, w, vig):
    """Darkening towards the corners (cached: it is the same for every frame of a video)."""
    key = (h, w, vig)
    m = _VIG.get(key)
    if m is None:
        _VIG.clear()
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
        m = (1 - vig * np.clip(r2 / 2, 0, 1))[..., None].astype(np.float32)
        _VIG[key] = m
    return m


def grain_cells(h, w, k):
    """Film grain pattern (cached, same every frame as before)."""
    key = (h, w, k)
    n = _CELLS.get(key)
    if n is None:
        _CELLS.clear()
        n = np.random.default_rng(3).standard_normal((-(-h // k), -(-w // k), 1)).astype(np.float32)
        if k > 1:
            n = block_up(n, k, h, w)
        _CELLS[key] = n
    return n


FILTER_GROUPS = [
    ("Color & Tone", ["Sepia", "Monochrome", "Black & White", "Duotone", "High Contrast", "Saturation Boost",
                      "Vibrance Boost", "Cross Process"]),
    ("Vintage & Film", ["Film Grain", "Light Leaks", "Vignette", "Polaroid", "Chromatic Aberration", "Daguerreotype"]),
    ("Blur & Focus", ["Bokeh", "Tilt-Shift", "Motion Blur", "Radial Blur (Zoom)", "Radial Blur (Spin)", "Glow (Orton)"]),
    ("Artistic", ["Glitch / VHS", "Halftone", "Solarize", "Pixelate", "Posterize", "Infrared"]),
    ("Classic", ["Noir", "Warm", "Cool", "Fade", "Vivid"]),
] + FILM_GROUPS
FILTERS = ["None"] + [f for _, fs in FILTER_GROUPS for f in fs] + ["Mono"]      # "Mono" = old projects
# (key, label, min, max, default)
ADJ_SLIDERS = [("strength", "Filter strength", 0, 100, 100), ("angle", "Effect direction (deg)", 0, 180, 0),
               ("exposure", "Exposure", -100, 100, 0), ("brightness", "Brightness", -100, 100, 0),
               ("contrast", "Contrast", -100, 100, 0), ("highlights", "Highlights", -100, 100, 0),
               ("shadows", "Shadows", -100, 100, 0), ("temperature", "Temperature", -100, 100, 0),
               ("tint", "Tint", -100, 100, 0), ("vibrance", "Vibrance", -100, 100, 0),
               ("saturation", "Saturation", -100, 100, 0), ("blur", "Blur", 0, 100, 0),
               ("sharpen", "Sharpen", 0, 100, 0), ("grain", "Grain", 0, 100, 0)]
ADJ_DEFAULT = {k: d for k, _, _, _, d in ADJ_SLIDERS}
DUO_DEFAULT = ("#2b1055", "#ffb36b")


def qimage_to_np(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()]
    a = a.astype(np.float32) / 255
    return a[..., :3].copy(), a[..., 3:].copy()


def np_to_pixmap(rgb, alpha):
    out = np.ascontiguousarray((np.dstack([np.clip(rgb, 0, 1), alpha]) * 255).astype(np.uint8))
    h, w = out.shape[:2]
    return QPixmap.fromImage(QImage(out.data, w, h, w * 4, QImage.Format_RGBA8888).copy())


def box_blur(x, r):
    if r < 1:
        return x
    k = 2 * r + 1
    for ax in (0, 1):
        for _ in range(2):
            pad = [(0, 0)] * 3
            pad[ax] = (r + 1, r)
            c = np.cumsum(np.pad(x, pad, mode="edge"), axis=ax, dtype=np.float32)
            n = x.shape[ax]
            x = (np.take(c, np.arange(k, n + k), axis=ax) - np.take(c, np.arange(0, n), axis=ax)) / k
    return x


def chroma(x):
    """max(R,G,B) - min(R,G,B) per pixel as (h, w, 1): about 30x faster than x.max(-1) - x.min(-1) on big frames."""
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    return (np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b))[..., None]


def lumv(x):
    return (x @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]


def smooth01(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def unit_coords(h, w):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return xx / max(w - 1, 1), yy / max(h - 1, 1)


def axis_blur(x, r, axis):
    if r < 1:
        return x
    k = 2 * r + 1
    pad = [(0, 0)] * 3
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(x, pad, mode="edge"), axis=axis, dtype=np.float32)
    n = x.shape[axis]
    return (np.take(c, np.arange(k, n + k), axis=axis) - np.take(c, np.arange(0, n), axis=axis)) / k


def block_down(x, f):
    h, w = x.shape[:2]
    H, W = -(-h // f) * f, -(-w // f) * f
    xp = np.pad(x, ((0, H - h), (0, W - w), (0, 0)), mode="edge")
    return xp.reshape(H // f, f, W // f, f, -1).mean(axis=(1, 3))


def block_up(x, f, h, w):
    return np.repeat(np.repeat(x, f, 0), f, 1)[:h, :w]


def disc_conv(x, r):
    """Blur with a round (disc) kernel via FFT - gives bokeh its circular highlights."""
    r = max(1, int(r))
    h, w = x.shape[:2]
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    k = ((xx * xx + yy * yy) <= r * r).astype(np.float32)
    k /= k.sum()
    H, W = h + 2 * r, w + 2 * r
    K = np.fft.rfft2(k, (H, W))
    out = np.empty_like(x)
    for c in range(x.shape[2]):
        out[..., c] = np.fft.irfft2(np.fft.rfft2(x[..., c], (H, W)) * K, (H, W))[r:r + h, r:r + w]
    return out


def motion_blur(x, ang, length):
    length = max(1, int(length))
    h, w = x.shape[:2]
    pad = length + 1
    xp = np.pad(x, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    n = min(2 * length + 1, 17)
    acc = np.zeros_like(x)
    for t in np.linspace(-length, length, n):
        dx, dy = int(round(t * ca)), int(round(t * sa))
        acc += xp[pad + dy:pad + dy + h, pad + dx:pad + dx + w]
    return acc / n


def radial_blur(x, amount, spin):
    h, w = x.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    dx, dy = xx - cx, yy - cy
    n, acc = 9, np.zeros_like(x)
    for k in range(n):
        t = k / (n - 1) - 0.5
        if spin:
            a = math.radians(amount * 14) * t
            sx, sy = cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)
        else:
            sc = 1 + amount * 0.22 * t
            sx, sy = cx + dx / sc, cy + dy / sc
        acc += x[np.clip(np.rint(sy).astype(int), 0, h - 1), np.clip(np.rint(sx).astype(int), 0, w - 1)]
    r = np.sqrt(dx * dx + dy * dy) / (0.5 * math.hypot(w, h))
    wgt = smooth01((r - 0.12) / 0.55)[..., None]                # centre stays sharp
    return x * (1 - wgt) + (acc / n) * wgt


def hex_rgb(hx):
    c = QColor(hx)
    return np.array([c.redF(), c.greenF(), c.blueF()], np.float32)


def apply_filter(x, f, a):
    h, w = x.shape[:2]
    size = max(h, w) / 1000.0
    L = lumv(x)
    rng = np.random.default_rng(3)
    if f in FILM_PARAMS:
        return apply_look(x, FILM_PARAMS[f], size)
    if f in ("Mono", "Monochrome"):
        return np.repeat(L, 3, 2)
    if f == "Black & White":
        return np.repeat(np.clip((L - 0.5) * 1.25 + 0.5, 0, 1), 3, 2)
    if f == "Noir":
        return (np.repeat(L, 3, 2) - 0.5) * 1.35 + 0.46
    if f == "Sepia":
        m = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]], np.float32)
        return x @ m.T
    if f == "Duotone":
        lo, hi = hex_rgb(a.get("duo_a", DUO_DEFAULT[0])), hex_rgb(a.get("duo_b", DUO_DEFAULT[1]))
        return lo + (hi - lo) * np.clip(L, 0, 1)
    if f == "High Contrast":
        y = (x - 0.5) * 1.75 + 0.5
        return lumv(y) + (y - lumv(y)) * 1.15
    if f == "Saturation Boost":
        return L + (x - L) * 1.65
    if f == "Vibrance Boost":
        sat = chroma(x)
        return L + (x - L) * (1 + 1.1 * (1 - sat))
    if f == "Cross Process":
        r = smooth01(x[..., 0] * 1.05 - 0.02) * 0.6 + x[..., 0] * 0.4 + 0.03
        g = np.clip((x[..., 1] - 0.5) * 1.15 + 0.52, 0, 1)
        b = x[..., 2] * 0.62 + 0.18 - 0.05 * x[..., 0]
        y = np.stack([r, g, b], -1)
        return (y - 0.5) * 1.15 + 0.5
    if f == "Warm":
        return x + np.array([0.06, 0, -0.06], np.float32)
    if f == "Cool":
        return x + np.array([-0.06, 0, 0.06], np.float32)
    if f == "Fade":
        return x * 0.85 + 0.1
    if f == "Vivid":
        return (L + (x - L) * 1.3 - 0.5) * 1.12 + 0.5
    if f == "Film Grain":
        n = rng.normal(0, 0.055, (h, w, 1)).astype(np.float32) * (0.55 + 0.9 * (1 - np.abs(L - 0.5) * 1.4))
        return x * 0.94 + 0.035 + n + np.array([0.012, 0.004, -0.012], np.float32)
    if f == "Light Leaks":
        xx, yy = unit_coords(h, w)
        e = lambda v: np.exp(-v * v)[..., None]
        leak = (e(xx / 0.32) * np.array([1.0, 0.42, 0.12], np.float32) * 0.95
                + e((xx + yy * 0.55 - 1.2) / 0.13) * np.array([1.0, 0.18, 0.42], np.float32) * 0.8
                + e((1 - yy) / 0.25) * e((xx - 0.7) / 0.5) * np.array([1.0, 0.8, 0.2], np.float32) * 0.6)
        return 1 - (1 - x * 0.97) * (1 - np.clip(leak, 0, 1) * 0.85)
    if f == "Vignette":
        xx, yy = unit_coords(h, w)
        r = np.sqrt(((xx - 0.5) * 1.25) ** 2 + ((yy - 0.5) * 1.25) ** 2)
        return x * (1 - smooth01((r - 0.28) / 0.6)[..., None] * 0.85)
    if f == "Polaroid":
        y = x * 0.86 + 0.09
        y = y + np.array([0.035, 0.0, -0.045], np.float32) * L + np.array([0.0, 0.02, 0.045], np.float32) * (1 - L)
        y = lumv(y) + (y - lumv(y)) * 0.9
        m = int(min(h, w) * 0.05)
        bt = int(min(h, w) * 0.17)
        cream = np.array([0.96, 0.95, 0.91], np.float32)
        y[:m], y[-bt:], y[:, :m], y[:, -m:] = cream, cream, cream, cream
        return y
    if f == "Chromatic Aberration":
        d = max(1, int(max(h, w) * 0.006))
        xp = np.pad(x, ((0, 0), (d, d), (0, 0)), mode="edge")
        y = x.copy()
        y[..., 0] = xp[:, 2 * d:2 * d + w, 0]
        y[..., 2] = xp[:, 0:w, 2]
        return y
    if f == "Daguerreotype":
        xx, yy = unit_coords(h, w)
        g = np.clip((L - 0.5) * 1.3 + 0.47, 0, 1)
        y = g * np.array([0.93, 0.92, 0.88], np.float32) + (1 - g) * np.array([0.05, 0.06, 0.07], np.float32) * 0.5
        r = np.sqrt(((xx - 0.5) * 1.3) ** 2 + ((yy - 0.5) * 1.3) ** 2)
        y = y * (1 - smooth01((r - 0.3) / 0.55)[..., None] * 0.7)
        return y + rng.normal(0, 0.025, (h, w, 1)).astype(np.float32)
    if f == "Bokeh":
        R = max(2, int(15 * size))
        blur = box_blur(x, R)
        hl = x * smooth01((L - 0.68) / 0.3) ** 1.5
        k = max(1, int(math.ceil(max(h, w) / 480)))
        spots = block_up(disc_conv(block_down(hl, k), max(2, int(R * 1.7 / k))), k, h, w) * 3.2
        xx, yy = unit_coords(h, w)
        focus = 1 - smooth01((np.sqrt(((xx - 0.5) / 0.62) ** 2 + ((yy - 0.5) / 0.62) ** 2) - 0.45) / 0.5)[..., None]
        return x * focus + (blur + spots * 0.7) * (1 - focus)
    if f == "Tilt-Shift":
        xx, yy = unit_coords(h, w)
        wgt = smooth01((np.abs(yy - 0.5) - 0.12) / 0.3)[..., None]
        b1, b2 = box_blur(x, max(1, int(7 * size))), box_blur(x, max(2, int(16 * size)))
        y = x + (b1 - x) * np.clip(wgt * 2, 0, 1) + (b2 - b1) * np.clip(wgt * 2 - 1, 0, 1)
        return (lumv(y) + (y - lumv(y)) * 1.35 - 0.5) * 1.1 + 0.5
    if f == "Motion Blur":
        return motion_blur(x, a.get("angle", 0), 14 * size)
    if f == "Radial Blur (Zoom)":
        return radial_blur(x, 1.0, False)
    if f == "Radial Blur (Spin)":
        return radial_blur(x, 1.0, True)
    if f == "Glow (Orton)":
        bl = np.clip(box_blur(x, max(2, int(18 * size))) * 1.3, 0, 1)
        return (1 - (1 - x) * (1 - bl * 0.6)) * 0.95 + 0.02
    if f == "Glitch / VHS":
        d = max(2, int(w * 0.008))
        y = x.copy()
        y[..., 0] = np.roll(x[..., 0], d, axis=1)
        y[..., 2] = np.roll(x[..., 2], -d, axis=1)
        for _ in range(9):
            y0 = int(rng.integers(0, h))
            bh = int(rng.integers(max(2, h // 80), max(3, h // 14)))
            y[y0:y0 + bh] = np.roll(y[y0:y0 + bh], int(rng.integers(-max(2, w // 12), max(3, w // 12))), axis=1)
        y = axis_blur(y, max(1, int(1.5 * size)), 1)
        y[::3] *= 0.86
        gray = lumv(y)
        return gray + (y - gray) * 1.25 + np.array([0.02, -0.01, 0.03], np.float32)
    if f == "Halftone":
        c = max(4, int(9 * size))
        cells = block_down(x, c)
        ch, cw = cells.shape[:2]
        col = block_up(cells, c, h, w)
        rad = (np.sqrt(1 - np.clip(lumv(cells)[..., 0], 0, 1)) * c * 0.62)
        radf = block_up(rad[..., None], c, h, w)[..., 0]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((xx % c) - c / 2 + 0.5) ** 2 + ((yy % c) - c / 2 + 0.5) ** 2)
        m = np.clip(radf - d + 0.5, 0, 1)[..., None]
        paper = np.array([0.97, 0.96, 0.92], np.float32)
        return paper * (1 - m) + np.clip(col * 1.05, 0, 1) * m
    if f == "Solarize":
        tent = 2 * np.minimum(x, 1 - x)
        return x * 0.15 + tent * 0.85
    if f == "Pixelate":
        k = max(4, int(12 * size))
        return block_up(block_down(x, k), k, h, w)
    if f == "Posterize":
        return np.floor(np.clip(x, 0, 0.999) * 4) / 3
    if f == "Infrared":
        g = np.clip(0.18 * x[..., 0] + 1.15 * x[..., 1] - 0.55 * x[..., 2] + 0.05, 0, 1)[..., None]
        g = np.clip((g - 0.5) * 1.25 + 0.5, 0, 1)
        glow = np.clip(box_blur(np.repeat(g, 3, 2), max(2, int(10 * size))), 0, 1)
        return np.clip(np.repeat(g, 3, 2) * 0.75 + glow * 0.35, 0, 1) * np.array([1.0, 0.99, 0.97], np.float32)
    return x


_GRAIN = {}


def grain_noise(shape):
    """Same film grain for every frame / call of one size (it was recomputed every time)."""
    key = tuple(shape)
    n = _GRAIN.get(key)
    if n is None:
        _GRAIN.clear()
        n = np.random.default_rng(1).standard_normal(key + (1,)).astype(np.float32)
        _GRAIN[key] = n
    return n


def adjust_rgb(x, a):
    g = lambda k: a.get(k, 0) / 100.0
    lum = lambda v: v @ np.array([0.299, 0.587, 0.114], np.float32)
    sstep = lambda lo, hi, v: np.clip((v - lo) / (hi - lo), 0, 1)
    if g("exposure") or g("brightness"):
        x = x * (2 ** (g("exposure") * 1.5)) + g("brightness") * 0.3
    x = np.clip((x - 0.5) * (1 + g("contrast")) + 0.5, 0, 1) if g("contrast") else np.clip(x, 0, 1)
    changed = False
    if g("highlights") or g("shadows"):
        L = lum(x)[..., None]
        x = x + g("highlights") * 0.35 * sstep(0.5, 1, L) + g("shadows") * 0.35 * (1 - sstep(0, 0.5, L))
        changed = True
    if g("temperature") or g("tint"):
        x[..., 0] += g("temperature") * 0.12 + g("tint") * 0.04
        x[..., 2] -= g("temperature") * 0.12 - g("tint") * 0.04
        x[..., 1] -= g("tint") * 0.08
        changed = True
    if changed:
        x = np.clip(x, 0, 1)
    if g("saturation") or g("vibrance"):
        gray = lum(x)[..., None]
        if g("vibrance"):
            x = gray + (x - gray) * (1 + g("saturation") + g("vibrance") * (1 - chroma(x)))
        else:
            x = gray + (x - gray) * (1 + g("saturation"))
    f = a.get("filter", "None")
    if f != "None":
        pre = x
        x = np.clip(apply_filter(x, f, a), 0, 1)
        st = a.get("strength", 100) / 100.0
        if st < 1:
            x = pre + (x - pre) * st
    x = np.clip(x, 0, 1)
    size = max(x.shape[:2]) / 1000.0
    if a.get("blur"):
        x = box_blur(x, int(a["blur"] / 100 * 12 * size))
    if a.get("sharpen"):
        x = x + (a["sharpen"] / 100 * 1.5) * (x - box_blur(x, max(1, int(1.5 * size))))
    if a.get("grain"):
        x = x + grain_noise(x.shape[:2]) * (a["grain"] / 100 * 0.12)
    return np.clip(x, 0, 1)


class AdjustPanel(QDialog):
    """Per-image Edit: filter + adjustments. Dragging previews at low resolution; release renders full."""
    def __init__(self, m, it):
        super().__init__(m)
        self.m, self.it = m, it
        self.adj = json.loads(it.data(5) or "{}")
        self.setWindowTitle("Edit image")
        self.setFixedWidth(400)
        self.resize(400, 760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        lay = QVBoxLayout(inner)
        lay.addWidget(QLabel("Filter"))
        self.cur_filter = {"Mono": "Monochrome"}.get(self.adj.get("filter", "None"), self.adj.get("filter", "None"))
        self.cat = QComboBox()
        self.cat.addItems(["All filters"] + [g for g, _ in FILTER_GROUPS])
        lay.addWidget(self.cat)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search filters (e.g. portra, velvia, tri-x)...")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        self.filter = QComboBox()
        self.filter.setMaxVisibleItems(24)
        self.fill_filters()
        self.cat.currentIndexChanged.connect(self.fill_filters)
        self.search.textChanged.connect(self.fill_filters)
        self.filter.currentTextChanged.connect(self.pick_filter)
        lay.addWidget(self.filter)
        row = QHBoxLayout()
        self.duo = []
        for i, label in enumerate(("Duotone shadows", "Duotone highlights")):
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, i=i: self.pick_duo(i))
            row.addWidget(b)
            self.duo.append(b)
        lay.addLayout(row)
        self.sl, self.spins = {}, {}
        for key, label, lo, hi, dv in ADJ_SLIDERS:
            lay.addWidget(QLabel(label))
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(int(self.adj.get(key, dv)))
            sp = QSpinBox()                      # exact value, typed or stepped with the arrows
            sp.setRange(lo, hi)
            sp.setKeyboardTracking(False)        # apply on Enter / focus-out, not on every digit
            sp.setValue(s.value())
            s.valueChanged.connect(lambda v, k=key, w=s: self.set(k, v, w.isSliderDown()))
            s.valueChanged.connect(lambda v, b=sp: self.show_spin(b, v))
            s.sliderReleased.connect(lambda: self.push(False))
            sp.valueChanged.connect(s.setValue)  # moves the slider -> full-quality render + undo step
            lay.addWidget(s)
            lay.addWidget(sp)
            self.sl[key], self.spins[key] = s, sp
        lay.addStretch()
        b = QPushButton("Reset")
        b.clicked.connect(self.reset)
        outer.addWidget(b)
        self.update_duo()

    @staticmethod
    def show_spin(sp, v):
        sp.blockSignals(True)
        sp.setValue(v)
        sp.blockSignals(False)

    def fill_filters(self, *_):
        """(Re)build the filter list for the chosen category / search text; the active filter always stays listed."""
        cat, q = self.cat.currentText(), self.search.text().strip().lower()
        cur = getattr(self, "cur_filter", "None")
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("None")
        shown = {"None"}
        for group, names in FILTER_GROUPS:
            if cat != "All filters" and group != cat:
                continue
            hits = [n for n in names if q in n.lower()]
            if not hits:
                continue
            self.filter.addItem(f"-- {group} --")
            self.filter.model().item(self.filter.count() - 1).setEnabled(False)
            self.filter.addItems(hits)
            shown.update(hits)
        if cur not in shown:
            self.filter.insertItem(1, cur)
        self.filter.setCurrentText(cur)
        self.filter.blockSignals(False)

    def duo_color(self, i):
        return self.adj.get(("duo_a", "duo_b")[i], DUO_DEFAULT[i])

    def update_duo(self):
        on = self.filter.currentText() == "Duotone"
        for i, b in enumerate(self.duo):
            b.setEnabled(on)
            c = self.duo_color(i)
            set_swatch(b, c)

    def pick_duo(self, i):
        c = QColorDialog.getColor(QColor(self.duo_color(i)), self, "Duotone color")
        if c.isValid():
            self.set(("duo_a", "duo_b")[i], c.name(), False)
            self.update_duo()

    def pick_filter(self, name):
        if name.startswith("--"):
            return
        self.cur_filter = name
        self.set("filter", name, False)
        self.update_duo()

    def set(self, k, v, preview):
        self.adj[k] = v
        self.push(preview)

    def push(self, preview):
        try:
            keep = {k: v for k, v in self.adj.items() if v != ADJ_DEFAULT.get(k, 0) and v != "None"}
            self.it.setData(5, json.dumps(keep))
            self.m.refresh_image(self.it, preview)
        except RuntimeError:   # layer was deleted (e.g. by undo)
            self.close()
            return
        if not preview:
            self.m.commit()

    def reset(self):
        self.adj = {}
        for k, s in self.sl.items():
            s.blockSignals(True)
            s.setValue(ADJ_DEFAULT.get(k, 0))
            s.blockSignals(False)
            self.show_spin(self.spins[k], ADJ_DEFAULT.get(k, 0))
        self.cur_filter = "None"
        self.fill_filters()
        self.update_duo()
        self.push(False)


class CropBox:
    """Crop rectangle as fractions [left, top, right, bottom] of the full original photo (pw x ph pixels)."""
    MIN = 0.04

    def __init__(self, pw, ph, c=None):
        self.pw, self.ph, self.c, self.ratio = pw, ph, list(c or [0, 0, 1, 1]), None

    def rect(self):
        l, t, r, b = self.c
        return QRectF(l * self.pw, t * self.ph, (r - l) * self.pw, (b - t) * self.ph)

    def is_full(self):
        return all(abs(a - b) < 0.001 for a, b in zip(self.c, (0, 0, 1, 1)))

    def set_ratio(self, ratio):
        """Largest centred box with this width/height ratio."""
        self.ratio = ratio
        if not ratio:
            return
        wf, hf = ratio * self.ph / self.pw, 1.0
        if wf > 1:
            wf, hf = 1.0, self.pw / (ratio * self.ph)
        self.c = [(1 - wf) / 2, (1 - hf) / 2, (1 + wf) / 2, (1 + hf) / 2]

    def hit(self, pt, tol):
        """Which part of the box is under pt (pixels of the photo): 'tl','t','tr','l','r','bl','b','br','move' or None."""
        C, x, y = self.rect(), pt.x(), pt.y()
        inx, iny = C.left() - tol <= x <= C.right() + tol, C.top() - tol <= y <= C.bottom() + tol
        mode = ""
        if iny and abs(y - C.top()) < tol:
            mode += "t"
        elif iny and abs(y - C.bottom()) < tol:
            mode += "b"
        if inx and abs(x - C.left()) < tol:
            mode += "l"
        elif inx and abs(x - C.right()) < tol:
            mode += "r"
        if mode:
            return mode
        return "move" if C.contains(pt) else None

    def drag(self, mode, c0, dxf, dyf):
        MIN = self.MIN
        l, t, r, b = c0
        if mode == "move":
            w, h = r - l, b - t
            l, t = min(max(l + dxf, 0), 1 - w), min(max(t + dyf, 0), 1 - h)
            return [l, t, l + w, t + h]
        if "l" in mode:
            l = min(max(l + dxf, 0), r - MIN)
        if "r" in mode:
            r = max(min(r + dxf, 1), l + MIN)
        if "t" in mode:
            t = min(max(t + dyf, 0), b - MIN)
        if "b" in mode:
            b = max(min(b + dyf, 1), t + MIN)
        if self.ratio and len(mode) == 2:            # locked ratio: corners scale from the opposite corner
            pw, ph = self.pw, self.ph
            ax, ay = (r if "l" in mode else l), (b if "t" in mode else t)
            mx, my = (l if "l" in mode else r), (t if "t" in mode else b)
            w, h = abs(mx - ax) * pw, abs(my - ay) * ph
            room_x = (ax if "l" in mode else 1 - ax) * pw
            room_y = (ay if "t" in mode else 1 - ay) * ph
            w = max(MIN * pw, min(max(w, h * self.ratio), room_x, room_y * self.ratio))
            fw, fh = w / pw, w / self.ratio / ph
            l, r = (ax - fw, ax) if "l" in mode else (ax, ax + fw)
            t, b = (ay - fh, ay) if "t" in mode else (ay, ay + fh)
        return [l, t, r, b]


class CropOverlay(QGraphicsItem):
    """Crop box drawn right on the photo in the editor (child of the image layer, so it follows its scale / rotation)."""
    CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
               "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
               "move": Qt.SizeAllCursor}

    def __init__(self, parent, box, on_change):
        super().__init__(parent)
        self.box, self.on_change, self.drag = box, on_change, None
        self.setZValue(10000)

    def k(self):
        """One screen pixel expressed in the photo's own pixels."""
        sc, par = self.scene(), self.parentItem()
        return (sc.px() if sc else 1.0) / max(par.scale() if par else 1.0, 1e-6)

    def boundingRect(self):
        return QRectF(0, 0, self.box.pw, self.box.ph).adjusted(-80, -80, 80, 80)

    def cursor_at(self, scene_pos):
        mode = self.box.hit(self.mapFromScene(scene_pos), 12 * self.k())
        return self.CURSORS.get(mode, Qt.ArrowCursor)

    def paint(self, p, opt, widget=None):
        k, C = self.k(), self.box.rect()
        dim = QPainterPath()
        dim.addRect(QRectF(0, 0, self.box.pw, self.box.ph))
        dim.addRect(C)
        p.fillPath(dim, QColor(0, 0, 0, 150))
        pen = QPen(QColor(255, 255, 255, 110), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        for i in (1, 2):
            p.drawLine(QPointF(C.left() + C.width() * i / 3, C.top()), QPointF(C.left() + C.width() * i / 3, C.bottom()))
            p.drawLine(QPointF(C.left(), C.top() + C.height() * i / 3), QPointF(C.right(), C.top() + C.height() * i / 3))
        pen = QPen(QColor("white"), 2)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(C)
        al, spans = self.edge_state() if self.scene() else ({}, {})
        if any(al.values()) or spans:                  # snap guide: edges that sit exactly on a slide edge / neighbour
            gp = QPen(QColor("#2ee66b"), 4)
            gp.setCosmetic(True)
            p.setPen(gp)
            for e2, (q1, q2) in {"l": (C.topLeft(), C.bottomLeft()), "r": (C.topRight(), C.bottomRight()),
                                 "t": (C.topLeft(), C.topRight()), "b": (C.bottomLeft(), C.bottomRight())}.items():
                if al.get(e2):
                    p.drawLine(q1, q2)
            parts = []
            for ax, word in (("v", "wide"), ("h", "tall")):
                if ax in spans:
                    parts.append("Slide " + word if spans[ax] == 1 else f"{spans[ax]} slides {word}")
            label = "  -  ".join(parts) if parts else "Snapped to edge"
            p.save()
            p.translate(C.center().x(), C.top() + 14 * k)
            p.scale(k, k)
            f = QFont()
            f.setPixelSize(13)
            f.setBold(True)
            p.setFont(f)
            tw = QFontMetricsF(f).horizontalAdvance(label) + 20
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#2ee66b"))
            p.drawRoundedRect(QRectF(-tw / 2, -11, tw, 22), 11, 11)
            p.setPen(QColor("#0b2a14"))
            p.drawText(QRectF(-tw / 2, -11, tw, 22), Qt.AlignCenter, label)
            p.restore()
        pen = QPen(QColor(50, 50, 50), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QColor("white"))
        cx, cy, s = C.center().x(), C.center().y(), 6 * k
        for x, y in ((C.left(), C.top()), (C.right(), C.top()), (C.left(), C.bottom()), (C.right(), C.bottom()),
                     (cx, C.top()), (cx, C.bottom()), (C.left(), cy), (C.right(), cy)):
            p.drawRect(QRectF(x - s, y - s, 2 * s, 2 * s))

    def mousePressEvent(self, e):
        mode = self.box.hit(e.pos(), 12 * self.k())
        self.drag = (mode, list(self.box.c), e.pos()) if mode and e.button() == Qt.LeftButton else None
        e.accept()

    def mouseMoveEvent(self, e):
        if not self.drag:
            return
        mode, c0, p0 = self.drag
        self.box.c = self.box.drag(mode, c0, (e.pos().x() - p0.x()) / self.box.pw, (e.pos().y() - p0.y()) / self.box.ph)
        if not (e.modifiers() & Qt.AltModifier):
            self.snap(mode)
        elif self.scene():
            self.scene().snap_lines = []
        self.update()
        self.on_change()

    def mouseReleaseEvent(self, e):
        self.drag = None
        if self.scene():
            self.scene().snap_lines = []
            self.scene().update()
        self.update()
        e.accept()

    # ---- snapping of the crop box to slide edges / other layers (for seamless, border-free neighbours)
    def edge_geo(self, e):
        """Where crop-box edge e ('l','r','t','b') is in the scene: (axis 'v'|'h' or None, position, scene px per photo px)."""
        C = self.box.rect()
        cx, cy = C.center().x(), C.center().y()
        p = {"l": QPointF(C.left(), cy), "r": QPointF(C.right(), cy), "t": QPointF(cx, C.top()), "b": QPointF(cx, C.bottom())}[e]
        n = QPointF(1, 0) if e in "lr" else QPointF(0, 1)
        s0, s1 = self.mapToScene(p), self.mapToScene(p + n)
        dx, dy = s1.x() - s0.x(), s1.y() - s0.y()
        if min(abs(dx), abs(dy)) > 1e-3 * max(abs(dx), abs(dy), 1e-9):
            return None, 0.0, 0.0                       # rotated off the axes: no edge snapping
        return ("v", s0.x(), dx) if abs(dx) > abs(dy) else ("h", s0.y(), dy)

    def targets(self):
        sc, par = self.scene(), self.parentItem()
        xt = [i * sc.pw for i in range(sc.n + 1)]       # slide edges (every cut and the outer borders)
        yt = [j * sc.ph for j in range(sc.rows + 1)]
        for o in sc.items():
            if isinstance(o, LAYERS) and o is not par:  # edges of neighbouring layers: butt up with no gap
                r = o.sceneBoundingRect()
                xt += [r.left(), r.right()]
                yt += [r.top(), r.bottom()]
                if isinstance(o, GridItem):
                    for i in range(o.count()):
                        c = o.mapToScene(o.cell_rect(i)).boundingRect()
                        xt += [c.left(), c.right()]
                        yt += [c.top(), c.bottom()]
        return {"v": xt, "h": yt}

    def best_target(self, e, tg, thr):
        axis, pos, comp = self.edge_geo(e)
        if axis is None or abs(comp) < 1e-9:
            return None
        cand = [(t - pos, t) for t in tg[axis] if abs(t - pos) < thr]
        if not cand:
            return None
        d, t = min(cand, key=lambda c: abs(c[0]))
        return d / comp, axis, t                        # shift in photo px, axis, target

    def shift_edge(self, e, dl):
        b, c = self.box, self.box.c
        i = {"l": 0, "t": 1, "r": 2, "b": 3}[e]
        c[i] += dl / (b.pw if e in "lr" else b.ph)

    def snap(self, mode):
        sc = self.scene()
        if sc is None or self.parentItem() is None:
            return
        tg, thr, b = self.targets(), 8 * sc.px(), self.box
        lines = []
        old = list(b.c)
        edges = ["l", "r"] if mode == "move" else [e for e in mode]
        if mode == "move":
            for grp in (("l", "r"), ("t", "b")):
                cands = [(r, e) for e in grp for r in [self.best_target(e, tg, thr)] if r]
                if cands:
                    (dl, axis, t), e = min(cands, key=lambda c: abs(c[0][0]))
                    cur = b.c[:]
                    for ee in grp:
                        self.shift_edge(ee, dl)
                    if min(b.c[0], b.c[1]) < -1e-9 or max(b.c[2], b.c[3]) > 1 + 1e-9:
                        b.c = cur
                    else:
                        lines.append((axis, t))
        else:
            ratio_corner = bool(b.ratio) and len(mode) == 2
            done = set()
            for e in edges:
                if ratio_corner and e in "tb":
                    continue
                r = self.best_target(e, tg, thr)
                if r:
                    dl, axis, t = r
                    self.shift_edge(e, dl)
                    done.add(e)
                    lines.append((axis, t))
            for e in edges:                              # size snap: exactly 1, 2, 3 ... slides wide / tall
                if e in done or (ratio_corner and e in "tb"):
                    continue
                other = {"l": "r", "r": "l", "t": "b", "b": "t"}[e]
                axis, pos, comp = self.edge_geo(e)
                axis2, pos2, _ = self.edge_geo(other)
                if axis is None or axis != axis2:
                    continue
                unit = sc.pw if axis == "v" else sc.ph
                cnt = sc.n if axis == "v" else sc.rows
                span = abs(pos - pos2)
                k = round(span / unit)
                if 1 <= k <= cnt and abs(span - k * unit) < thr:
                    sg = 1 if pos - pos2 >= 0 else -1
                    self.shift_edge(e, (pos2 + sg * k * unit - pos) / comp)
            if ratio_corner:                             # keep the locked ratio: height follows the snapped width
                l, t, r, bt = b.c
                h = (r - l) * b.pw / b.ratio / b.ph
                if "b" in mode:
                    bt = min(1.0, t + h)
                    t = bt - h
                else:
                    t = max(0.0, bt - h)
                    bt = t + h
                b.c = [l, t, r, bt]
        l, t, r, bt = b.c
        if l < -1e-9 or t < -1e-9 or r > 1 + 1e-9 or bt > 1 + 1e-9 or r - l < b.MIN or bt - t < b.MIN:
            b.c = old                                    # a snap would leave the photo: ignore it
            lines = []
        sc.snap_lines = lines
        sc.update()

    def seam_targets(self):
        """For each scene axis: where the box's lower / upper edge must end up (None = not snapped to anything)."""
        sc = self.scene()
        tg, tol = self.targets(), 0.75 * sc.px()
        out = {}
        for a, b2 in (("l", "r"), ("t", "b")):
            g1, g2 = self.edge_geo(a), self.edge_geo(b2)
            if g1[0] is None or g1[0] != g2[0]:
                continue
            res = []
            for g in sorted((g1, g2), key=lambda g: g[1]):
                near = [t for t in tg[g[0]] if abs(t - g[1]) < tol]
                res.append(min(near, key=lambda t: abs(t - g[1])) if near else None)
            out[g1[0]] = tuple(res)
        return out

    def edge_state(self):
        """Per edge: is it exactly on a slide edge / neighbouring layer?  Plus how many slides wide / tall the box is."""
        sc = self.scene()
        tg, tol = self.targets(), 0.75 * sc.px()
        al = {}
        for e in "lrtb":
            axis, pos, comp = self.edge_geo(e)
            al[e] = axis is not None and any(abs(t - pos) < tol for t in tg[axis])
        spans = {}
        for a, b2 in (("l", "r"), ("t", "b")):
            ax1, p1, _ = self.edge_geo(a)
            ax2, p2, _ = self.edge_geo(b2)
            if ax1 and ax1 == ax2:
                unit, cnt = (sc.pw, sc.n) if ax1 == "v" else (sc.ph, sc.rows)
                k = round(abs(p1 - p2) / unit)
                if 1 <= k <= cnt and abs(abs(p1 - p2) - k * unit) < tol:
                    spans[ax1] = k
        return al, spans


class CropPanel(QWidget):
    """Shown in the right-hand panel only while an image is being cropped."""
    def __init__(self, main):
        super().__init__()
        self.m, self.box, self.busy, self.overlay, self.ratios = main, None, False, None, []
        lay = QVBoxLayout(self)
        hint = QLabel("Drag the edges or corners of the box on the photo, or drag inside it to move it.\n"
                      "Enter = apply     Esc = cancel\nClicking away from the photo also applies.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addWidget(QLabel("Aspect ratio"))
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self.ratio_changed)
        lay.addWidget(self.combo)
        lay.addWidget(QLabel("Trimmed from each side"))
        g = QGridLayout()
        self.sp = {}
        for i, name in enumerate(("Left", "Top", "Right", "Bottom")):
            sb = QSpinBox()
            sb.setRange(0, 90)
            sb.setSuffix(" %")
            sb.setKeyboardTracking(False)
            sb.valueChanged.connect(self.spin_changed)
            g.addWidget(QLabel(name), (i // 2) * 2, i % 2)
            g.addWidget(sb, (i // 2) * 2 + 1, i % 2)
            self.sp[name] = sb
        lay.addLayout(g)
        row = QHBoxLayout()
        for label, fn in (("Apply", lambda: main.end_crop(True)), ("Reset", self.reset), ("Cancel", lambda: main.end_crop(False))):
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, f=fn: f())
            row.addWidget(b)
        lay.addLayout(row)
        lay.addStretch()

    def load(self, box, overlay, slide_ratio, keep):
        self.box, self.overlay = box, overlay
        self.ratios = [("Free-form", None), ("Original", box.pw / box.ph), ("Slide", slide_ratio), ("1:1", 1.0),
                       ("4:5", 0.8), ("3:4", 0.75), ("9:16", 9 / 16), ("16:9", 16 / 9)]
        if keep:
            self.ratios.insert(0, ("Current frame (keeps its size)", box.ratio))
        self.busy = True
        self.combo.clear()
        self.combo.addItems([n for n, _ in self.ratios])
        self.combo.setCurrentIndex(0)
        self.busy = False
        self.sync()

    def sync(self):
        if not self.box:
            return
        l, t, r, b = self.box.c
        self.busy = True
        for name, v in (("Left", l), ("Top", t), ("Right", 1 - r), ("Bottom", 1 - b)):
            self.sp[name].setValue(round(v * 100))
        self.busy = False

    def changed(self):
        if self.overlay is not None:
            self.overlay.update()
        self.sync()

    def ratio_changed(self, i):
        if self.busy or not self.box:
            return
        r = self.ratios[i][1]
        self.box.ratio = r
        if r:
            self.box.set_ratio(r)
        self.changed()

    def spin_changed(self, *_):
        if self.busy or not self.box:
            return
        l, t, rt, bt = (self.sp[k].value() / 100 for k in ("Left", "Top", "Right", "Bottom"))
        r, b = max(1 - rt, l + 0.05), max(1 - bt, t + 0.05)
        self.box.c = [l, t, min(r, 1.0), min(b, 1.0)]
        self.box.ratio = None                       # typed numbers are free-form
        self.busy = True
        self.combo.setCurrentIndex(next((i for i, (_, v) in enumerate(self.ratios) if v is None), 0))
        self.busy = False
        if self.overlay is not None:
            self.overlay.update()

    def reset(self):
        if self.box:
            self.box.c = [0, 0, 1, 1]
            self.changed()


def soften(img, r):
    """Feather an ARGB image's edges by down/up scaling (no extra packages needed)."""
    k = int(r)
    if k < 2:
        return img
    w, h = img.width(), img.height()
    small = img.scaled(max(1, w // k), max(1, h // k), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_ARGB32)


def alpha_to_qimage(a):
    """float HxW (0..1) -> white ARGB32 image whose alpha is a."""
    h, w = a.shape
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = 255
    out[..., 3] = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    return QImage(out.data, w, h, w * 4, QImage.Format_RGBA8888).copy().convertToFormat(QImage.Format_ARGB32)


def flood_keep_mask(img, tol, seed=None, contiguous=True, smooth=2):
    """Colour-based background removal (numpy only). seed=None: background colours are sampled from the photo's
    border and removed where connected to the border. seed=(x, y): remove the region of that colour around the click."""
    W, H = img.width(), img.height()
    f = max(1, int(math.ceil(max(W, H) / 640)))
    small = img.scaled(max(1, W // f), max(1, H // f), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    rgb, a0 = qimage_to_np(small)
    h, w = rgb.shape[:2]
    thr = tol / 100.0 * 0.9
    start = np.zeros((h, w), bool)
    if seed is None:
        border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        q = np.round(border * 15).astype(int)
        key = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
        vals, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
        cols = [border[inv == i].mean(0) for i in np.argsort(-counts)[:3] if counts[i] >= 0.08 * len(border)]
        cols = cols or [border.mean(0)]
        d = np.min([np.linalg.norm(rgb - c, axis=-1) for c in cols], axis=0)
        cand = d <= thr
        start[0, :] = start[-1, :] = start[:, 0] = start[:, -1] = True
        start &= cand
    else:
        sx, sy = min(max(int(seed[0] / f), 0), w - 1), min(max(int(seed[1] / f), 0), h - 1)
        cand = np.linalg.norm(rgb - rgb[sy, sx], axis=-1) <= thr
        start[sy, sx] = True
    if contiguous:
        bg = start.copy()
        for _ in range(4000):
            nb = bg.copy()
            nb[1:] |= bg[:-1]
            nb[:-1] |= bg[1:]
            nb[:, 1:] |= bg[:, :-1]
            nb[:, :-1] |= bg[:, 1:]
            nb &= cand
            if np.array_equal(nb, bg):
                break
            bg = nb
    else:
        bg = cand
    keep = (~bg).astype(np.float32)[..., None]
    keep = box_blur(keep, max(0, int(smooth)))[..., 0]
    return alpha_to_qimage(keep).scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def ai_keep_mask(img):
    """Optional: pip install rembg  (downloads a small segmentation model the first time)."""
    from rembg import remove
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    res = QImage.fromData(remove(bytes(buf.data()))).convertToFormat(QImage.Format_ARGB32)
    mask = QImage(res.size(), QImage.Format_ARGB32)
    mask.fill(QColor(255, 255, 255))
    p = QPainter(mask)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(0, 0, res)
    p.end()
    return mask


class MaskCanvas(QWidget):
    """Photo on a checkerboard with its live keep-mask. Wheel = zoom, middle-drag = pan."""
    def __init__(self, base, mask):
        super().__init__()
        self.base, self.mask = base, mask
        self.shown = QImage(base.size(), QImage.Format_ARGB32_Premultiplied)
        self.tool, self.erase, self.size, self.hard = "wand", True, 40, 70
        self.s, self.o, self.fitted = 1.0, QPointF(10, 10), False
        self.pts, self.poly_mode, self.drag, self.cur = [], False, None, None
        self.on_begin = self.on_pick = None          # callbacks: stroke begins (push undo) / click in 'wand' tool
        self.setMinimumSize(560, 460)
        self.setMouseTracking(True)
        tile = QPixmap(24, 24)
        tile.fill(QColor(200, 200, 200))
        tp = QPainter(tile)
        tp.fillRect(0, 0, 12, 12, QColor(150, 150, 150))
        tp.fillRect(12, 12, 12, 12, QColor(150, 150, 150))
        tp.end()
        self.checker = QBrush(tile)
        self.rebuild()

    def rebuild(self, r=None):
        r = r or self.base.rect()
        p = QPainter(self.shown)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(r.topLeft(), self.base, r)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(r.topLeft(), self.mask, r)
        p.end()
        self.update()

    def fit(self):
        W, H = self.width() - 20, self.height() - 20
        self.s = max(0.01, min(W / self.base.width(), H / self.base.height()))
        self.o = QPointF((self.width() - self.base.width() * self.s) / 2, (self.height() - self.base.height() * self.s) / 2)
        self.fitted = True
        self.update()

    def resizeEvent(self, e):
        if not self.fitted or self.drag is None:
            self.fit()

    def to_img(self, pt):
        return QPointF((pt.x() - self.o.x()) / self.s, (pt.y() - self.o.y()) / self.s)

    def to_wid(self, pt):
        return QPointF(self.o.x() + pt.x() * self.s, self.o.y() + pt.y() * self.s)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(36, 36, 40))
        tr = QRectF(self.o.x(), self.o.y(), self.base.width() * self.s, self.base.height() * self.s)
        p.setBrushOrigin(tr.topLeft())
        p.fillRect(tr, self.checker)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.s < 1)
        p.drawImage(tr, self.shown)
        p.setRenderHint(QPainter.Antialiasing)
        if self.pts:
            pen = QPen(QColor("white"), 2, Qt.DashLine)
            p.setPen(pen)
            wp = [self.to_wid(q) for q in self.pts]
            p.setBrush(QColor(80, 160, 255, 50))
            p.drawPolygon(QPolygonF(wp)) if (self.drag == "lasso" or len(wp) > 2) else p.drawPolyline(QPolygonF(wp))
            if self.poly_mode:
                p.setBrush(QColor("white"))
                for q in wp:
                    p.drawEllipse(q, 4, 4)
        if self.tool == "brush" and self.cur is not None:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.drawEllipse(self.cur, self.size * self.s, self.size * self.s)
            p.setPen(QPen(QColor(0, 0, 0), 1))
            p.drawEllipse(self.cur, self.size * self.s + 1.5, self.size * self.s + 1.5)

    # ----- painting on the mask -----
    def stamp(self, pt):
        r, h = float(self.size), self.hard / 100.0
        c = QColor(0, 0, 0, 255) if self.erase else QColor(255, 255, 255, 255)
        c0 = QColor(c)
        c1 = QColor(c)
        c1.setAlpha(0)
        g = QRadialGradient(pt, r)
        g.setColorAt(0, c0)
        g.setColorAt(min(h, 0.99), c0)
        g.setColorAt(1, c1)
        p = QPainter(self.mask)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut if self.erase else QPainter.CompositionMode_SourceOver)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(pt, r, r)
        p.end()
        self.rebuild(QRectF(pt.x() - r - 2, pt.y() - r - 2, 2 * r + 4, 2 * r + 4).toAlignedRect().intersected(self.base.rect()))

    def stroke_to(self, pt):
        a, d = self.last, math.hypot(pt.x() - self.last.x(), pt.y() - self.last.y())
        step = max(1.0, self.size * 0.2)
        n = max(1, int(d / step))
        for i in range(1, n + 1):
            self.stamp(QPointF(a.x() + (pt.x() - a.x()) * i / n, a.y() + (pt.y() - a.y()) * i / n))
        self.last = pt

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MiddleButton:
            self.drag, self.pan0 = "pan", pos
            return
        if e.button() != Qt.LeftButton:
            return
        ip = self.to_img(pos)
        if self.tool == "brush":
            if self.on_begin:
                self.on_begin()
            self.drag, self.last = "paint", ip
            self.stamp(ip)
        elif self.tool == "lasso":
            self.pts, self.drag = [ip], "lasso"
        elif self.tool == "poly":
            if len(self.pts) >= 3 and math.hypot(*(self.to_wid(self.pts[0]) - pos).toTuple()) < 10:
                self.drag = None              # clicked the first point: polygon is complete
            else:
                self.pts.append(ip)
            self.update()
        elif self.tool == "wand" and self.on_pick:
            self.on_pick(ip)

    def mouseMoveEvent(self, e):
        pos = e.position()
        self.cur = pos
        if self.drag == "pan":
            self.o += pos - self.pan0
            self.pan0 = pos
        elif self.drag == "paint":
            self.stroke_to(self.to_img(pos))
        elif self.drag == "lasso":
            self.pts.append(self.to_img(pos))
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag in ("pan", "paint", "lasso"):
            self.drag = None

    def mouseDoubleClickEvent(self, e):
        pass

    def leaveEvent(self, e):
        self.cur = None
        self.update()

    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        pos = e.position()
        ip = self.to_img(pos)
        self.s = min(40.0, max(0.02, self.s * f))
        self.o = QPointF(pos.x() - ip.x() * self.s, pos.y() - ip.y() * self.s)
        self.fitted = True
        self.update()


class MaskEditor(QDialog):
    """Background tools: Remove Background (auto / click), Cut out (lasso or polygon), Erase / Restore (brush)."""
    TABS = {"remove": 0, "cutout": 1, "erase": 2}

    def __init__(self, parent, base, mask, tool="remove"):
        super().__init__(parent)
        self.setWindowTitle("Background tools")
        self.resize(1040, 720)
        self.hist, self.changed = [], False
        self.cv = MaskCanvas(base, mask)
        self.cv.on_begin = self.push_hist
        self.cv.on_pick = self.pick_remove
        lay = QHBoxLayout(self)
        lay.addWidget(self.cv, 1)
        side = QVBoxLayout()
        lay.addLayout(side)
        self.tabs = QTabWidget()
        self.tabs.setFixedWidth(300)
        side.addWidget(self.tabs)

        # --- Remove Background
        w = QWidget()
        v = QVBoxLayout(w)
        self.ai = QCheckBox("Use AI model (needs: pip install rembg)")
        try:
            import rembg  # noqa: F401
            self.ai.setChecked(True)
        except Exception:
            self.ai.setEnabled(False)
        v.addWidget(self.ai)
        self.tol = slider_spin(v, "Color tolerance", 1, 100, lambda x, d: None)
        self.tol[2](22)
        self.smooth = slider_spin(v, "Edge smoothing", 0, 12, lambda x, d: None)
        self.smooth[2](2)
        self.contig = QCheckBox("Only background connected to the photo's edges")
        self.contig.setChecked(True)
        v.addWidget(self.contig)
        b = QPushButton("Remove Background (auto)")
        b.clicked.connect(self.auto_remove)
        v.addWidget(b)
        v.addWidget(QLabel("Or click a background area on the photo\nto remove that color region."))
        v.addStretch()
        self.tabs.addTab(w, "Remove BG")

        # --- Cut out
        w = QWidget()
        v = QVBoxLayout(w)
        self.cmode = QComboBox()
        self.cmode.addItems(["Freehand lasso (drag)", "Polygon (click points)"])
        self.cmode.currentIndexChanged.connect(self.set_tool)
        v.addWidget(self.cmode)
        self.keep = QComboBox()
        self.keep.addItems(["Keep inside the selection", "Remove inside the selection"])
        v.addWidget(self.keep)
        self.feather = slider_spin(v, "Feather (px)", 0, 60, lambda x, d: None)
        b = QPushButton("Apply Cut Out")
        b.clicked.connect(self.apply_cut)
        v.addWidget(b)
        b = QPushButton("Clear Selection")
        b.clicked.connect(self.clear_sel)
        v.addWidget(b)
        v.addWidget(QLabel("Polygon: click the first point or press\nApply to close the shape."))
        v.addStretch()
        self.tabs.addTab(w, "Cut out")

        # --- Erase
        w = QWidget()
        v = QVBoxLayout(w)
        self.emode = QComboBox()
        self.emode.addItems(["Erase", "Restore (paint back)"])
        self.emode.currentIndexChanged.connect(self.set_tool)
        v.addWidget(self.emode)
        self.bsize = slider_spin(v, "Brush size (px)", 2, 400, self.brush_changed)
        self.bsize[2](40)
        self.bhard = slider_spin(v, "Hardness (%)", 0, 100, self.brush_changed)
        self.bhard[2](70)
        v.addStretch()
        self.tabs.addTab(w, "Erase")

        row = QHBoxLayout()
        for label, fn in (("Undo", self.undo), ("Reset all", self.reset_all), ("Fit", self.cv.fit)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        side.addLayout(row)
        side.addWidget(QLabel("Wheel = zoom, middle-drag = move"))
        side.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        side.addWidget(bb)
        self.tabs.currentChanged.connect(self.set_tool)
        self.tabs.setCurrentIndex(self.TABS.get(tool, 0))
        self.set_tool()

    @property
    def mask(self):
        return self.cv.mask

    def set_tool(self, *_):
        i = self.tabs.currentIndex()
        c = self.cv
        c.pts, c.drag = [], None
        c.poly_mode = i == 1 and self.cmode.currentIndex() == 1
        c.tool = ("wand", "poly" if c.poly_mode else "lasso", "brush")[i]
        c.erase = self.emode.currentIndex() == 0
        c.setCursor(Qt.CrossCursor if c.tool != "brush" else Qt.BlankCursor)
        c.update()

    def brush_changed(self, *_):
        self.cv.size, self.cv.hard = self.bsize[0].value(), self.bhard[0].value()

    # ----- history -----
    def push_hist(self):
        self.hist.append(self.cv.mask.copy())
        del self.hist[:-10]
        self.changed = True

    def undo(self):
        if self.hist:
            self.cv.mask = self.hist.pop()
            self.cv.rebuild()

    def reset_all(self):
        self.push_hist()
        self.cv.mask.fill(QColor(255, 255, 255))
        self.cv.rebuild()

    def merge(self, keep):
        """Multiply the mask by `keep` (an ARGB image whose alpha = what to keep)."""
        self.push_hist()
        p = QPainter(self.cv.mask)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, keep)
        p.end()
        self.cv.rebuild()

    # ----- tools -----
    def need_numpy(self):
        if np is None:
            QMessageBox.warning(self, "Remove background", "This needs numpy:\n\npip install numpy")
            return True
        return False

    def auto_remove(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self.ai.isChecked():
                try:
                    self.merge(ai_keep_mask(self.cv.base))
                    return
                except Exception as ex:
                    QMessageBox.warning(self, "AI background removal failed", f"{ex}\n\nFalling back to the color-based method.")
            if self.need_numpy():
                return
            self.merge(flood_keep_mask(self.cv.base, self.tol[0].value(), None, self.contig.isChecked(), self.smooth[0].value()))
        finally:
            QApplication.restoreOverrideCursor()

    def pick_remove(self, ip):
        if self.need_numpy():
            return
        x, y = int(ip.x()), int(ip.y())
        if not (0 <= x < self.cv.base.width() and 0 <= y < self.cv.base.height()):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.merge(flood_keep_mask(self.cv.base, self.tol[0].value(), (x, y), self.contig.isChecked(), self.smooth[0].value()))
        finally:
            QApplication.restoreOverrideCursor()

    def clear_sel(self):
        self.cv.pts = []
        self.cv.update()

    def apply_cut(self):
        pts = self.cv.pts
        if len(pts) < 3:
            QMessageBox.information(self, "Cut out", "Draw a selection around the part you want first.")
            return
        inside = self.keep.currentIndex() == 0
        poly = QImage(self.cv.base.size(), QImage.Format_ARGB32)
        poly.fill(QColor(0, 0, 0, 0) if inside else QColor(255, 255, 255, 255))
        path = QPainterPath()
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
        p = QPainter(poly)
        p.setRenderHint(QPainter.Antialiasing)
        if inside:
            p.fillPath(path, QColor(255, 255, 255))
        else:
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillPath(path, QColor(0, 0, 0))
        p.end()
        self.merge(soften(poly, self.feather[0].value()))
        self.cv.pts = []
        self.cv.update()


class TextPanel(QDialog):
    """Font menu: font / colour, alignment, line spacing, indent, outline. Applies to the selected text layers."""
    def __init__(self, m):
        super().__init__(m)
        self.m, self.busy = m, False
        self.setWindowTitle("Text / Font")
        self.setFixedWidth(340)
        self.resize(340, 460)
        lay = QVBoxLayout(self)
        for label, fn in (("Font...", m.pick_font), ("Text Color...", m.pick_text_color)):
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, f=fn: f())
            lay.addWidget(b)
        self.line = self.slider_row(lay, "Line spacing (%)", 50, 300, "line_h")
        lay.addWidget(QLabel("Indent"))
        g = QGridLayout()
        dec, inc = QPushButton("Decrease Indent"), QPushButton("Increase Indent")
        dec.clicked.connect(lambda: self.bump(-1))
        inc.clicked.connect(lambda: self.bump(1))
        self.ind_lbl = QLabel()
        g.addWidget(dec, 0, 0)
        g.addWidget(inc, 0, 1)
        g.addWidget(self.ind_lbl, 1, 0, 1, 2)
        lay.addLayout(g)
        lay.addWidget(QLabel("Text outline"))
        self.ocolor = QPushButton("Outline Color...")
        self.ocolor.clicked.connect(self.pick_outline)
        lay.addWidget(self.ocolor)
        self.outline = self.slider_row(lay, "Outline width (px)", 0, 40, "outline_w")
        lay.addStretch()
        m.scene.selectionChanged.connect(self.refresh)
        self.refresh()

    def texts(self):
        return [i for i in self.m.layers_sel() if isinstance(i, TextItem)]

    def slider_row(self, lay, label, lo, hi, attr):
        lay.addWidget(QLabel(label))
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        sp = QSpinBox()                       # exact value
        sp.setRange(lo, hi)
        sp.setKeyboardTracking(False)

        def changed(v):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
            self.put(attr, v, not s.isSliderDown())
        s.valueChanged.connect(changed)
        s.sliderReleased.connect(self.m.commit)
        sp.valueChanged.connect(s.setValue)
        lay.addWidget(s)
        lay.addWidget(sp)
        return s, sp

    def put(self, attr, v, final):
        if self.busy:
            return
        its = self.texts()
        for it in its:
            setattr(it, attr, v)
            self.m.relayout(it)
        self.m.scene.update()
        if its and final:
            self.m.commit()

    def bump(self, d):
        its = self.texts()
        for it in its:
            it.indent = max(0, min(10, it.indent + d))
            self.m.relayout(it)
        if its:
            self.m.scene.update()
            self.m.commit()
            self.refresh()

    def pick_outline(self):
        its = self.texts()
        if not its:
            return
        c = QColorDialog.getColor(its[0].outline, self, "Outline color")
        if not c.isValid():
            return
        for it in its:
            it.outline = c
            if it.outline_w == 0:
                it.outline_w = 3                 # so the new colour is visible straight away
            self.m.relayout(it)
        self.m.scene.update()
        self.m.commit()
        self.refresh()

    def refresh(self):
        its = self.texts()
        self.setEnabled(bool(its))
        if not its:
            return
        it = its[0]
        self.busy = True
        for (s, sp), v in ((self.line, it.line_h), (self.outline, it.outline_w)):
            for w in (s, sp):
                w.blockSignals(True)
                w.setValue(int(v))
                w.blockSignals(False)
        self.ind_lbl.setText(f"Indent level: {it.indent}")
        self.ocolor.setText(f"Outline Color...  ({it.outline.name()})")
        self.busy = False


class ShapePanel(QDialog):
    """Insert > shapes: opacity, corner radius (+ individual corners), shadow, border (style / thickness / corner / position)."""
    def __init__(self, m):
        super().__init__(m)
        self.m, self.busy = m, False
        self.setWindowTitle("Edit shape")
        self.setFixedWidth(400)
        self.resize(400, 780)
        outer = QVBoxLayout(self)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        sc.setWidget(inner)
        outer.addWidget(sc)
        lay = QVBoxLayout(inner)
        b = QPushButton("Fill Color...")
        b.clicked.connect(lambda: m.shape_prop("fill"))
        lay.addWidget(b)
        self.nofill = QCheckBox("Transparent fill (invisible inside - makes a frame)")
        self.nofill.toggled.connect(lambda v: self.put("nofill", v, False))
        lay.addWidget(self.nofill)
        self.op = slider_spin(lay, "Opacity (%)", 5, 100, lambda v, d: self.put("opacity", v, d), m.commit)
        self.rad = slider_spin(lay, "Corner radius (px)", 0, 500, lambda v, d: self.put("radius", v, d), m.commit)
        lay.addWidget(QLabel("Round these corners (toggle each on / off)"))
        g = QGridLayout()
        self.cbs = []
        for i, name in enumerate(("Top-left", "Top-right", "Bottom-left", "Bottom-right")):
            cb = QCheckBox(name)
            cb.toggled.connect(lambda v, i=i: self.put("corner", (i, v), False))
            g.addWidget(cb, i // 2, i % 2)
            self.cbs.append(cb)
        lay.addLayout(g)
        self.shadow = QCheckBox("Shadow")
        self.shadow.toggled.connect(lambda v: self.put("shadow", v, False))
        lay.addWidget(self.shadow)
        lay.addWidget(QLabel("Border"))
        self.style = QComboBox()
        self.style.addItems(["Line (solid)", "Dashed line", "Dotted line"])
        self.style.currentIndexChanged.connect(lambda i: self.put("dash", ("solid", "dash", "dot")[i], False))
        lay.addWidget(self.style)
        self.bw = slider_spin(lay, "Thickness (px)", 0, 100, lambda v, d: self.put("bw", v, d), m.commit)
        bc = QPushButton("Border Color...")
        bc.clicked.connect(lambda: m.shape_prop("border"))
        lay.addWidget(bc)
        self.noborder = QCheckBox("Transparent border (invisible)")
        self.noborder.toggled.connect(lambda v: self.put("noborder", v, False))
        lay.addWidget(self.noborder)
        lay.addWidget(QLabel("Border corner"))
        self.join = QComboBox()
        self.join.addItems(["Sharp", "Rounded", "Beveled"])
        self.join.currentIndexChanged.connect(lambda i: self.put("join", ("miter", "round", "bevel")[i], False))
        lay.addWidget(self.join)
        lay.addWidget(QLabel("Border position"))
        self.bpos = QComboBox()
        self.bpos.addItems(["Outside", "Inside", "Center"])
        self.bpos.currentIndexChanged.connect(lambda i: self.put("bpos", ("outside", "inside", "center")[i], False))
        lay.addWidget(self.bpos)
        lay.addStretch()
        m.scene.selectionChanged.connect(self.refresh)
        self.refresh()

    def shape(self):
        it = self.m.selected()
        return it if isinstance(it, ShapeItem) else None

    def put(self, what, v, dragging):
        it = self.shape()
        if it is None or self.busy or it.data(1):
            return
        it.prepareGeometryChange()
        if what == "opacity":
            it.setOpacity(v / 100)
        elif what == "radius":
            it.radius = v
        elif what == "corner":
            it.corners[v[0]] = v[1]
        elif what == "shadow":
            it.set_shadow(v)
        elif what == "nofill":
            it.no_fill = v
        elif what == "noborder":
            it.no_border = v
        elif what == "dash":
            it.dash = v
        elif what == "bw":
            it.bw = v
        elif what == "join":
            it.bjoin = v
        elif what == "bpos":
            it.bpos = v
        self.m.shape_changed(it)
        if not dragging:
            self.m.commit()

    def refresh(self):
        it = self.shape()
        self.setEnabled(it is not None and not it.data(1))
        if it is None:
            return
        self.busy = True
        mx = max(1, int(min(it.w, it.h) // 2))
        for w in (self.rad[0], self.rad[1]):
            w.setMaximum(mx)
        self.op[2](round(it.opacity() * 100))
        self.rad[2](min(it.radius, mx))
        self.bw[2](it.bw)
        # order of the checkboxes: TL, TR, BL, BR  ->  corners list: TL, TR, BR, BL
        for cb, idx in zip(self.cbs, (0, 1, 3, 2)):
            cb.blockSignals(True)
            cb.setChecked(it.corners[idx])
            cb.blockSignals(False)
        for w, v in ((self.shadow, it.shadow), (self.nofill, it.no_fill), (self.noborder, it.no_border)):
            w.blockSignals(True)
            w.setChecked(v)
            w.blockSignals(False)
        for combo, val, opts in ((self.style, it.dash, ("solid", "dash", "dot")), (self.join, it.bjoin, ("miter", "round", "bevel")),
                                 (self.bpos, it.bpos, ("outside", "inside", "center"))):
            combo.blockSignals(True)
            combo.setCurrentIndex(opts.index(val))
            combo.blockSignals(False)
        rect_like = it.kind == "rect"
        for w in (self.rad[0], self.rad[1], *self.cbs):
            w.setEnabled(rect_like)
        for w in (self.join, self.bpos):
            w.setEnabled(it.kind != "line")
        self.busy = False


class GridDialog(QDialog):
    """Rows / columns / gap / corner radius / empty-cell colour for a Grid layer."""
    def __init__(self, parent, g):
        super().__init__(parent)
        self.setWindowTitle("Grid settings")
        self.color = QColor(g.fill)
        f = QFormLayout(self)
        self.sp = {}
        for key, label, lo, hi, v in (("rows", "Rows", 1, 12, g.rows), ("cols", "Columns", 1, 12, g.cols),
                                      ("gap", "Gap (px)", 0, 400, g.gap), ("radius", "Corner radius (px)", 0, 1000, g.radius)):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setValue(int(v))
            f.addRow(label, sb)
            self.sp[key] = sb
        self.cbtn = QPushButton()
        self.cbtn.clicked.connect(self.pick)
        f.addRow("Empty cell color", self.cbtn)
        self.transp = QCheckBox("Transparent (empty cells show the background)")
        self.transp.setChecked(self.color.alpha() == 0)
        self.transp.toggled.connect(self.set_transparent)
        f.addRow("", self.transp)
        self.paint_btn()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def paint_btn(self):
        c = self.color
        set_swatch(self.cbtn, c, "Transparent" if c.alpha() == 0 else c.name(QColor.HexArgb if c.alpha() < 255 else QColor.HexRgb))

    def set_transparent(self, on):
        if on:
            self.color = QColor(self.color.red(), self.color.green(), self.color.blue(), 0)
        elif self.color.alpha() == 0:
            self.color.setAlpha(255)
        self.paint_btn()

    def pick(self):
        c = pick_color_transparent(self, self.color, "Empty cell color")
        if c is not None:
            self.color = c
            self.transp.blockSignals(True)
            self.transp.setChecked(c.alpha() == 0)
            self.transp.blockSignals(False)
            self.paint_btn()


def pick_color_transparent(parent, color, title):
    """Colour dialog with alpha plus a 'Transparent' checkbox inside it. Returns the QColor, or None if cancelled."""
    base = QColor(color)
    was_transp = base.alpha() == 0
    if was_transp:
        base.setAlpha(255)
    dlg = QColorDialog(base, parent)
    dlg.setWindowTitle(title)
    dlg.setOption(QColorDialog.ShowAlphaChannel, True)
    dlg.setOption(QColorDialog.DontUseNativeDialog, True)
    chk = QCheckBox("Transparent")
    chk.setChecked(was_transp)
    lay = dlg.layout()
    if isinstance(lay, QGridLayout):
        lay.addWidget(chk, lay.rowCount(), 0, 1, lay.columnCount())
    else:
        lay.insertWidget(max(0, lay.count() - 1), chk)
    last = [QColor(base)]

    def on_toggle(on):
        if on:
            last[0] = QColor(dlg.currentColor())
            c = QColor(last[0]); c.setAlpha(0)
            dlg.setCurrentColor(c)
        else:
            c = QColor(last[0]); c.setAlpha(255 if last[0].alpha() == 0 else last[0].alpha())
            dlg.setCurrentColor(c)

    def on_color(c):      # moving the alpha slider to 0 ticks the box, and vice versa
        chk.blockSignals(True)
        chk.setChecked(c.alpha() == 0)
        chk.blockSignals(False)

    chk.toggled.connect(on_toggle)
    dlg.currentColorChanged.connect(on_color)
    if was_transp:
        on_toggle(True)
    if not dlg.exec():
        return None
    return QColor(dlg.currentColor())


# ---------------------------------------------------------------- grid layouts (Grids picker)
def _rows(spec):
    out, y = [], 0.0
    for h, ws in spec:
        x = 0.0
        for w in ws:
            out.append((x, y, x + w, y + h))
            x += w
        y += h
    return out


def _cols(spec):
    out, x = [], 0.0
    for w, hs in spec:
        y = 0.0
        for h in hs:
            out.append((x, y, x + w, y + h))
            y += h
        x += w
    return out


_t3, _q = [1 / 3] * 3, [.25] * 4
GRID_LAYOUTS = [
    _cols([(.5, [1]), (.5, [1])]), _rows([(.5, [1]), (.5, [1])]),
    _rows([(.5, [1]), (.5, [.5, .5])]), _cols([(.5, [1]), (.5, [.5, .5])]),
    _cols([(.5, [.5, .5]), (.5, [1])]), _rows([(.5, [.5, .5]), (.5, [1])]),
    _cols([(1 / 3, [1])] * 3), _rows([(1 / 3, [1])] * 3),
    _rows([(.62, [1]), (.38, _t3)]), _cols([(.55, [1]), (.45, _t3)]),
    _rows([(.4, _t3), (.6, [1])]), _cols([(.5, [.7, .3]), (.5, [.3, .7])]),
    _rows([(.33, [.33, .67]), (.67, [.67, .33])]), _rows([(.25, [1])] * 4),
    _cols([(.25, [1])] * 4), _rows([(.5, [.5, .5]), (.5, [.5, .5])]),
    _cols([(.5, _t3), (.5, [1])]), _cols([(.2, [1])] * 5),
    _rows([(.2, [1])] * 5), _rows([(.5, [.5, .5]), (.5, _t3)]),
    _rows([(.5, _t3), (.5, [.67, .33])]), _rows([(.4, [.5, .5]), (.3, [.5, .5]), (.3, [.5, .5])]),
    _rows([(.25, [.5, .5]), (.35, [.5, .5]), (.4, [.4, .6])]), _rows([(.5, _q), (.5, _q)]),
    _rows([(1 / 3, _t3), (1 / 3, [.67, .33]), (1 / 3, _t3)]),
    _rows([(.25, _q), (.25, [.5, .25, .25]), (.25, [.25, .25, .5]), (.25, _q)]),
]


def grid_layout_icon(cells, size=96, dark=True):
    """Tile picture of a layout: rounded square, grey cells separated by thin light gaps (like the Grids picker)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), size * .2, size * .2)
    p.setClipPath(clip)
    shades = [200, 212, 222, 206, 230, 216]
    for i, (x0, y0, x1, y1) in enumerate(cells):
        g = 1.5
        r = QRectF(x0 * size + (g if x0 > 0 else 0), y0 * size + (g if y0 > 0 else 0),
                   (x1 - x0) * size - (g if x0 > 0 else 0) - (g if x1 < 1 else 0),
                   (y1 - y0) * size - (g if y0 > 0 else 0) - (g if y1 < 1 else 0))
        p.fillRect(r, QColor(shades[i % 6], shades[i % 6], shades[i % 6] + 4))
    p.end()
    return pm


class GridsDialog(QDialog):
    """Pick a collage layout (2-3-4-5 cells...). Double-click or click to insert it as a Grid layer."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Grids")
        self.chosen = None
        self.setFixedWidth(520)
        self.resize(520, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Choose a layout - it is added as a Grid layer you can fill with photos."))
        lst = QListWidget()
        lst.setViewMode(QListWidget.IconMode)
        lst.setIconSize(QSize(96, 96))
        lst.setGridSize(QSize(112, 112))
        lst.setMovement(QListWidget.Static)
        lst.setResizeMode(QListWidget.Adjust)
        lst.setSpacing(4)
        for i, cells in enumerate(GRID_LAYOUTS):
            li = QListWidgetItem(QIcon(grid_layout_icon(cells)), "")
            li.setData(Qt.UserRole, i)
            li.setToolTip(f"{len(cells)} cells")
            lst.addItem(li)
        lst.itemClicked.connect(self.pick)
        lst.itemActivated.connect(self.pick)
        lay.addWidget(lst, 1)

    def pick(self, li):
        self.chosen = li.data(Qt.UserRole)
        self.accept()


# ---------------------------------------------------------------- templates
def _font(family, px, bold=False, italic=False):
    f = QFont(family)
    f.setPixelSize(px)
    f.setBold(bold)
    f.setItalic(italic)
    return f.toString()


def T_text(text, x, y, px=64, color="#111111", bold=True, family="Segoe UI", italic=False, box_w=0, align="left", line_h=100):
    return dict(type="text", x=x, y=y, text=text, font=_font(family, px, bold, italic), color=color, align=align,
                box_w=box_w, line_h=line_h, indent=0, outline_w=0, outline="#000000")


def T_shape(kind, x, y, w, h, fill, radius=0, bw=0, border="#000000", shadow=False):
    return dict(type="shape", x=x, y=y, kind=kind, w=w, h=h, fill=fill, border=border, bw=bw, radius=radius,
                corners=[True] * 4, shadow=shadow, dash="solid", bpos="center", bjoin="miter")


def T_grid(x, y, w, h, rows=1, cols=1, gap=5, radius=0, fill="#c9ced6", layout=None):
    return dict(type="grid", x=x, y=y, rows=rows, cols=cols, w=w, h=h, gap=gap, radius=radius, fill=fill, ids=[],
                cells=GRID_LAYOUTS[layout] if layout is not None else None)


def tpl_strip(W, H, n):
    return [T_grid(40, 330, n * W - 80, H - 660, 1, 5, 20, 26),
            T_text("YOUR STORY", 60, 90, 120, "#2a2a2a", True, "Georgia"),
            T_text("swipe  →", 66, 235, 40, "#8a7f70", False),
            T_text("@yourhandle", 66, H - 170, 40, "#2a2a2a", True)]


def tpl_pano(W, H, n):
    it = [T_grid(0, int(H * 0.16), n * W, int(H * 0.68), 1, 1, 0, 0, "#2c2f36"),
          T_text("PANORAMA", 60, 70, 100, "#ffffff", True, "Georgia")]
    it += [T_text(f"0{i + 1}", i * W + 60, H - 170, 70, "#ffffff", False, "Segoe UI Light") for i in range(n)]
    return it


def tpl_dump(W, H, n):
    it = []
    for i in range(n):
        it += [T_text("PHOTO DUMP", i * W + 50, 60, 54, "#222222", True),
               T_grid(i * W + 50, 170, W - 100, H - 340, 2, 2, 16, 22),
               T_text(f"{i + 1} / {n}", i * W + 50, H - 130, 40, "#888888", False)]
    return it


def tpl_quotes(W, H, n):
    qs = ["Your quote goes here.", "Say something worth saving.", "Short. Bold. Memorable.", "Make it yours."]
    it = []
    for i in range(n):
        it += [T_text("“", i * W + 70, 150, 300, "#ff7a59", True, "Georgia"),
               T_text(qs[i % len(qs)], i * W + 80, 480, 84, "#ffffff", True, "Georgia", False, W - 160),
               T_text("— Author name", i * W + 80, H - 230, 40, "#b9b6e6", False),
               T_text("swipe  →" if i < n - 1 else "follow for more", i * W + W - 330, H - 130, 34, "#8a87c9", False)]
    return it


def tpl_tips(W, H, n):
    it = [T_shape("rect", 70, 120, W - 140, 14, "#ff5078", 7),
          T_text("5 TIPS TO", 70, 220, 150, "#222222", True, "Segoe UI", False, W - 140),
          T_text("GROW FASTER", 70, 390, 150, "#ff5078", True, "Segoe UI", False, W - 140),
          T_text("swipe  →", 70, H - 170, 44, "#222222", False)]
    heads = ["Be consistent", "Tell a story", "Use great photos", "Engage daily"]
    for i in range(1, n):
        x = i * W
        it += [T_shape("ellipse", x + 80, 150, 210, 210, "#ff5078"),
               T_text(str(i), x + 80, 170, 150, "#ffffff", True, "Segoe UI", False, 210, "center"),
               T_text(heads[(i - 1) % 4], x + 80, 470, 100, "#222222", True, "Segoe UI", False, W - 160),
               T_text("A short sentence that explains this tip in plain words.", x + 80, 800, 52, "#555555", False,
                      "Segoe UI", False, W - 160, "left", 120)]
    return it


def tpl_product(W, H, n):
    it = [T_grid(80, 160, W - 160, 800, 1, 1, 0, 44),
          T_text("Product Name", 80, 1000, 72, "#2b2118", True, "Georgia"),
          T_text("A short line about this product.", 80, 1105, 40, "#7a6a58", False),
          T_shape("rect", W - 330, 1005, 250, 100, "#2b2118", 50),
          T_text("$49", W - 330, 1015, 64, "#ffffff", True, "Segoe UI", False, 250, "center")]
    if n > 1:
        it += [T_grid(W + 70, 180, W - 140, 520, 1, 2, 24, 30), T_grid(W + 70, 724, W - 140, 520, 1, 1, 24, 30),
               T_text("Why you'll love it", W + 70, H - 90, 40, "#2b2118", True)]
    if n > 2:
        it += [T_text("Ready to\nshop?", 2 * W + 90, 420, 150, "#2b2118", True, "Georgia"),
               T_shape("rect", 2 * W + 90, 900, W - 180, 130, "#2b2118", 65),
               T_text("SHOP NOW", 2 * W + 90, 925, 60, "#ffffff", True, "Segoe UI", False, W - 180, "center")]
    return it


def tpl_polaroid(W, H, n):
    it = []
    for i in range(n):
        x = i * W
        it += [T_shape("rect", x + 120, 170, W - 240, 1000, "#ffffff", 10, shadow=True),
               T_grid(x + 160, 210, W - 320, W - 320, 1, 1, 0, 4),
               T_text("Place, 2026", x + 160, 210 + W - 320 + 60, 70, "#333333", False, "Georgia", True, W - 320)]
    return it


def tpl_editorial(W, H, n):
    it = [T_shape("rect", 60, 120, W - 120, 5, "#111111"),
          T_text("The Edit", 60, 170, 190, "#111111", True, "Georgia"),
          T_text("Issue 01  —  Autumn", 66, 420, 40, "#777777", False),
          T_grid(60, 560, W - 120, H - 700, 1, 1, 0, 0)]
    if n > 1:
        it += [T_grid(W + 60, 120, W - 120, 640, 1, 1, 0, 0), T_grid(W + 60, 800, (W - 140) // 2, 420, 1, 1, 0, 0),
               T_grid(W + 80 + (W - 140) // 2, 800, (W - 140) // 2, 420, 1, 1, 0, 0)]
    if n > 2:
        it += [T_text("Thank you\nfor reading.", 2 * W + 70, 480, 130, "#111111", True, "Georgia", False, W - 140),
               T_shape("rect", 2 * W + 70, 900, 220, 5, "#111111")]
    return it


def tpl_beforeafter(W, H, n):
    return [T_grid(60, 220, n * W - 120, H - 440, 1, 2, 0, 0, "#2d2d33"),
            T_text("BEFORE", 100, 130, 60, "#ffffff", True), T_text("AFTER", W + 100, 130, 60, "#ffd166", True),
            T_text("swipe to compare  →", 100, H - 170, 38, "#aaaaaa", False)]


def tpl_mosaic(W, H, n):
    it = [T_grid(90, 125, W - 180, H - 250, 1, 1, 0, 40)]
    if n > 1:
        it += [T_grid(W + 90, 125, W - 180, 560, 1, 1, 0, 40), T_grid(W + 90, 725, W - 180, 500, 1, 1, 0, 40)]
    if n > 2:
        it += [T_grid(2 * W + 90, 125, W - 180, 900, 1, 1, 0, 40),
               T_text("memories", 2 * W + 90, 1090, 100, "#7a3b12", True, "Georgia", True)]
    it += [T_grid(W - 280, 860, 560, 400, 1, 1, 0, 40, "#b8c0cc")]       # straddles the cut between slide 1 and 2
    return it


def tpl_square(W, H, n):
    it = []
    for i in range(n):
        it += [T_grid(i * W + 60, 60, W - 120, H - 270, 1, 1, 0, 36),
               T_text("Caption goes here", i * W + 70, H - 170, 56, "#222222", True, "Segoe UI", False, W - 140)]
    return it


def tpl_gradient(W, H, n):
    it = [T_text("BIG\nIDEA", 90, 300, 330, "#ffffff", True, "Segoe UI", False, 0, "left", 90),
          T_text("swipe  →", 96, H - 190, 46, "#ffe8f0", False)]
    for i in range(1, n):
        it += [T_text(f"0{i}", i * W + 90, 160, 120, "#ffe8f0", True),
               T_text("Your point goes here, short and strong.", i * W + 90, 420, 96, "#ffffff", True, "Segoe UI", False, W - 180),
               T_grid(i * W + 90, 900, W - 180, 300, 1, 1, 0, 30, "#ffffff")]
    return it


def tpl_gridmix(W, H, n):
    order = [8, 3, 10, 12, 24, 5]
    it = []
    for i in range(n):
        it += [T_grid(i * W + 50, 150, W - 100, H - 330, layout=order[i % len(order)]),
               T_text(f"0{i + 1}", i * W + 56, H - 150, 70, "#1d1d1f", True, "Segoe UI"),
               T_text("swipe  →" if i < n - 1 else "thank you", i * W + W - 330, H - 135, 38, "#6b6b73", False)]
    return it


def tpl_wide_collage(W, H, n):
    return [T_grid(40, 150, n * W - 80, H - 330, layout=25),
            T_text("THE COLLECTION", 50, 50, 56, "#1d1d1f", True, "Georgia"),
            T_text("one picture, every slide  →", 56, H - 130, 38, "#6b6b73", False)]


def tpl_magazine(W, H, n):
    it = [T_text("STYLE\nEDIT", 60, 70, 210, "#ffffff", True, "Georgia", False, 0, "left", 85),
          T_grid(0, 0, W, H, 1, 1, 0, 0, "#40454f"),
          T_text("ISSUE 12  -  THE FEATURE ISSUE", 66, H - 150, 38, "#ffffff", True)]
    it = it[1:2] + it[0:1] + it[2:]
    for i in range(1, n):
        it += [T_grid(i * W + 50, 120, W - 100, H - 420, layout=[8, 10, 12][i % 3]),
               T_text("Feature story headline", i * W + 56, H - 270, 70, "#111111", True, "Georgia", False, W - 112),
               T_text("A short standfirst to introduce the piece.", i * W + 56, H - 130, 36, "#666666", False, "Segoe UI", False, W - 112)]
    return it


def tpl_travel(W, H, n):
    it = [T_grid(60, 160, W - 120, 760, layout=3),
          T_text("Bali, 2026", 60, 960, 130, "#23423a", True, "Georgia", True),
          T_text("Seven days, one backpack.", 66, 1130, 44, "#5b7a70", False)]
    for i in range(1, n):
        it += [T_text(f"DAY {i}", i * W + 60, 90, 54, "#23423a", True),
               T_grid(i * W + 60, 190, W - 120, 640, layout=[0, 4, 2][i % 3]),
               T_text("What happened today, in a sentence or two.", i * W + 60, 880, 50, "#23423a", False, "Segoe UI", False, W - 120, "left", 120)]
    return it


def tpl_recipe(W, H, n):
    it = [T_grid(60, 60, W - 120, 800, 1, 1, 0, 40),
          T_text("Creamy Garlic\nPasta", 60, 900, 110, "#3b2a1a", True, "Georgia", False, W - 120, "left", 95),
          T_text("20 min  -  serves 4  -  easy", 66, 1170, 42, "#9a6b3c", True)]
    if n > 1:
        it += [T_text("INGREDIENTS", W + 60, 100, 60, "#9a6b3c", True),
               T_text("- 300 g pasta\n- 4 garlic cloves\n- 200 ml cream\n- parmesan\n- salt and pepper", W + 60, 240, 62, "#3b2a1a", False,
                      "Segoe UI", False, W - 120, "left", 140)]
    for i in range(2, n):
        it += [T_shape("ellipse", i * W + 60, 120, 140, 140, "#9a6b3c"),
               T_text(str(i - 1), i * W + 60, 140, 90, "#ffffff", True, "Segoe UI", False, 140, "center"),
               T_text("Describe this step clearly in two short lines.", i * W + 60, 330, 66, "#3b2a1a", True, "Segoe UI", False, W - 120, "left", 120),
               T_grid(i * W + 60, 760, W - 120, 480, layout=1)]
    return it


def tpl_fitness(W, H, n):
    it = [T_text("30-DAY\nPLAN", 70, 160, 250, "#c6ff3d", True, "Segoe UI", False, 0, "left", 88),
          T_text("no gym needed", 76, 700, 56, "#ffffff", False),
          T_shape("rect", 70, 840, 330, 110, "#c6ff3d", 55),
          T_text("START", 70, 862, 56, "#111111", True, "Segoe UI", False, 330, "center")]
    for i in range(1, n):
        it += [T_text(f"WEEK {i}", i * W + 70, 110, 120, "#c6ff3d", True),
               T_grid(i * W + 70, 290, W - 140, 520, layout=[14, 7, 9][i % 3], fill="#2c2f36"),
               T_text("3 sets  -  12 reps  -  45 sec rest", i * W + 70, 870, 50, "#ffffff", False, "Segoe UI", False, W - 140),
               T_text("Warm up first. Form beats speed.", i * W + 70, 1020, 42, "#8d93a5", False, "Segoe UI", False, W - 140)]
    return it


def tpl_pitch(W, H, n):
    it = [T_shape("rect", 0, 0, 40, H, "#3b5bff"),
          T_text("Company\nName", 100, 220, 210, "#0f1a3a", True, "Segoe UI", False, 0, "left", 90),
          T_text("Pitch deck  -  2026", 106, 700, 48, "#5a6382", False),
          T_text("swipe  →", 106, H - 160, 40, "#3b5bff", True)]
    pts = [("The problem", "Say what hurts, for whom, and how much."), ("Our solution", "Explain it simply, in one sentence."),
           ("Traction", "Three numbers that prove it works."), ("The ask", "What you need and what it unlocks.")]
    for i in range(1, n):
        h, b = pts[(i - 1) % 4]
        it += [T_text(f"0{i}", i * W + 80, 110, 90, "#3b5bff", True),
               T_text(h, i * W + 80, 300, 110, "#0f1a3a", True, "Segoe UI", False, W - 160),
               T_text(b, i * W + 80, 560, 56, "#5a6382", False, "Segoe UI", False, W - 160, "left", 125),
               T_grid(i * W + 80, 900, W - 160, 300, layout=6)]
    return it


def tpl_lookbook(W, H, n):
    it = [T_grid(50, 140, n * W - 100, H - 300, layout=[7, 23, 6][n % 3]),
          T_text("LOOKBOOK / AW26", 50, 50, 54, "#111111", True, "Georgia")]
    it += [T_text(f"N°{i + 1}", i * W + 60, H - 130, 48, "#111111", False, "Georgia", True) for i in range(n)]
    return it


def tpl_event(W, H, n):
    it = [T_text("SAVE\nTHE DATE", 80, 200, 190, "#ffffff", True, "Segoe UI", False, 0, "left", 88),
          T_text("12 DEC  -  7 PM", 86, 620, 70, "#ffd166", True),
          T_text("The Rooftop, Makati", 86, 740, 46, "#ffe8f0", False),
          T_grid(80, 900, W - 160, 280, 1, 1, 0, 26, "#55ffffff")]
    for i in range(1, n):
        it += [T_text(["LINE-UP", "DETAILS", "RSVP"][(i - 1) % 3], i * W + 80, 120, 110, "#ffd166", True),
               T_text("Add the names, times and the little things guests need to know.", i * W + 80, 340, 60, "#ffffff", False,
                      "Segoe UI", False, W - 160, "left", 130),
               T_grid(i * W + 80, 860, W - 160, 340, layout=7, fill="#44ffffff")]
    return it


def tpl_testimonial(W, H, n):
    it = []
    for i in range(n):
        x = i * W
        it += [T_shape("rect", x + 70, 150, W - 140, H - 400, "#ffffff", 40, shadow=True),
               T_text("★★★★★", x + 110, 200, 70, "#ffb400", True, "Segoe UI", False, W - 220),
               T_text("\"This changed how I plan everything. Highly recommend!\"", x + 110, 340, 72, "#222222", True, "Georgia", False, W - 220, "left", 120),
               T_grid(x + 110, H - 420, 120, 120, 1, 1, 0, 60),
               T_text("Customer Name", x + 260, H - 395, 46, "#222222", True, "Segoe UI", False, W - 400),
               T_text("Title, Company", x + 260, H - 335, 36, "#777777", False, "Segoe UI", False, W - 400)]
    return it


TEMPLATES = [
    dict(name="Seamless Photo Strip", cat="Photo", pw=1080, ph=1350, n=3, bg="#f4f1ea", build=tpl_strip),
    dict(name="Panorama Split", cat="Photo", pw=1080, ph=1350, n=3, bg="#111111", build=tpl_pano),
    dict(name="Photo Dump 2x2", cat="Photo", pw=1080, ph=1350, n=4, bg="#ffffff", build=tpl_dump),
    dict(name="Travel Polaroids", cat="Photo", pw=1080, ph=1350, n=3, bg="#cfe3e8", build=tpl_polaroid),
    dict(name="Before & After", cat="Photo", pw=1080, ph=1350, n=2, bg="#101010", build=tpl_beforeafter),
    dict(name="Mosaic Collage", cat="Photo", pw=1080, ph=1350, n=3, bg="#ffe9d6", build=tpl_mosaic),
    dict(name="Square Photo Trio", cat="Photo", pw=1080, ph=1080, n=3, bg="#ffffff", build=tpl_square),
    dict(name="Quote Series", cat="Text", pw=1080, ph=1350, n=4, bg="#1d1b3a", build=tpl_quotes),
    dict(name="Tips & Steps", cat="Text", pw=1080, ph=1350, n=5, bg="#fff4e0", build=tpl_tips),
    dict(name="Bold Gradient", cat="Text", pw=1080, ph=1350, n=3, bg="#ff512f", bg2="#dd2476", build=tpl_gradient),
    dict(name="Product Showcase", cat="Product", pw=1080, ph=1350, n=3, bg="#efe7dc", build=tpl_product),
    dict(name="Minimal Editorial", cat="Product", pw=1080, ph=1350, n=3, bg="#fafafa", build=tpl_editorial),
    dict(name="Grid Mix Carousel", cat="Grid", pw=1080, ph=1350, n=5, bg="#f3f1ee", build=tpl_gridmix),
    dict(name="Wide Collage (seamless)", cat="Grid", pw=1080, ph=1350, n=3, bg="#ffffff", build=tpl_wide_collage),
    dict(name="Fashion Lookbook", cat="Grid", pw=1080, ph=1350, n=3, bg="#f4f4f4", build=tpl_lookbook),
    dict(name="Magazine Cover Story", cat="Lifestyle", pw=1080, ph=1350, n=3, bg="#f7f3ec", build=tpl_magazine),
    dict(name="Travel Diary", cat="Lifestyle", pw=1080, ph=1350, n=4, bg="#eaf3ee", build=tpl_travel),
    dict(name="Recipe Steps", cat="Lifestyle", pw=1080, ph=1350, n=4, bg="#fff7ec", build=tpl_recipe),
    dict(name="30-Day Fitness Plan", cat="Lifestyle", pw=1080, ph=1350, n=4, bg="#14161b", build=tpl_fitness),
    dict(name="Startup Pitch", cat="Business", pw=1080, ph=1350, n=5, bg="#f6f8ff", build=tpl_pitch),
    dict(name="Event Announcement", cat="Business", pw=1080, ph=1350, n=3, bg="#6a2c91", bg2="#ec4899", build=tpl_event),
    dict(name="Testimonial Cards", cat="Business", pw=1080, ph=1350, n=3, bg="#e8ecff", build=tpl_testimonial),
]


def template_snapshot(t):
    items = t["build"](t["pw"], t["ph"], t["n"])
    for z, d in enumerate(items):
        d.update(scale=1.0, rot=0.0, op=1.0, z=z, locked=False, fx=False, fy=False)
    return {"pw": t["pw"], "ph": t["ph"], "n": t["n"], "rows": 1, "bg": t["bg"], "bg2": t.get("bg2", "#7b5cff"),
            "bg_mode": "gradient" if t.get("bg2") else "solid", "bg_angle": 35, "bg_tex": None, "items": items}


class TemplateDelegate(QStyledItemDelegate):
    """Template picker card: the template picture, its name and how many slides / what size."""
    def sizeHint(self, option, index):
        return QSize(440, 212)

    def paint(self, p, option, index):
        pal = QApplication.palette()
        acc, txt, mut = pal.color(QPalette.Highlight), pal.color(QPalette.WindowText), pal.color(QPalette.PlaceholderText)
        r = QRectF(option.rect).adjusted(5, 5, -5, -5)
        sel, hov = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
        p.save()
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        bg = QColor(acc)
        bg.setAlpha(36)
        p.setPen(QPen(acc if sel else QColor(128, 134, 150, 130 if hov else 60), 2 if sel else 1))
        p.setBrush(bg if sel else pal.color(QPalette.Base))
        p.drawRoundedRect(r, 14, 14)
        ic = index.data(Qt.DecorationRole)
        name, _, meta = (index.data(Qt.DisplayRole) or "").partition("\n")
        area = QRectF(r.left() + 10, r.top() + 10, r.width() - 20, 140)
        if isinstance(ic, QIcon):
            pm = ic.pixmap(QSize(860, 340))
            sc = pm.scaled(int(area.width() * 2), int(area.height() * 2), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            w, h = sc.width() / 2, sc.height() / 2
            tgt = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
            clip = QPainterPath()
            clip.addRoundedRect(tgt, 8, 8)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(tgt, sc, QRectF(sc.rect()))
            p.restore()
        f = QFont(option.font)
        f.setPixelSize(13)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(txt)
        p.drawText(QRectF(r.left() + 14, r.top() + 158, r.width() - 28, 20), Qt.AlignLeft | Qt.AlignVCenter, name)
        f.setPixelSize(11)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(mut)
        p.drawText(QRectF(r.left() + 14, r.top() + 177, r.width() - 28, 16), Qt.AlignLeft | Qt.AlignVCenter, meta)
        p.restore()


class TemplatesDialog(QDialog):
    """Ready-made carousel layouts (grids, text, product...). Pick one, then fill the grids with your photos."""
    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main, self.chosen = main, None
        self.setWindowTitle("Carousel templates")
        self.setFixedWidth(960)
        self.resize(960, 700)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        tl_ = QLabel("Templates")
        tl_.setObjectName("h2")
        top.addWidget(tl_)
        top.addSpacing(14)
        top.addWidget(QLabel("Category"))
        self.cat = QComboBox()
        self.cat.addItems(["All"] + list(dict.fromkeys(t["cat"] for t in TEMPLATES)))
        self.cat.currentTextChanged.connect(self.fill)
        top.addWidget(self.cat)
        top.addStretch()
        lay.addLayout(top)
        self.lst = QListWidget()
        self.lst.setViewMode(QListWidget.IconMode)
        self.lst.setIconSize(QSize(430, 170))
        self.lst.setSpacing(4)
        self.lst.setItemDelegate(TemplateDelegate(self.lst))
        self.lst.setMouseTracking(True)
        self.lst.setMovement(QListWidget.Static)
        self.lst.setResizeMode(QListWidget.Adjust)
        self.lst.setWordWrap(True)
        self.lst.itemDoubleClicked.connect(lambda *_: self.use())
        lay.addWidget(self.lst, 1)
        lay.addWidget(QLabel("Photo frames start empty: select the grid, then press Fill cells in the tool bar to add your photos."))
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        b = bb.addButton("Use Template", QDialogButtonBox.AcceptRole)
        b.setObjectName("primary")
        b.setMinimumWidth(150)
        b.clicked.connect(self.use)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.icons = {}
        self.fill()

    def fill(self, *_):
        self.lst.clear()
        cat = self.cat.currentText()
        for t in TEMPLATES:
            if cat != "All" and t["cat"] != cat:
                continue
            if t["name"] not in self.icons:
                self.icons[t["name"]] = QIcon(self.main.template_pixmap(t))
            li = QListWidgetItem(self.icons[t["name"]], f"{t['name']}\n{t['n']} slides  -  {t['pw']} x {t['ph']}")
            li.setData(Qt.UserRole, t["name"])
            li.setSizeHint(QSize(440, 212))
            self.lst.addItem(li)
        if self.lst.count():
            self.lst.setCurrentRow(0)

    def use(self):
        li = self.lst.currentItem()
        if li:
            self.chosen = next(t for t in TEMPLATES if t["name"] == li.data(Qt.UserRole))
            self.accept()


class PreviewWindow(QWidget):
    """Full-screen preview: two neighbouring slides side by side. Navigation glides smoothly (the carousel is one
    continuous strip); drag to scroll, arrow keys / click / wheel to step, Esc leaves."""
    def __init__(self, main):
        super().__init__(None, Qt.Window)
        self.m, self.sc = main, main.scene
        self.setWindowTitle("Full screen preview")
        sc = self.sc
        self.pages, self.labels = [], []
        for r in range(sc.rows):
            if sc.n == 1:
                self.pages.append(QRectF(0, r * sc.ph, sc.pw, sc.ph))
                self.labels.append(f"Slide {r + 1}")
            else:
                for c in range(sc.n - 1):
                    self.pages.append(QRectF(c * sc.pw, r * sc.ph, 2 * sc.pw, sc.ph))
                    k = r * sc.n + c + 1
                    self.labels.append(f"Slides {k} - {k + 1}")
        vc = main.view_center()
        self.i = next((k for k, r in enumerate(self.pages) if r.contains(vc)), 0)
        self.cur = QPointF(self.pages[self.i].topLeft())       # top-left of the visible window, in scene pixels
        self.size = self.pages[0].size()
        self.k, self.press, self.dragging, self.cur0 = 1.0, None, False, QPointF()
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(420)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.anim.valueChanged.connect(self.on_anim)
        self.saved_sel = list(sc.selectedItems())
        self.saved_guides = sc.show_guides
        sc.clearSelection()
        sc.exporting = True                      # hides guides / handles while previewing
        sc.live_preview = True                   # videos keep drawing their cheap live frames (not the full-detail export path)
        self.show_hint = True
        self.hint_timer = QTimer(self)
        self.hint_timer.setSingleShot(True)
        self.hint_timer.timeout.connect(self.hide_hint)
        self.hint_timer.start(3500)
        self.has_video = HAS_VIDEO and any(isinstance(i, VideoItem) for i in sc.items())
        self.last_draw = 0.0
        if self.has_video:                       # repaint when a video frame arrives (not on a blind timer) ...
            sc.changed.connect(self.on_scene_changed)
            main.view.setUpdatesEnabled(False)   # ... and stop the hidden editor view from drawing the same frames
        self.moving = False

    def on_scene_changed(self, _rects=None):
        now = time.monotonic()
        if now - self.last_draw >= 0.03 and not self.anim.state() == QVariantAnimation.Running:
            self.update()

    def on_anim(self, v):
        self.cur = QPointF(v)
        self.update()

    def hide_hint(self):
        self.show_hint = False
        self.update()

    def go_to(self, i):
        self.i = min(max(i, 0), len(self.pages) - 1)
        self.anim.stop()
        self.anim.setStartValue(QPointF(self.cur))
        self.anim.setEndValue(QPointF(self.pages[self.i].topLeft()))
        self.anim.start()
        self.show_hint = True
        self.hint_timer.start(2500)
        self.update()

    def go(self, d):
        self.go_to(self.i + d)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        r = QRectF(self.cur, self.size)
        self.k = min(self.width() / r.width(), self.height() / r.height())
        tw, th = r.width() * self.k, r.height() * self.k
        target = QRectF((self.width() - tw) / 2, (self.height() - th) / 2, tw, th)
        self.last_draw = time.monotonic()
        moving = self.anim.state() == QVariantAnimation.Running or self.dragging
        if moving and self.has_video:            # gliding between slides: cheaper drawing, full quality again at rest
            p.setRenderHints(QPainter.TextAntialiasing)
        else:
            p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        p.setClipRect(target)                    # nothing may spill into the black bars around the slides
        self.sc.render(p, target, r, Qt.KeepAspectRatio)
        if self.show_hint:
            txt = f"{self.labels[self.i]}   of   {self.sc.n * self.sc.rows}      ← → navigate      Esc exit"
            f = p.font()
            f.setPointSize(13)
            p.setFont(f)
            tr = p.fontMetrics().boundingRect(txt).adjusted(-22, -10, 22, 10)
            tr.moveCenter(QPointF(self.width() / 2, self.height() - 46).toPoint())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(tr, 18, 18)
            p.setPen(QColor(255, 255, 255))
            p.drawText(tr, Qt.AlignCenter, txt)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
        elif k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown):
            self.go(1)
        elif k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Backspace):
            self.go(-1)
        elif k == Qt.Key_Home:
            self.go_to(0)
        elif k == Qt.Key_End:
            self.go_to(len(self.pages) - 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.go(-1)
            return
        self.press, self.dragging, self.cur0 = e.position(), False, QPointF(self.cur)

    def mouseMoveEvent(self, e):
        if self.press is None or not (e.buttons() & Qt.LeftButton):
            return
        dx = e.position().x() - self.press.x()
        if not self.dragging and abs(dx) > 8:
            self.dragging = True
            self.anim.stop()
        if self.dragging:                        # drag to scroll the strip live
            row_y = self.pages[self.i].top()
            xs = [pg.left() for pg in self.pages if abs(pg.top() - row_y) < 1]
            self.cur = QPointF(min(max(self.cur0.x() - dx / self.k, min(xs)), max(xs)), self.cur0.y())
            self.update()

    def mouseReleaseEvent(self, e):
        if self.press is None:
            return
        if self.dragging:
            moved = self.cur.x() - self.cur0.x()
            thr = 0.15 * self.sc.pw
            self.go_to(self.i + (1 if moved > thr else -1 if moved < -thr else 0))
        else:
            self.go(1)
        self.press, self.dragging = None, False

    def wheelEvent(self, e):
        self.go(-1 if e.angleDelta().y() > 0 else 1)

    def closeEvent(self, e):
        self.anim.stop()
        if self.has_video:
            try:
                self.sc.changed.disconnect(self.on_scene_changed)
            except (RuntimeError, TypeError):
                pass
            self.m.view.setUpdatesEnabled(True)
        self.sc.exporting = False
        self.sc.live_preview = False
        self.sc.show_guides = self.saved_guides
        for it in self.saved_sel:
            try:
                it.setSelected(True)
            except RuntimeError:
                pass
        self.sc.update()
        self.m.preview = None
        e.accept()


# ---------------------------------------------------------------- start screen
APP_NAME = "Aero"


# ---------------------------------------------------------------- export (quality first)
EXPORT_FORMATS = [("PNG  (lossless)", "png"), ("JPEG  (maximum quality)", "jpg"), ("JFIF  (maximum quality)", "jfif"),
                  ("TIFF  (lossless)", "tiff"), ("WebP  (lossless)", "webp"), ("HEIC  (maximum quality)", "heic"),
                  ("HEIF  (maximum quality)", "heif"), ("BMP  (uncompressed)", "bmp")]


def qimage_to_pil(img):
    from PIL import Image
    im = img.convertToFormat(QImage.Format_RGB888)
    return Image.frombuffer("RGB", (im.width(), im.height()), bytes(im.constBits()), "raw", "RGB", im.bytesPerLine(), 1)


def save_image_hq(img, base, fmt):
    """Save without any avoidable loss: PNG / TIFF / WebP lossless, JPEG at quality 100 with full colour resolution,
    HEIC / HEIF lossless where the encoder allows. Returns an error text or None."""
    path = Path(str(base) + "." + fmt)
    try:
        if fmt in ("png", "bmp", "tiff") and True:
            qfmt = {"png": "PNG", "bmp": "BMP", "tiff": "TIFF"}[fmt]
            if img.save(str(path), qfmt):
                return None
            if fmt != "tiff":
                return f"Could not write {path.name}"
        try:
            pil = qimage_to_pil(img)
        except ImportError:
            pil = None
        if fmt in ("jpg", "jfif"):
            if pil is not None:
                pil.save(str(path), "JPEG", quality=100, subsampling=0, optimize=True)
                return None
            return None if img.save(str(path), "JPG", 100) else f"Could not write {path.name}"
        if fmt == "tiff":
            if pil is None:
                return "TIFF needs Pillow:  pip install pillow"
            pil.save(str(path), "TIFF", compression="tiff_lzw")          # lossless
            return None
        if fmt == "webp":
            if pil is not None:
                pil.save(str(path), "WEBP", lossless=True, quality=100, method=4)
                return None
            return None if img.save(str(path), "WEBP", 100) else f"Could not write {path.name}"
        if fmt in ("heic", "heif"):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                return ("HEIC / HEIF export needs two small packages:\n\n    pip install pillow pillow-heif\n\n"
                        "Nothing was exported. Pick PNG or TIFF (lossless) to export now.")
            try:
                pil.save(str(path), "HEIF", quality=-1)                # -1 = lossless
            except Exception:
                pil.save(str(path), "HEIF", quality=100)
            return None
    except Exception as ex:
        return f"Export failed: {ex}"
    return f"Unknown format {fmt}"


FFMPEG = None


def find_ffmpeg():
    """ffmpeg executable: the one bundled with imageio-ffmpeg, else one on PATH."""
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    return shutil.which("ffmpeg")


def probe_audio(ff, path):
    """'aac' / other codec name of the first audio stream, or '' if the video has no sound."""
    try:
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=30, **kw)
        for line in (r.stderr or "").splitlines():
            if "Audio:" in line:
                return line.split("Audio:")[1].strip().split(" ")[0].strip(",").lower()
    except Exception:
        pass
    return ""


def fps_str(fps):
    for a, b in ((23.976, "24000/1001"), (29.97, "30000/1001"), (47.952, "48000/1001"), (59.94, "60000/1001")):
        if abs(fps - a) < 0.01:
            return b
    return f"{fps:.3f}"


def video_frame_image(cv2, fr, crop, adj, tw, th):
    """Original BGR frame -> crop -> resized to the export size -> Edit Image filters -> QImage. Safe to run on worker threads.
    When the picture has fewer real pixels than the export size (for example a 1080p clip saved at 2x), the filters work on
    the real pixels and the result is enlarged afterwards: the filters cost 2 to 4 times less and the image is the same."""
    H, W = fr.shape[:2]
    if crop:
        x0, y0 = int(crop[0] * W), int(crop[1] * H)
        fr = fr[y0:max(y0 + 1, int(crop[3] * H)), x0:max(x0 + 1, int(crop[2] * W))]
    ww, wh = tw, th
    if adj:
        k = min(1.0, fr.shape[1] / tw, fr.shape[0] / th)
        if k < 0.8:
            ww, wh = max(16, int(tw * k)), max(16, int(th * k))
    interp = cv2.INTER_AREA if fr.shape[1] > ww else cv2.INTER_LANCZOS4
    fr = cv2.resize(fr, (ww, wh), interpolation=interp)
    rgb = np.ascontiguousarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
    if adj:
        rgb = (np.clip(adjust_rgb(rgb.astype(np.float32) / 255.0, adj), 0, 1) * 255 + 0.5).astype(np.uint8)
        if (ww, wh) != (tw, th):
            rgb = cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_LANCZOS4)
        rgb = np.ascontiguousarray(rgb)
    return QImage(rgb.data, tw, th, tw * 3, QImage.Format_RGB888).copy()


def video_frame_pixmap(cv2, fr, crop, adj, tw, th):
    return QPixmap.fromImage(video_frame_image(cv2, fr, crop, adj, tw, th))


# ---------------------------------------------------------------- export: resource limits, memory estimate, progress
def available_ram_mb():
    """Free memory (MB) that new allocations can use."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMSTAT()
            st.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullAvailPhys / 1048576.0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return None


def est_export_mb(fmt, W, H, video=False):
    """Rough peak memory (MB) for one slide at W x H. Deliberately on the high side."""
    px = W * H
    per = {"png": 12, "bmp": 10, "tiff": 16, "webp": 30, "jpg": 14, "jfif": 14, "heic": 90, "heif": 90}.get(fmt, 20)
    return px * per / 1048576.0 + 300


VIDEO_MAX_SCALE = 2      # video slides are never exported larger than 2x: bigger needs many GB for the encoder and no phone plays it


def video_scale(scale):
    return min(scale, VIDEO_MAX_SCALE)


def est_video_mb(W, H):
    """Peak memory (MB) of the video encoder + frame buffers for one video slide at W x H (measured, with a safety margin)."""
    return W * H * 140 / 1048576.0 + 500


def video_workers(limits, sizes, has_filters):
    """How many frames may be filtered at the same time: most of the allowed threads (one is kept for drawing, one for the
    encoder), but never more than the memory budget allows (one frame in the filter needs ~100 bytes per pixel)."""
    if not has_filters:
        return 1
    th = limits.threads or 2
    n = max(1, th - 2)
    per = max(w * h for w, h in sizes) * 100 / 1048576.0
    budget = 1800.0
    av = available_ram_mb()
    if av:
        budget = min(budget, av * 0.25)
    return int(max(1, min(n, 8, budget // max(per, 1))))


_JOB = {"h": None}


def _win_cpu_cap(percent):
    """Windows: put this process (and the encoders it starts) in a job whose CPU use is capped at `percent` of the whole PC.
    A hard cap works even when the per-core restriction is ignored. Returns True when it took effect."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.AssignProcessToJobObject.restype = wintypes.BOOL

    class RATE(ctypes.Structure):
        _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]
    first = _JOB["h"] is None
    if first:
        _JOB["h"] = k.CreateJobObjectW(None, None)
        if not _JOB["h"]:
            return False
    info = RATE(0x1 | 0x4, int(max(5, min(100, percent)) * 100))          # ENABLE | HARD_CAP, rate in 1/100 percent
    if not k.SetInformationJobObject(_JOB["h"], 15, ctypes.byref(info), ctypes.sizeof(info)):
        return False
    if first and not k.AssignProcessToJobObject(_JOB["h"], k.GetCurrentProcess()):
        return False
    return True


class ExportLimits:
    """While exporting, keep the PC cool and usable: lower priority, fewer cores and a hard ceiling on CPU use.
    mode: 'balanced' (about half, recommended), 'gentle' (2 cores), 'fast' (everything)."""
    def __init__(self, mode="balanced"):
        ncpu = os.cpu_count() or 2
        self.mode, self.low_priority = mode, mode != "fast"
        self.ncpu = ncpu
        self.threads = self.want(ncpu)
        self.saved = None
        self.status = ""
        self.cv_threads = None

    def want(self, n):
        return n if self.mode == "fast" else (min(2, n) if self.mode == "gentle" else max(1, n // 2))

    def pick(self, cpus):
        n = len(cpus)
        want = self.want(n)
        if want >= n:
            return list(cpus)
        step = max(1, n // want)          # every other logical CPU = one thread per physical core on SMT chips
        return list(cpus)[::step][:want]

    def __enter__(self):
        notes = []
        try:
            if cv2 is not None:
                self.cv_threads = cv2.getNumThreads()
                cv2.setNumThreads(max(1, self.threads))
        except Exception:
            pass
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                k = ctypes.WinDLL("kernel32", use_last_error=True)
                k.GetCurrentProcess.restype = wintypes.HANDLE
                k.GetPriorityClass.argtypes = [wintypes.HANDLE]
                k.GetPriorityClass.restype = wintypes.DWORD
                k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                k.SetPriorityClass.restype = wintypes.BOOL
                k.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
                k.GetProcessAffinityMask.restype = wintypes.BOOL
                k.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
                k.SetProcessAffinityMask.restype = wintypes.BOOL
                h = k.GetCurrentProcess()
                pm, sm = ctypes.c_size_t(), ctypes.c_size_t()
                if k.GetProcessAffinityMask(h, ctypes.byref(pm), ctypes.byref(sm)):
                    cpus = [b for b in range(64) if pm.value >> b & 1]
                    keep = self.pick(cpus)
                    self.saved = (k.GetPriorityClass(h), pm.value)
                    if self.low_priority:
                        notes.append("lower priority" if k.SetPriorityClass(h, 0x4000) else "")
                    if len(keep) < len(cpus):
                        if k.SetProcessAffinityMask(h, sum(1 << b for b in keep)):
                            notes.append(f"{len(keep)} of {len(cpus)} threads")
                    self.threads = len(keep)
                if self.mode != "fast":
                    pct = 100.0 * self.threads / max(1, self.ncpu)
                    try:
                        if _win_cpu_cap(pct):
                            notes.append(f"CPU capped at {int(round(pct))}%")
                            self.capped = True
                    except Exception:
                        pass
            elif hasattr(os, "sched_getaffinity"):
                cpus = sorted(os.sched_getaffinity(0))
                keep = self.pick(cpus)
                self.saved = (None, set(cpus))
                os.sched_setaffinity(0, set(keep))
                self.threads = len(keep)
                notes.append(f"{len(keep)} of {len(cpus)} threads")
        except Exception:
            pass
        self.status = ", ".join(n for n in notes if n)
        return self

    capped = False

    def __exit__(self, *a):
        try:
            if self.cv_threads is not None and cv2 is not None:
                cv2.setNumThreads(self.cv_threads)
        except Exception:
            pass
        try:
            if self.capped and sys.platform == "win32":
                _win_cpu_cap(100)                              # lift the ceiling again
        except Exception:
            pass
        try:
            if self.saved is None:
                return
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                k = ctypes.WinDLL("kernel32", use_last_error=True)
                k.GetCurrentProcess.restype = wintypes.HANDLE
                k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                k.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
                h = k.GetCurrentProcess()
                k.SetPriorityClass(h, self.saved[0] or 0x20)
                k.SetProcessAffinityMask(h, self.saved[1])
            elif hasattr(os, "sched_setaffinity"):
                os.sched_setaffinity(0, self.saved[1])
        except Exception:
            pass


class ExportProgress:
    """One progress bar for the whole export: overall percentage, what is happening now, time left. Cancel supported."""
    def __init__(self, parent, total_units):
        self.total, self.done, self.t0 = max(1, total_units), 0.0, time.monotonic()
        self.dlg = QProgressDialog("Starting export...", "Cancel", 0, 1000, parent)
        self.dlg.setWindowTitle("Exporting")
        self.dlg.setWindowModality(Qt.WindowModal)
        self.dlg.setMinimumDuration(0)
        self.dlg.setAutoClose(False)
        self.dlg.setAutoReset(False)
        self.dlg.setMinimumWidth(440)
        self.dlg.setValue(0)
        QApplication.processEvents()

    def update(self, units, text):
        self.done = min(units, self.total)
        f = self.done / self.total
        el = time.monotonic() - self.t0
        eta = f"   -   about {self.fmt_t(el * (1 - f) / f)} left" if f > 0.04 and el > 3 else ""
        self.dlg.setLabelText(f"{text}\n{int(f * 100)}%{eta}")
        self.dlg.setValue(int(f * 1000))
        QApplication.processEvents()

    @staticmethod
    def fmt_t(sec):
        sec = int(sec)
        return f"{sec // 60} min {sec % 60:02d} s" if sec >= 60 else f"{sec} s"

    def canceled(self):
        QApplication.processEvents()
        return self.dlg.wasCanceled()

    def close(self):
        self.dlg.close()


def encoder_cmd(ff, W, H, fs, aud, out, level, threads=0):
    """ffmpeg command line. level 0 = best (near-lossless H.264, original audio copied), 1 = plain H.264 (maximum compatibility),
    2 = MPEG-4 part 2 (only if H.264 is missing from this ffmpeg)."""
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-video_size", f"{W}x{H}", "-framerate", fs, "-i", "-"]
    for i in aud:
        cmd += ["-ss", f"{i['a'] / i['fps']:.4f}", "-t", f"{(i['b'] - i['a']) / i['fps']:.4f}", "-i", i["v"].path]
    if len(aud) > 1:
        mix = "".join(f"[{n + 1}:a]" for n in range(len(aud))) + f"amix=inputs={len(aud)}:duration=longest[a]"
        cmd += ["-filter_complex", mix, "-map", "0:v:0", "-map", "[a]", "-c:a", "aac", "-b:a", "320k"]
    elif len(aud) == 1:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c:a", "copy"] if (level <= 0 and aud[0]["audio"] == "aac") else ["-c:a", "aac", "-b:a", "320k"]
    else:
        cmd += ["-map", "0:v:0"]
    x264 = "rc-lookahead=10:bframes=2:ref=3:sync-lookahead=0:frame-threads=%d" % min(max(threads, 1), 3)   # small look-ahead: far less memory
    if level == -1:          # NVIDIA graphics card encoder: very fast, hardly any CPU, high quality (not mathematically near-lossless)
        cmd += ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "12", "-b:v", "0", "-profile:v", "high",
                "-r", fs, "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart"]
    elif level == 0:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-x264-params", x264, "-crf", "10", "-profile:v", "high", "-r", fs,
                "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart"]
    elif level == 1:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-x264-params", x264, "-crf", "10", "-pix_fmt", "yuv420p", "-r", fs, "-movflags", "+faststart"]
    else:
        cmd += ["-c:v", "mpeg4", "-q:v", "1", "-pix_fmt", "yuv420p", "-r", fs]
    if threads:
        cmd += ["-threads", str(threads)]
    return cmd + [str(out)]


def run_hidden(cmd, low_priority=False, **kw):
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000 | (0x4000 if low_priority else 0)      # no console window / below-normal priority
    return subprocess.Popen(cmd, **kw)


def preflight_encoder(ff, aud, fs, folder, gpu=False, size=(1080, 1350)):
    """Try a 3-frame test encode with the real settings; returns (level, log). Picks the best level that works.
    gpu=True tries the graphics-card encoder first (tested at the real video size)."""
    log = []
    test = Path(folder) / ".aero_encoder_test.mp4"
    for level in ((-1, 0, 1, 2) if gpu else (0, 1, 2)):
        ef = tempfile.TemporaryFile()
        tw, th = (size[0], size[1]) if level == -1 else (128, 128)
        try:
            pc = run_hidden(encoder_cmd(ff, tw, th, fs, aud, test, level), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=ef)
            try:
                pc.stdin.write(bytes(tw * th * 4 * 3))
                pc.stdin.close()
            except OSError:
                pass
            rc = pc.wait(timeout=60)
            ef.seek(0)
            msg = ef.read().decode(errors="replace").strip()
            if rc == 0 and test.exists():
                return level, log
            log.append(f"[level {level}] exit code {rc}: {msg[-400:]}")
        except Exception as e:
            log.append(f"[level {level}] {e}")
        finally:
            ef.close()
            try:
                test.unlink()
            except OSError:
                pass
    return None, log


def slide_rect(sc, k):
    return QRectF((k % sc.n) * sc.pw, (k // sc.n) * sc.ph, sc.pw, sc.ph)


def video_slide_map(sc):
    """{slide index: [video layers that appear on it]}."""
    out = {}
    vids = [i for i in sc.items() if HAS_VIDEO and isinstance(i, VideoItem) and i.parentItem() is None and not i.data(8)]
    for k in range(sc.n * sc.rows):
        r = slide_rect(sc, k)
        on = [v for v in vids if v.sceneBoundingRect().intersected(r).width() > 0.5 and v.sceneBoundingRect().intersected(r).height() > 0.5]
        if on:
            out[k] = sorted(on, key=lambda v: v.zValue())
    return out


def need_video_tools(parent):
    """True when OpenCV, numpy and ffmpeg are all available (else tells the user)."""
    global FFMPEG
    FFMPEG = find_ffmpeg()
    if cv2 is None or np is None or FFMPEG is None:
        QMessageBox.warning(parent, "Export", "This project has videos, and exporting them needs these packages:\n\n"
                                              "pip install opencv-python numpy imageio-ffmpeg")
        return False
    return True


class TrimDialog(QDialog):
    """Keep only part of a video: pick the start and end; the canvas shows the frame while you drag."""
    def __init__(self, parent, v):
        super().__init__(parent)
        self.v, self.old = v, v.trim
        self.setWindowTitle("Trim video length")
        self.setFixedWidth(460)
        dur = max(int(v.duration()), 0)
        self.dur = dur
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(8)
        if dur <= 0:
            lay.addWidget(QLabel("The video is still loading. Close this and try again in a moment."))
            b = QPushButton("Close")
            b.clicked.connect(self.reject)
            lay.addWidget(b)
            self.sl = None
            return
        intro = QLabel("Keep only this part of the video. The rest is not used in the editor or in the exported slides.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        st, en = (v.trim or (0, dur))
        self.sl, self.sp = {}, {}
        for key, label, val in (("start", "Start (seconds)", st), ("end", "End (seconds)", en)):
            lay.addWidget(QLabel(label))
            row = QHBoxLayout()
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, dur)
            sl.setValue(int(val))
            sp = QDoubleSpinBox()
            sp.setDecimals(2)
            sp.setRange(0, dur / 1000.0)
            sp.setValue(val / 1000.0)
            sp.setSingleStep(0.1)
            sp.setFixedWidth(110)
            sp.setMinimumHeight(32)
            sp.setToolTip("Type a time, or use the arrows to change it by 0.1 s")
            sl.valueChanged.connect(lambda x, k=key: self.changed(k, x, True))
            sp.valueChanged.connect(lambda x, k=key: self.changed(k, int(round(x * 1000)), False))
            row.addWidget(sl, 1)
            row.addWidget(sp)
            lay.addLayout(row)
            self.sl[key], self.sp[key] = sl, sp
        self.info = QLabel("")
        self.info.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.info)
        row = QHBoxLayout()
        reset = QPushButton("Use whole video")
        reset.clicked.connect(self.whole)
        row.addWidget(reset)
        row.addStretch(1)
        ok = QPushButton("OK")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        v.pause()
        self.update_info()
        self.setFixedHeight(self.sizeHint().height())

    def changed(self, key, ms, from_slider):
        other = "end" if key == "start" else "start"
        if key == "start" and ms >= self.sl["end"].value() - 100:
            ms = max(0, self.sl["end"].value() - 100)
        if key == "end" and ms <= self.sl["start"].value() + 100:
            ms = min(self.dur, self.sl["start"].value() + 100)
        for w, val in ((self.sl[key], ms), (self.sp[key], ms / 1000.0)):
            w.blockSignals(True)
            w.setValue(val)
            w.blockSignals(False)
        self.v.seek(ms)                              # show that frame on the canvas
        self.update_info()

    def whole(self):
        for key, val in (("start", 0), ("end", self.dur)):
            self.sl[key].blockSignals(True); self.sp[key].blockSignals(True)
            self.sl[key].setValue(val); self.sp[key].setValue(val / 1000.0)
            self.sl[key].blockSignals(False); self.sp[key].blockSignals(False)
        self.update_info()

    def update_info(self):
        a, b = self.sl["start"].value(), self.sl["end"].value()
        self.info.setText(f"Kept length: {(b - a) / 1000.0:.2f} s  of  {self.dur / 1000.0:.2f} s")

    def result_trim(self):
        a, b = self.sl["start"].value(), self.sl["end"].value()
        return None if (a <= 0 and b >= self.dur) else (a, b)

    def exec(self):
        if self.sl is None:
            super().exec()
            return False
        return super().exec()


class ExportDialog(QDialog):
    """Export: format, resolution, folder, how hard the PC may work. Quality first - nothing is compressed to save space."""
    def __init__(self, parent, auto_scale, n_videos=0, video_slides=()):
        super().__init__(parent)
        self.n_videos, self.video_slides = n_videos, list(video_slides)
        self.setWindowTitle("Export")
        self.setFixedWidth(480)
        self.fmt, self.scale, self.folder, self.auto, self.perf, self.gpu = "png", 2, "", auto_scale, "balanced", False
        self.sc = parent.scene
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Format"))
        self.f = QComboBox()
        for label, _ in EXPORT_FORMATS:
            self.f.addItem(label)
        self.f.currentIndexChanged.connect(self.format_changed)
        lay.addWidget(self.f)
        lay.addWidget(QLabel("Resolution"))
        self.r = QComboBox()
        self.r.addItem("", 0)
        for k in (1, 2, 3, 4):
            self.r.addItem(f"{k}x", k)
        self.r.currentIndexChanged.connect(self.info)
        lay.addWidget(self.r)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.note)
        if n_videos:
            vs = ", ".join(str(k + 1) for k in self.video_slides)
            vn = QLabel(f"This project has {n_videos} video(s) on slide(s) {vs}. Those slides are exported as MP4 "
                        f"(near-lossless, original frame rate and sound); all other slides use the format above. "
                        f"Everything goes into the same folder, numbered in slide order.")
            vn.setWordWrap(True)
            vn.setStyleSheet("color: palette(mid);")
            lay.addWidget(vn)
        self.venc = None
        if n_videos:
            lay.addWidget(QLabel("Video encoder"))
            self.venc = QComboBox()
            self.venc.addItem("Best quality - processor (recommended)", False)
            self.venc.addItem("Much faster - graphics card (NVIDIA), if available", True)
            lay.addWidget(self.venc)
            hint = QLabel("The graphics-card encoder is very fast and keeps the processor free; the picture is still high quality "
                          "but the files are not as near-lossless. If your card cannot do it, Aero uses the processor automatically.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: palette(mid);")
            lay.addWidget(hint)
        lay.addWidget(QLabel("Computer load"))
        self.p = QComboBox()
        self.p.addItem("Balanced - about half of your CPU (recommended)", "balanced")
        self.p.addItem("Gentle - 2 cores, best for working while it exports", "gentle")
        self.p.addItem("Fast - all CPU cores", "fast")
        lay.addWidget(self.p)
        lay.addSpacing(4)
        lay.addWidget(QLabel("Save to"))
        row = QHBoxLayout()
        self.loc = QLineEdit(str(Path(parent.path).parent) if parent.path else default_projects_dir())
        row.addWidget(self.loc, 1)
        b = QPushButton("Choose...")
        b.clicked.connect(self.choose)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addSpacing(6)
        go = QPushButton("Export")
        go.setObjectName("primary")
        go.setDefault(True)
        go.clicked.connect(self.go)
        lay.addWidget(go)
        self.format_changed()
        self.setFixedHeight(self.sizeHint().height())

    def cur_fmt(self):
        return EXPORT_FORMATS[self.f.currentIndex()][1]

    def auto_for(self, fmt):
        """HEIC / HEIF at 4x is a 23-megapixel encode that needs many GB of memory: 'Best detail' stops at 2x for them
        ."""
        if fmt in ("heic", "heif"):
            return min(self.auto, 2)
        return self.auto

    def format_changed(self, *_):
        k = self.auto_for(self.cur_fmt())
        self.r.setItemText(0, f"Best detail (automatic: {k}x)")
        self.info()

    def info(self, *_):
        fmt = self.cur_fmt()
        k = self.r.currentData() or self.auto_for(fmt)
        W, H = int(self.sc.pw * k), int(self.sc.ph * k)
        mb = est_export_mb(fmt, W, H)
        txt = (f"Each slide is saved at {W} x {H} px. Text and shapes are drawn sharp at that size and photos keep "
               f"their full detail.")
        if self.n_videos:
            vk = video_scale(k)
            mb = max(mb, est_video_mb(int(self.sc.pw * vk), int(self.sc.ph * vk)))
            txt += (f"  Video slides are saved at {int(self.sc.pw * vk)} x {int(self.sc.ph * vk)} px "
                    f"({vk}x, the largest size that is safe for video).")
        txt += f"  Estimated memory: about {mb / 1024:.1f} GB."
        if fmt in ("heic", "heif") and k >= 3:
            txt += "  HEIC / HEIF at this size is slow and memory-hungry; 2x is recommended."
        self.note.setText(txt)

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, "Export to folder", self.loc.text())
        if d:
            self.loc.setText(d)

    def go(self):
        self.fmt = self.cur_fmt()
        self.scale = self.r.currentData() or self.auto_for(self.fmt)
        self.perf = self.p.currentData()
        self.gpu = bool(self.venc.currentData()) if self.venc is not None else False
        self.folder = self.loc.text().strip()
        try:
            Path(self.folder).mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            QMessageBox.warning(self, "Export", f"Cannot use that folder: {ex}")
            return
        self.accept()


# ---------------------------------------------------------------- settings / theme / system info
APP_VERSION = "1.0.0"
APP_BUILD = APP_VERSION
VERSION_LINES = [f"Aero version {APP_VERSION}",
                 "Created by Winserendipity",
                 "All Rights Reserved. 2026"]
VERSION_TEXT = VERSION_LINES[0]
LANGUAGES = ["English", "Filipino", "Espa\u00f1ol", "Fran\u00e7ais", "Deutsch", "Portugu\u00eas", "Italiano",
             "\u65e5\u672c\u8a9e", "\ud55c\uad6d\uc5b4", "\u4e2d\u6587 (\u7b80\u4f53)"]
DEFAULT_ACCENT = "#6c7bff"


def cfg():
    return QSettings("AeroPhotoEditor", "Editor")


ACCENT_PRESETS = [("Indigo", "#6c7bff"), ("Violet", "#a070ff"), ("Sky", "#3aa0ff"), ("Mint", "#2ed3a3"),
                  ("Coral", "#ff6b78"), ("Amber", "#ffb020"), ("Lime", "#c6f135")]
THEMES = {
    "Dark": dict(bg="#12141b", panel="#181b24", field="#1f232e", border="#262b38", border2="#363c4d", text="#eef0f6",
                 muted="#8c94a8", hover="#1f2430", press="#2a3040", canvas="#0d0f14", raised="#1f232e"),
    "Light": dict(bg="#eceef2", panel="#f7f7f9", field="#ffffff", border="#e1e3e9", border2="#cfd3dc", text="#171a21",
                  muted="#667085", hover="#eceef3", press="#e1e4ea", canvas="#fbfbfc", raised="#ffffff"),
}
PASTEBOARD = QColor("#0d0f14")          # area around the slides (follows the theme)
UI_DOT = QColor(255, 255, 255, 34)      # dot grid on the workspace
UI_LABEL = QColor("#8b93a3")            # slide names above the slides


def theme_tokens(theme=None, accent=None):
    c = cfg()
    theme = theme or c.value("theme", "Dark")
    accent = accent or c.value("accent", DEFAULT_ACCENT)
    t = dict(THEMES.get(theme, THEMES["Dark"]))
    ac = QColor(accent)
    if not ac.isValid():
        ac = QColor(DEFAULT_ACCENT)
    t["dark"] = theme != "Light"
    t["accent"] = ac.name()
    lin = lambda v: (v / 255.0) ** 2.2
    lum = 0.2126 * lin(ac.red()) + 0.7152 * lin(ac.green()) + 0.0722 * lin(ac.blue())
    t["accent_text"] = "#0d1103" if lum > 0.34 else "#ffffff"
    t["accent_soft"] = f"rgba({ac.red()}, {ac.green()}, {ac.blue()}, 0.18)"
    t["accent_hover"] = ac.lighter(112).name()
    h, sat, val, _ = ac.getHsv()
    t["accent2"] = QColor.fromHsv((max(h, 0) + 32) % 360, min(255, sat + 10), min(255, val), 255).name() if h >= 0 else ac.name()
    return t


def _chevron(path, color, up=False):
    pm = QPixmap(24, 24)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    y0, y1 = (14, 9) if up else (9, 14)
    p.drawPolyline([QPointF(7, y0), QPointF(12, y1), QPointF(17, y0)])
    p.end()
    pm.save(str(path), "PNG")


def _tick(path, color):
    pm = QPixmap(24, 24)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(6, 12.5), QPointF(10.5, 17), QPointF(18, 8)])
    p.end()
    pm.save(str(path), "PNG")


def draw_ui_icon(p, name, color, S):
    """One line icon on a 24 x 24 grid (drawn in code, so no image files and it follows the theme colour)."""
    u = S / 24.0
    col = QColor(color)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(col, 1.9 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    P = lambda x, y: QPointF(x * u, y * u)
    R = lambda x, y, w, h: QRectF(x * u, y * u, w * u, h * u)
    L = lambda x1, y1, x2, y2: p.drawLine(P(x1, y1), P(x2, y2))
    PL = lambda *pts: p.drawPolyline([P(x, y) for x, y in pts])
    soft = QColor(col)
    soft.setAlpha(70)
    if name == "image":
        p.drawRoundedRect(R(3.5, 4.5, 17, 15), 3 * u, 3 * u)
        p.drawEllipse(P(9, 10), 1.6 * u, 1.6 * u)
        PL((4, 17), (10, 12.5), (14, 15.5), (17, 13), (20, 16))
    elif name == "video":
        p.drawRoundedRect(R(3, 6, 13.5, 12), 3 * u, 3 * u)
        PL((16.5, 10.5), (21, 7.5), (21, 16.5), (16.5, 13.5))
    elif name in ("volume", "mute"):
        PL((4, 9.5), (8, 9.5), (12.5, 5.5), (12.5, 18.5), (8, 14.5), (4, 14.5), (4, 9.5))
        if name == "volume":
            PL((15.5, 9), (17, 12), (15.5, 15))
            PL((18, 6.5), (20.5, 12), (18, 17.5))
        else:
            L(16, 9.5, 21, 14.5)
            L(21, 9.5, 16, 14.5)
    elif name == "text":
        L(5, 6, 19, 6)
        L(12, 6, 12, 19)
        L(9, 19, 15, 19)
    elif name == "shape":
        p.drawRoundedRect(R(3.5, 10.5, 10, 10), 2 * u, 2 * u)
        p.drawEllipse(P(15, 9), 5.2 * u, 5.2 * u)
    elif name == "grid":
        for x, y, w, h in ((4, 4, 7, 9), (13, 4, 7, 5), (13, 11, 7, 9), (4, 15, 7, 5)):
            p.drawRoundedRect(R(x, y, w, h), 1.8 * u, 1.8 * u)
    elif name == "template":
        p.drawRoundedRect(R(3.5, 4, 17, 16), 3 * u, 3 * u)
        L(3.5, 9.5, 20.5, 9.5)
        L(10, 9.5, 10, 20)
    elif name == "crop":
        PL((7, 3), (7, 17), (21, 17))
        PL((3, 7), (17, 7), (17, 21))
    elif name == "replace":
        PL((4, 9), (19, 9))
        PL((15.5, 5.5), (19, 9), (15.5, 12.5))
        PL((20, 15), (5, 15))
        PL((8.5, 11.5), (5, 15), (8.5, 18.5))
    elif name == "adjust":
        for y, kx in ((7, 9), (12, 15.5), (17, 8)):
            L(4, y, 20, y)
            p.setBrush(QColor("#000000") if False else soft)
            p.drawEllipse(P(kx, y), 2.4 * u, 2.4 * u)
            p.setBrush(Qt.NoBrush)
    elif name == "canvas":
        PL((12, 4), (21, 9), (12, 14), (3, 9), (12, 4))
        PL((3, 13), (12, 18), (21, 13))
    elif name in ("undo", "redo"):
        x = (lambda v: v) if name == "undo" else (lambda v: 24 - v)
        PL((x(9), 5), (x(4), 10), (x(9), 15))
        path = QPainterPath(P(x(4), 10))
        path.lineTo(P(x(14), 10))
        path.quadTo(P(x(20), 10), P(x(20), 14.5))
        path.quadTo(P(x(20), 19), P(x(14), 19))
        path.lineTo(P(x(9), 19))
        p.drawPath(path)
    elif name == "play":
        p.drawPolygon(QPolygonF([P(8, 5.5), P(19, 12), P(8, 18.5)]))
    elif name == "export":
        PL((4, 15), (4, 20), (20, 20), (20, 15))
        L(12, 4, 12, 15)
        PL((7.5, 10.5), (12, 15), (16.5, 10.5))
    elif name in ("front", "back"):
        a, b = R(3.5, 3.5, 12, 12), R(8.5, 8.5, 12, 12)
        if name == "front":
            p.drawRoundedRect(a, 2.5 * u, 2.5 * u)
            p.setBrush(soft)
            p.drawRoundedRect(b, 2.5 * u, 2.5 * u)
        else:
            p.setBrush(soft)
            p.drawRoundedRect(a, 2.5 * u, 2.5 * u)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(b, 2.5 * u, 2.5 * u)
    elif name == "trash":
        L(4, 7, 20, 7)
        PL((9, 7), (9, 4), (15, 4), (15, 7))
        PL((6, 7), (7, 20), (17, 20), (18, 7))
        L(10, 11, 10, 16)
        L(14, 11, 14, 16)
    elif name == "duplicate":
        p.drawRoundedRect(R(8.5, 8.5, 12, 12), 2.5 * u, 2.5 * u)
        path = QPainterPath(P(15.5, 5.5))
        path.lineTo(P(6, 5.5))
        path.quadTo(P(3.5, 5.5), P(3.5, 8))
        path.lineTo(P(3.5, 17.5))
        p.drawPath(path)
    elif name == "guides":
        L(9, 3, 9, 21)
        L(15, 3, 15, 21)
        L(3, 9, 21, 9)
        L(3, 15, 21, 15)
    elif name == "snap":
        path = QPainterPath(P(6, 4))
        path.lineTo(P(6, 11))
        path.arcTo(R(6, 5, 12, 12), 180, 180)
        path.lineTo(P(18, 4))
        p.drawPath(path)
        L(6, 8, 10, 8)
        L(14, 8, 18, 8)
    elif name == "fit":
        PL((4, 9), (4, 4), (9, 4))
        PL((15, 4), (20, 4), (20, 9))
        PL((20, 15), (20, 20), (15, 20))
        PL((9, 20), (4, 20), (4, 15))
    elif name == "plus":
        L(12, 5, 12, 19)
        L(5, 12, 19, 12)
    elif name == "minus":
        L(5, 12, 19, 12)
    elif name == "folder":
        path = QPainterPath(P(3, 8))
        path.lineTo(P(3, 18)); path.quadTo(P(3, 20), P(5, 20)); path.lineTo(P(19, 20)); path.quadTo(P(21, 20), P(21, 18))
        path.lineTo(P(21, 9)); path.quadTo(P(21, 7), P(19, 7)); path.lineTo(P(11, 7)); path.lineTo(P(9, 4.5))
        path.lineTo(P(5, 4.5)); path.quadTo(P(3, 4.5), P(3, 6.5)); path.closeSubpath()
        p.drawPath(path)
    elif name == "settings":
        for y, kx in ((7, 15), (12, 8), (17, 16)):
            L(4, y, 20, y)
            p.setBrush(soft)
            p.drawEllipse(P(kx, y), 2.4 * u, 2.4 * u)
            p.setBrush(Qt.NoBrush)
    elif name == "tips":
        p.drawEllipse(P(12, 10), 6 * u, 6 * u)
        L(9.5, 19, 14.5, 19)
        L(10.5, 21.5, 13.5, 21.5)
        L(12, 7, 12, 10.5)
    elif name == "info":
        p.drawEllipse(P(12, 12), 8.5 * u, 8.5 * u)
        L(12, 11, 12, 16.5)
        L(12, 7.6, 12, 7.7)
    elif name == "layers":
        PL((12, 4), (21, 9), (12, 14), (3, 9), (12, 4))
        PL((3, 13), (12, 18), (21, 13))
    elif name == "home":
        PL((4, 11), (12, 4), (20, 11))
        PL((6, 10), (6, 20), (18, 20), (18, 10))
    elif name == "bold":
        L(8, 5, 8, 19)
        a = QPainterPath(P(8, 5)); a.lineTo(P(13, 5)); a.quadTo(P(17, 5), P(17, 8.5)); a.quadTo(P(17, 12), P(13, 12)); a.lineTo(P(8, 12))
        b = QPainterPath(P(8, 12)); b.lineTo(P(14, 12)); b.quadTo(P(18, 12), P(18, 15.5)); b.quadTo(P(18, 19), P(14, 19)); b.lineTo(P(8, 19))
        p.drawPath(a); p.drawPath(b)
    elif name == "italic":
        L(14, 5, 10, 19); L(11, 5, 17, 5); L(7, 19, 13, 19)
    elif name == "underline":
        u_ = QPainterPath(P(7, 4)); u_.lineTo(P(7, 11)); u_.arcTo(R(7, 6, 10, 10), 180, 180); u_.lineTo(P(17, 4))
        p.drawPath(u_); L(5, 20, 19, 20)
    elif name in ("alignl", "alignc", "alignr", "alignj"):
        spans = {"alignl": ((4, 20), (4, 14), (4, 20), (4, 14)), "alignc": ((4, 20), (7, 17), (4, 20), (7, 17)),
                 "alignr": ((4, 20), (10, 20), (4, 20), (10, 20)), "alignj": ((4, 20),) * 4}[name]
        for y, (x1, x2) in zip((6, 10.3, 14.6, 19), spans):
            L(x1, y, x2, y)
    elif name in ("eye", "eyeoff"):
        e_ = QPainterPath(P(2.5, 12)); e_.quadTo(P(12, 3.5), P(21.5, 12)); e_.quadTo(P(12, 20.5), P(2.5, 12))
        p.drawPath(e_); p.drawEllipse(P(12, 12), 3 * u, 3 * u)
        if name == "eyeoff":
            L(4.5, 20, 19.5, 4)
    elif name == "lock":
        p.drawRoundedRect(R(5, 11, 14, 9.5), 2.5 * u, 2.5 * u)
        k_ = QPainterPath(P(8, 11)); k_.lineTo(P(8, 8)); k_.arcTo(R(8, 4, 8, 8), 180, -180); k_.lineTo(P(16, 11))
        p.drawPath(k_)
    elif name == "search":
        p.drawEllipse(P(11, 11), 6 * u, 6 * u); L(15.5, 15.5, 20, 20)
    elif name == "chevd":
        PL((6, 9), (12, 15), (18, 9))
    elif name == "chevr":
        PL((9, 6), (15, 12), (9, 18))
    elif name == "chevl":
        PL((15, 6), (9, 12), (15, 18))
    elif name == "fliph":
        L(12, 3.5, 12, 20.5)
        p.drawPolygon(QPolygonF([P(4, 18), P(9.5, 7), P(9.5, 18)]))
        p.drawPolygon(QPolygonF([P(14.5, 18), P(14.5, 7), P(20, 18)]))
    elif name == "flipv":
        L(3.5, 12, 20.5, 12)
        p.drawPolygon(QPolygonF([P(18, 4), P(7, 9.5), P(18, 9.5)]))
        p.drawPolygon(QPolygonF([P(18, 14.5), P(7, 14.5), P(18, 20)]))
    elif name == "more":
        p.setBrush(col)
        for x in (6, 12, 18):
            p.drawEllipse(P(x, 12), 1.3 * u, 1.3 * u)
    elif name == "sun":
        p.drawEllipse(P(12, 12), 4 * u, 4 * u)
        for a_ in range(8):
            c_, s_ = math.cos(a_ * math.pi / 4), math.sin(a_ * math.pi / 4)
            L(12 + 7 * c_, 12 + 7 * s_, 12 + 9.5 * c_, 12 + 9.5 * s_)
    elif name == "move":
        L(12, 3.5, 12, 20.5); L(3.5, 12, 20.5, 12)
        PL((9, 6.5), (12, 3.5), (15, 6.5)); PL((9, 17.5), (12, 20.5), (15, 17.5))
        PL((6.5, 9), (3.5, 12), (6.5, 15)); PL((17.5, 9), (20.5, 12), (17.5, 15))
    else:
        p.drawRoundedRect(R(4, 4, 16, 16), 3 * u, 3 * u)


def ui_icon(name, normal=None, active=None, disabled=None, size=22):
    """QIcon for a toolbar button: normal colour, accent colour on hover / checked, faded when disabled."""
    t = theme_tokens()
    normal, active, disabled = normal or t["text"], active or t["accent"], disabled or t["muted"]
    S = size * 2
    ic = QIcon()
    for color, mode, state in ((normal, QIcon.Normal, QIcon.Off), (active, QIcon.Active, QIcon.Off), (active, QIcon.Normal, QIcon.On),
                               (active, QIcon.Active, QIcon.On), (disabled, QIcon.Disabled, QIcon.Off), (disabled, QIcon.Disabled, QIcon.On)):
        pm = QPixmap(S, S)
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        draw_ui_icon(pp, name, color, S)
        pp.end()
        ic.addPixmap(pm, mode, state)
    return ic


QSS = """
* { font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif; }
QMainWindow, QDialog { background: @bg@; }
QDialog { background: @panel@; }
QWidget { color: @text@; font-size: 13px; }
QToolTip { background: @panel@; color: @text@; border: 1px solid @border2@; padding: 5px 8px; }
QMenuBar { background: @bg@; padding: 6px 10px 2px 10px; spacing: 2px; border: none; }
QMenuBar::item { background: transparent; color: @muted@; padding: 5px 11px; border-radius: 7px; font-weight: 500; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: @hover@; color: @text@; }
QMenu { background: @panel@; border: 1px solid @border2@; padding: 6px; }
QMenu::item { padding: 7px 26px 7px 14px; border-radius: 6px; color: @text@; }
QMenu::item:selected { background: @press@; }
QMenu::item:disabled { color: @muted@; }
QMenu::separator { height: 1px; background: @border@; margin: 6px 8px; }
QToolBar { background: @bg@; border: none; spacing: 4px; padding: 4px 10px; }
QToolBar::separator { background: @border2@; width: 1px; margin: 6px 8px; }
QToolButton { background: transparent; color: @text@; border: none; border-radius: 9px; padding: 7px 12px; }
QToolButton:hover { background: @hover@; }
QToolButton:pressed { background: @press@; }
QToolButton:checked { background: @accent_soft@; color: @accent@; }
QToolBar QLabel { color: @muted@; }
QPushButton { background: @field@; color: @text@; border: 1px solid @border2@; border-radius: 10px; padding: 7px 16px; }
QPushButton:hover { background: @hover@; border-color: @muted@; }
QPushButton:pressed { background: @press@; }
QPushButton:disabled { color: @muted@; background: @bg@; border-color: @border@; }
QDialogButtonBox QPushButton:default, QPushButton#primary { background: @accent@; color: @accent_text@; border: 1px solid @accent@; font-weight: 700; }
QDialogButtonBox QPushButton:default:hover, QPushButton#primary:hover { background: @accent_hover@; border-color: @accent_hover@; }
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit { background: @field@; color: @text@; border: 1px solid @border2@;
    border-radius: 8px; padding: 5px 8px; selection-background-color: @accent@; selection-color: @accent_text@; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: @accent@; }
QSpinBox { padding-right: 24px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none; background: transparent; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none; background: transparent; }
QSpinBox::up-arrow { image: url(@chevup@); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url(@chev@); width: 10px; height: 10px; }
QRadioButton::indicator { width: 14px; height: 14px; border-radius: 9px; border: 2px solid @muted@; background: @field@; }
QRadioButton::indicator:hover { border-color: @text@; }
QRadioButton::indicator:checked { border: 2px solid @accent@; background: qradialgradient(cx:.5, cy:.5, radius:.5, fx:.5, fy:.5, stop:0 @accent@, stop:.45 @accent@, stop:.55 @field@, stop:1 @field@); }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 2px solid @muted@; background: @field@; }
QCheckBox::indicator:hover { border-color: @text@; }
QCheckBox::indicator:checked { border: 2px solid @accent@; background: @accent@; image: url(@tick@); }
QComboBox { background: @field@; color: @text@; border: 1px solid @border2@; border-radius: 8px; padding: 5px 30px 5px 10px; min-height: 20px; }
QComboBox:hover { border-color: @muted@; }
QComboBox:focus, QComboBox:on { border-color: @accent@; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(@chev@); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: @panel@; border: 1px solid @border2@; padding: 4px; outline: 0;
    selection-background-color: @press@; selection-color: @text@; }
QSlider { min-height: 26px; }
QSlider::groove:horizontal { height: 4px; background: @border2@; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @accent@; border-radius: 2px; }
QSlider::handle:horizontal { background: @accent@; border: none; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: @accent_hover@; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: @border2@; border-radius: 4px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: @muted@; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: @border2@; border-radius: 4px; min-width: 36px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: @muted@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QDockWidget { color: @muted@; }
QDockWidget::title { background: @bg@; padding: 4px 8px; text-align: left; }
QMainWindow::separator { background: @bg@; width: 8px; height: 8px; }
QScrollArea { border: none; background: transparent; }
QGraphicsView { border: 1px solid @border@; background: @canvas@; }
QListWidget { background: @panel@; border: 1px solid @border@; border-radius: 12px; padding: 6px; outline: 0; }
QListWidget::item { border-radius: 8px; padding: 6px; color: @text@; }
QListWidget::item:hover { background: @hover@; }
QListWidget::item:selected { background: @accent_soft@; color: @text@; }
QTabWidget::pane { border: 1px solid @border@; border-radius: 12px; background: @panel@; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: @muted@; padding: 8px 16px; margin: 2px 2px 8px 2px; border-radius: 9px; }
QTabBar::tab:hover { background: @hover@; color: @text@; }
QTabBar::tab:selected { background: @press@; color: @text@; }
QStatusBar { background: @bg@; color: @muted@; }
QStatusBar::item { border: none; }
QLabel { background: transparent; }
QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QGroupBox { border: 1px solid @border@; border-radius: 10px; margin-top: 10px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: @muted@; }
QProgressBar { background: @field@; border: none; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: @accent@; border-radius: 6px; }
/* ---- workspace ---- */
QToolBar#tools { background: @panel@; border: 1px solid @border@; border-radius: 14px; padding: 8px 5px; spacing: 3px; }
QToolBar#tools QToolButton { color: @muted@; font-size: 11px; font-weight: 600; padding: 8px 2px 6px 2px; min-width: 58px; border-radius: 10px; }
QToolBar#tools QToolButton:hover { background: @hover@; color: @text@; }
QToolBar#tools QToolButton:pressed { background: @press@; }
QToolBar#tools QToolButton::menu-indicator { image: none; width: 0; }
QToolBar#opts { background: @bg@; padding: 2px 10px 6px 10px; spacing: 6px; }
QToolBar#opts QToolButton { padding: 6px 8px; border-radius: 8px; }
QToolBar#opts QLabel { color: @muted@; font-size: 12px; padding: 0 2px 0 6px; }
QToolBar#opts QSpinBox, QToolBar#opts QComboBox { min-height: 20px; }
QWidget#panelBody { background: @panel@; border: 1px solid @border@; border-radius: 14px; }
QWidget#dockHead { background: transparent; border: none; }
QLabel#dockTitle { color: @text@; font-size: 13px; font-weight: 700; padding: 2px 4px; }
QLabel#dockCount { color: @muted@; font-size: 12px; }
QLabel#sect { color: @muted@; font-size: 11px; font-weight: 700; letter-spacing: 1px; padding-top: 6px; }
QLabel#fieldLab { color: @muted@; font-size: 11px; }
QLabel#val { color: @text@; font-size: 12px; font-weight: 600; }
QLabel#hint { color: @muted@; font-size: 12px; }
QFrame#hline { background: @border@; max-height: 1px; border: none; }
QToolButton#tipsBtn { color: @muted@; font-size: 12px; font-weight: 600; padding: 4px 2px; }
QToolButton#tipsBtn:hover { color: @text@; background: transparent; }
QListWidget#layers { background: transparent; border: none; padding: 2px; }
QListWidget#layers::item { border-radius: 10px; padding: 5px 6px; margin: 1px 0; color: @text@; }
QListWidget#layers::item:hover { background: @hover@; }
QListWidget#layers::item:selected { background: @accent_soft@; color: @text@; }
QStatusBar { background: @bg@; color: @muted@; padding: 0 8px; }
QStatusBar QLabel { color: @muted@; font-size: 12px; padding: 0 4px; }
QToolButton#zoomBtn { padding: 3px 6px; border-radius: 7px; }
QLabel#statusDot { color: @accent@; }
QPushButton#ghost { background: transparent; border: 1px solid @border2@; color: @text@; padding: 6px 14px; }
QPushButton#ghost:hover { background: @hover@; }
QMainWindow::separator { background: @bg@; width: 8px; height: 8px; }
QTabBar::tab:!selected { margin-bottom: 8px; }
/* ---------------- Aero UI 2: app bar, tool options, inspector ---------------- */
QMenuBar { background: transparent; }
QWidget#topbar { background: @bg@; }
QMenuBar#mbar { background: transparent; padding: 0; spacing: 0; }
QMenuBar#mbar::item { padding: 6px 10px; border-radius: 8px; color: @muted@; font-weight: 600; }
QMenuBar#mbar::item:selected, QMenuBar#mbar::item:pressed { background: @hover@; color: @text@; }
QToolButton#homeBtn { background: transparent; border-radius: 12px; padding: 3px; }
QToolButton#homeBtn:hover { background: @hover@; }
QLabel#projTitle { color: @text@; font-size: 14px; font-weight: 700; }
QLabel#projState { color: @muted@; font-size: 11px; }
QLabel#chipSaved { background: @field@; color: @muted@; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }
QLabel#chipDirty { background: @accent_soft@; color: @accent@; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }
QFrame#pill { background: @panel@; border: 1px solid @border@; border-radius: 12px; }
QFrame#pill QToolButton { padding: 4px 7px; border-radius: 8px; color: @text@; font-weight: 600; }
QFrame#pill QToolButton:hover { background: @hover@; }
QFrame#vline { background: @border2@; max-width: 1px; min-width: 1px; border: none; }
QToolBar#opts { background: @panel@; border: 1px solid @border@; border-radius: 14px; padding: 5px 8px; spacing: 6px; }
QToolBar#opts QToolButton { padding: 5px 8px; border-radius: 9px; }
QToolButton#fmt { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; border-radius: 9px; }
QToolButton#fmt:checked { background: @accent_soft@; }
QToolButton#fmtText { padding: 6px 10px; border-radius: 9px; font-weight: 600; }
QToolButton#fmtText::menu-indicator { image: none; width: 0; }
QToolBar#opts QLabel#ctxHint { color: @muted@; padding: 0 6px; }
QToolBar#opts QFontComboBox, QToolBar#opts QSpinBox { min-height: 24px; }
QPushButton#secHead { background: transparent; border: none; border-radius: 6px; text-align: left; font-weight: 700; font-size: 12px;
    color: @text@; padding: 8px 2px 6px 2px; }
QPushButton#secHead:hover { color: @accent@; background: transparent; }
QFrame#secLine { background: @border@; max-height: 1px; border: none; }
QLineEdit#search { border-radius: 10px; padding: 6px 10px 6px 30px; background: @field@; }
QToolBar#tools { border-radius: 16px; padding: 10px 6px; }
QToolBar#tools QToolButton { min-width: 56px; border-radius: 12px; }
QToolBar#tools QToolButton:checked { background: @accent_soft@; color: @accent@; }
QGraphicsView { border: none; }
QListWidget#layers { background: transparent; border: none; padding: 0; }
QMessageBox { background: @panel@; }
QFrame#card { background: @panel@; border: 1px solid @border@; border-radius: 16px; }
QFrame#cardSoft { background: @field@; border: 1px solid @border@; border-radius: 14px; }
QLabel#h1 { color: @text@; font-size: 28px; font-weight: 800; }
QLabel#h2 { color: @text@; font-size: 16px; font-weight: 700; }
QLabel#sub { color: @muted@; font-size: 13px; }
/* ---------------- Aero UI 3: flush, docked studio layout ---------------- */
QMainWindow { background: @bg@; }
QWidget#topbar { background: @panel@; border-bottom: 1px solid @border@; }
QToolBar#opts { background: @panel@; border: none; border-bottom: 1px solid @border@; border-radius: 0; padding: 6px 14px; spacing: 6px; }
QToolBar#tools { background: @panel@; border: none; border-right: 1px solid @border@; border-radius: 0; padding: 12px 6px; spacing: 2px; }
QToolBar#tools QToolButton { min-width: 54px; border-radius: 10px; font-size: 10.5px; padding: 8px 0 6px 0; }
QToolBar#tools::separator { background: @border@; height: 1px; margin: 8px 10px; }
QWidget#panelBody { background: @panel@; border: none; border-left: 1px solid @border@; border-radius: 0; }
QMainWindow::separator { background: @border@; width: 1px; height: 1px; }
QWidget#dockHead { background: @panel@; border: none; border-bottom: 1px solid @border@; border-left: 1px solid @border@; }
QLabel#dockTitle { color: @text@; font-size: 12px; font-weight: 700; padding: 8px 6px; }
QStatusBar { background: @panel@; border-top: 1px solid @border@; color: @muted@; padding: 0 10px; }
QGraphicsView { border: none; background: @canvas@; }
QPushButton { border-radius: 8px; padding: 6px 14px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { border-radius: 8px; min-height: 22px; }
QToolButton { border-radius: 8px; }
QFrame#pill { background: @panel@; border: 1px solid @border2@; border-radius: 12px; }
QFrame#floatBar { background: @panel@; border: 1px solid @border2@; border-radius: 14px; }
QFrame#floatBar QToolButton { padding: 5px 8px; border-radius: 9px; color: @text@; font-weight: 600; }
QFrame#floatBar QToolButton:hover { background: @hover@; }
QFrame#floatBar QLabel { color: @muted@; font-size: 12px; font-weight: 600; padding: 0 4px; }
QFrame#floatBar QFrame#vline { background: @border2@; }
QToolButton#chip { background: transparent; color: @muted@; border: 1px solid transparent; border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 600; }
QToolButton#chip:hover { background: @hover@; color: @text@; }
QToolButton#chip:checked { background: @accent_soft@; color: @accent@; border-color: @accent_soft@; }
QFrame#layerFoot { background: transparent; border-top: 1px solid @border@; }
QFrame#layerFoot QToolButton { padding: 6px; border-radius: 8px; }
QPushButton#primary { border: none; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent@, stop:1 @accent2@); }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent_hover@, stop:1 @accent2@); }
QPushButton#primary:disabled { background: @field@; color: @muted@; }
QLabel#secTitle { color: @muted@; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QFrame#secHeadRow:hover QLabel#secTitle { color: @text@; }
QSpinBox, QDoubleSpinBox { padding: 2px 30px 2px 8px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 24px;
    border: none; border-left: 1px solid @border2@; border-bottom: 1px solid @border2@; border-top-right-radius: 7px; background: @raised@; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 24px;
    border: none; border-left: 1px solid @border2@; border-bottom-right-radius: 7px; background: @raised@; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: @accent_soft@; }
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed, QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed { background: @press@; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@chevup@); width: 16px; height: 16px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@chev@); width: 16px; height: 16px; }
QToolBar#opts QSpinBox { padding: 1px 28px 1px 6px; }
"""


def apply_theme(app, theme=None, accent=None):
    """Whole-application look: colour palette + one global stylesheet (dark or light, any accent colour)."""
    global PASTEBOARD, UI_DOT, UI_LABEL
    t = theme_tokens(theme, accent)
    app.setStyle("Fusion")
    pal = QPalette()
    ac = QColor(t["accent"])
    for role, col in ((QPalette.Window, t["panel"]), (QPalette.WindowText, t["text"]), (QPalette.Base, t["field"]),
                      (QPalette.AlternateBase, t["hover"]), (QPalette.Text, t["text"]), (QPalette.Button, t["field"]),
                      (QPalette.ButtonText, t["text"]), (QPalette.ToolTipBase, t["panel"]), (QPalette.ToolTipText, t["text"]),
                      (QPalette.Highlight, ac), (QPalette.Link, ac), (QPalette.HighlightedText, t["accent_text"]),
                      (QPalette.PlaceholderText, t["muted"])):
        pal.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(t["muted"]))
    pal.setColor(QPalette.Mid, QColor(t["muted"]))      # text styled with palette(mid) stays readable in both themes
    pal.setColor(QPalette.PlaceholderText, QColor(t["muted"]))
    app.setPalette(pal)
    try:
        d = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation)) / "aero_ui"
        d.mkdir(parents=True, exist_ok=True)
        chev = d / f"chev_{t['text'].strip('#')}.png"
        _chevron(chev, t["muted"])
        up = d / f"chevup_{t['text'].strip('#')}.png"
        _chevron(up, t["muted"], up=True)
        tick = d / f"tick_{t['accent_text'].strip('#')}.png"
        _tick(tick, t["accent_text"])
        t["chev"], t["chevup"], t["tick"] = chev.as_posix(), up.as_posix(), tick.as_posix()
    except OSError:
        t["chev"] = t["chevup"] = t["tick"] = ""
    q = QSS
    for k, v in sorted(t.items(), key=lambda kv: -len(kv[0])):
        if isinstance(v, str):
            q = q.replace(f"@{k}@", v)
    app.setStyleSheet(q)
    PASTEBOARD = QColor(t["canvas"])
    UI_DOT = QColor(255, 255, 255, 30) if t["dark"] else QColor(0, 0, 0, 38)
    UI_LABEL = QColor(t["muted"])
    for w in app.topLevelWidgets():
        if hasattr(w, "refresh_icons"):
            w.refresh_icons()
        sc = getattr(w, "scene", None)
        if sc is not None and hasattr(sc, "update"):
            sc.update()


def _run(cmd, timeout=6):
    import subprocess
    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw).stdout.strip()
    except Exception:
        return ""


def detect_gpus():
    """GPU names of this computer, discrete cards first (e.g. 'NVIDIA GeForce RTX 5090')."""
    names = []
    if sys.platform.startswith("win"):
        out = _run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"])
        names = [x.strip() for x in out.splitlines() if x.strip()]
        if not names:
            out = _run(["wmic", "path", "win32_VideoController", "get", "name"])
            names = [x.strip() for x in out.splitlines()[1:] if x.strip()]
    elif sys.platform == "darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"])
        names = [x.split(":", 1)[1].strip() for x in out.splitlines() if "Chipset Model" in x]
    else:
        out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
        names = [x.strip() for x in out.splitlines() if x.strip()]
        for line in _run(["lspci"]).splitlines():
            if any(k in line for k in ("VGA", "3D controller", "Display controller")):
                nm = line.split(": ", 1)[-1].strip()
                if not any(nm.split("[")[-1].strip("] ") in n for n in names):
                    names.append(nm)
    names = [n for n in names if n and "basic" not in n.lower() and "remote" not in n.lower()] or names

    def rank(n):
        n = n.lower()
        return 0 if any(k in n for k in ("nvidia", "geforce", "rtx", "radeon rx", "arc ")) else 2 if any(k in n for k in ("intel", "uhd", "iris", "vega", "radeon(tm)")) else 1
    return sorted(dict.fromkeys(names), key=rank)


def system_specs():
    import platform
    os_name = platform.platform()
    if sys.platform.startswith("win"):
        try:
            build = int(platform.version().split(".")[-1])
            os_name = f"Windows {'11' if build >= 22000 else platform.release()} (build {build})"
        except ValueError:
            pass
    cpu = ""
    if sys.platform.startswith("win"):
        cpu = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"])
    elif sys.platform == "darwin":
        cpu = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    else:
        try:
            cpu = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "")
        except OSError:
            pass
    cpu = (cpu or platform.processor() or platform.machine()).strip()
    cores = os.cpu_count() or 0
    ram = ""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tf", ctypes.c_ulonglong), ("af", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong),
                            ("ae", ctypes.c_ulonglong)]
            ms = MS()
            ms.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            ram = f"{ms.tp / 2**30:.1f} GB"
        elif sys.platform == "darwin":
            ram = f"{int(_run(['sysctl', '-n', 'hw.memsize'])) / 2**30:.1f} GB"
        else:
            kb = next(int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemTotal"))
            ram = f"{kb / 2**20:.1f} GB"
    except Exception:
        ram = "unknown"
    return {"Operating system": os_name, "Processor": f"{cpu}  ({cores} threads)" if cores else cpu, "Memory": ram or "unknown"}


class ThemeTile(QPushButton):
    """Clickable picture of the Dark / Light look (a tiny window drawn in that theme's colours)."""
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(150, 104)
        self.setToolTip(f"{name} theme")

    def paintEvent(self, ev):
        t = THEMES[self.name]
        pal = QApplication.palette()
        acc = pal.color(QPalette.Highlight)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(QPen(acc if self.isChecked() else QColor(t["border2"]), 2.5 if self.isChecked() else 1))
        p.setBrush(QColor(t["bg"]))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["panel"]))
        p.drawRoundedRect(QRectF(r.left() + 8, r.top() + 22, 28, r.height() - 44), 6, 6)
        p.drawRoundedRect(QRectF(r.right() - 44, r.top() + 22, 36, r.height() - 44), 6, 6)
        p.setBrush(QColor(t["canvas"]))
        p.drawRoundedRect(QRectF(r.left() + 42, r.top() + 22, r.width() - 94, r.height() - 44), 6, 6)
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(r.right() - 40, r.top() + 28, 28, 6), 3, 3)
        p.setBrush(QColor(t["muted"]))
        p.drawRoundedRect(QRectF(r.left() + 12, r.top() + 8, 30, 5), 2.5, 2.5)
        p.setBrush(QColor(t["text"]))
        p.drawRoundedRect(QRectF(r.left() + 46, r.top() + 36, 24, 34), 3, 3)
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(t["text"]))
        p.drawText(QRectF(r.left(), r.bottom() - 20, r.width(), 18), Qt.AlignCenter, self.name)


class SizeTile(QPushButton):
    """Slide format picker: a rectangle with the real proportions, the ratio and the pixel size."""
    def __init__(self, label, size):
        super().__init__()
        self.w, self.h = size
        self.ratio = label.split(" ")[0]
        self.kind = label[label.find("(") + 1:label.find(")")] if "(" in label else ""
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(94, 118)
        self.setToolTip(f"{label}  -  {self.w} x {self.h} px")

    def paintEvent(self, ev):
        pal = QApplication.palette()
        acc, txt, mut = pal.color(QPalette.Highlight), pal.color(QPalette.WindowText), pal.color(QPalette.PlaceholderText)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on, hov = self.isChecked(), self.underMouse()
        bg = QColor(acc)
        bg.setAlpha(40 if on else 0)
        p.setPen(QPen(acc if on else QColor(128, 134, 150, 140 if hov else 70), 2 if on else 1))
        p.setBrush(bg if on else pal.color(QPalette.Base))
        p.drawRoundedRect(r, 14, 14)
        box, k = QRectF(0, 0, 44, 52), min(44.0 / self.w, 52.0 / self.h)
        rr = QRectF(0, 0, self.w * k, self.h * k)
        rr.moveCenter(QPointF(r.center().x(), r.top() + 36))
        p.setPen(QPen(acc if on else mut, 1.6))
        fill = QColor(acc if on else mut)
        fill.setAlpha(60)
        p.setBrush(fill)
        p.drawRoundedRect(rr, 4, 4)
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(acc if on else txt)
        p.drawText(QRectF(r.left(), r.top() + 66, r.width(), 18), Qt.AlignCenter, self.ratio)
        f.setPixelSize(10)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(mut)
        p.drawText(QRectF(r.left(), r.top() + 84, r.width(), 14), Qt.AlignCenter, self.kind)
        p.drawText(QRectF(r.left(), r.top() + 97, r.width(), 14), Qt.AlignCenter, f"{self.w}\u00d7{self.h}")


class SettingsDialog(QDialog):
    """File > Settings: General (language), Appearance (theme + accent), Version, About (system information)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(760, 520)
        c = cfg()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 14)
        outer.setSpacing(10)
        row_ = QHBoxLayout()
        row_.setSpacing(16)
        outer.addLayout(row_, 1)
        navw = QFrame()
        navw.setObjectName("cardSoft")
        navw.setFixedWidth(180)
        nl = QVBoxLayout(navw)
        nl.setContentsMargins(8, 10, 8, 10)
        nl.setSpacing(2)
        self.nav_btns = []
        for k, (nm, ic) in enumerate((("General", "settings"), ("Appearance", "sun"), ("Version", "tips"), ("About", "info"))):
            b = QPushButton("  " + nm)
            b.setObjectName("setNav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(QIcon(icon_pixmap(ic, theme_tokens()["muted"], 18)))
            b.clicked.connect(lambda checked=False, k=k: self.go_to(k))
            nl.addWidget(b)
            self.nav_btns.append(b)
        nl.addStretch()
        navw.setStyleSheet("QPushButton#setNav { background: transparent; border: none; border-radius: 9px; text-align: left; padding: 9px 10px; "
                           "font-weight: 600; color: palette(placeholder-text); }"
                           "QPushButton#setNav:hover { background: palette(alternate-base); color: palette(window-text); }"
                           "QPushButton#setNav:checked { background: palette(alternate-base); color: palette(highlight); }")
        row_.addWidget(navw)
        tabs = QTabWidget()
        tabs.tabBar().hide()
        tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        self.tabs = tabs
        row_.addWidget(tabs, 1)
        lay = outer
        # General
        g = QWidget()
        gl = QVBoxLayout(g)
        h_ = QLabel("Language")
        h_.setObjectName("h2")
        gl.addWidget(h_)
        self.lang = QComboBox()
        self.lang.addItems(LANGUAGES)
        self.lang.setCurrentText(c.value("language", "English"))
        self.lang.currentTextChanged.connect(lambda v: cfg().setValue("language", v))
        gl.addWidget(self.lang)
        note = QLabel("Your choice is saved. Translated interface text is not part of this release yet, so the app still shows English.")
        note.setWordWrap(True)
        gl.addWidget(note)
        gl.addSpacing(8)
        h2_ = QLabel("Performance")
        h2_.setObjectName("h2")
        gl.addWidget(h2_)
        self.gpu = QCheckBox("Use the graphics card (GPU) to draw the canvas")
        self.gpu.setChecked(c.value("gpu", "true") == "true")
        self.gpu.toggled.connect(lambda on: (cfg().setValue("gpu", "true" if on else "false"), cfg().setValue("gpu_guard", "0")))
        gl.addWidget(self.gpu)
        m = parent
        status = getattr(m, "gpu_note", "unknown")
        gnote = QLabel(f"Smoother panning and zooming with many photos, texts and filters. Takes effect the next time you start Aero.\n"
                       f"Right now: GPU drawing is {'ACTIVE' if getattr(m, 'gpu_active', False) else 'not active'} ({status}).")
        gnote.setWordWrap(True)
        gnote.setStyleSheet("color: palette(mid);")
        gl.addWidget(gnote)
        gl.addStretch()
        tabs.addTab(g, "General")
        # Appearance
        a = QWidget()
        al = QVBoxLayout(a)
        th = QLabel("Theme")
        th.setObjectName("h2")
        al.addWidget(th)
        tr_ = QHBoxLayout()
        tr_.setSpacing(12)
        self.theme_btns = {}
        for t in ("Dark", "Light"):
            r = ThemeTile(t)
            r.setChecked(c.value("theme", "Dark") == t)
            r.clicked.connect(lambda checked=False, t=t: self.set_theme(t))
            self.theme_btns[t] = r
            tr_.addWidget(r)
        tr_.addStretch()
        al.addLayout(tr_)
        al.addSpacing(14)
        ac_ = QLabel("Accent colour")
        ac_.setObjectName("h2")
        al.addWidget(ac_)
        sw = QHBoxLayout()
        sw.setSpacing(8)
        for nm, hexc in ACCENT_PRESETS:
            b = QPushButton()
            b.setFixedSize(30, 30)
            b.setToolTip(nm)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background: {hexc}; border: 2px solid transparent; border-radius: 15px; padding: 0; }}"
                            f"QPushButton:hover {{ border-color: palette(text); }}")
            b.clicked.connect(lambda checked=False, c=hexc: self.set_accent(c))
            sw.addWidget(b)
        sw.addStretch()
        al.addLayout(sw)
        al.addSpacing(6)
        row = QHBoxLayout()
        self.accent_btn = QPushButton()
        self.accent_btn.clicked.connect(self.pick_accent)
        row.addWidget(self.accent_btn)
        rb = QPushButton("Reset")
        rb.clicked.connect(lambda: self.set_accent(DEFAULT_ACCENT))
        row.addWidget(rb)
        row.addStretch()
        al.addLayout(row)
        al.addStretch()
        tabs.addTab(a, "Appearance")
        self.paint_accent()
        # Version
        v = QWidget()
        vl = QVBoxLayout(v)
        for i, line in enumerate(VERSION_LINES):
            vt = QLabel(line)
            vt.setWordWrap(True)
            vt.setStyleSheet("font-size: 15px; font-weight: 600;" if i == 0 else "font-size: 13px; color: palette(mid);")
            vl.addWidget(vt)
            vl.addSpacing(6)
        vl.addStretch()
        tabs.addTab(v, "Version")
        # About
        ab = QWidget()
        self.about_l = QFormLayout(ab)
        tabs.addTab(ab, "About")
        self.about_ready = False
        tabs.currentChanged.connect(lambda i: (i == 3 and self.fill_about(), [b.setChecked(n == i) for n, b in enumerate(self.nav_btns)]))
        self.nav_btns[0].setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        bb.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        lay.addWidget(bb)

    def go_to(self, k):
        self.tabs.setCurrentIndex(k)
        for n, b in enumerate(self.nav_btns):
            b.setChecked(n == k)

    def fill_about(self):
        if self.about_ready:
            return
        self.about_ready = True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            gpus = detect_gpus()
            specs = system_specs()
        finally:
            QApplication.restoreOverrideCursor()
        h = QLabel("System Information")
        h.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.about_l.addRow(h)
        rows = [("Application", "Aero"), ("Build", APP_BUILD), ("Graphics", "\n".join(gpus) if gpus else "Not detected")]
        rows += list(specs.items()) + [("Engine", "Aero Image Processor")]
        for k, val in rows:
            lb = QLabel(val)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lb.setWordWrap(True)
            self.about_l.addRow(k + ":", lb)

    def paint_accent(self):
        col = cfg().value("accent", DEFAULT_ACCENT)
        set_swatch(self.accent_btn, col, f"  {col}  -  change...")

    def set_theme(self, t):
        cfg().setValue("theme", t)
        apply_theme(QApplication.instance())
        for k, b in self.theme_btns.items():
            b.setChecked(k == t)

    def set_accent(self, col):
        cfg().setValue("accent", col)
        apply_theme(QApplication.instance())
        self.paint_accent()

    def pick_accent(self):
        col = QColorDialog.getColor(QColor(cfg().value("accent", DEFAULT_ACCENT)), self, "Accent colour")
        if col.isValid():
            self.set_accent(col.name())




def thumb_path(path):
    """Where the small preview picture of a saved project is kept."""
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    d = (Path(base) if base else Path.home() / ".aero_photo_editor") / "thumbs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d / (hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:16] + ".png")


def placeholder_icon():
    pm = QPixmap(150, 84)
    pm.fill(QColor(44, 47, 62))
    return QIcon(pm)


def recent_projects():
    cfg = QSettings("AeroPhotoEditor", "Editor")
    v = cfg.value("recent", [])
    v = [v] if isinstance(v, str) else list(v or [])
    return [x for x in v if Path(x).exists()]


def add_recent(path):
    cfg = QSettings("AeroPhotoEditor", "Editor")
    cur = [x for x in recent_projects() if Path(x) != Path(path)]
    cfg.setValue("recent", ([str(path)] + cur)[:10])


NEW_SIZES = [("4:5 (Portrait)", (1080, 1350)), ("3:4 (Portrait)", (1080, 1440)), ("9:16 (Story)", (1080, 1920)),
             ("1:1 (Square)", (1080, 1080)), ("16:9 (Landscape)", (1920, 1080))]


def default_projects_dir():
    base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
    return str(Path(base) / "Aero Projects")


class NewProjectDialog(QDialog):
    """Fixed-size window: project name, save location, slide format (pictures), number of slides, Create."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.info = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(8)
        self.lay = lay
        h1 = QLabel("New project")
        h1.setObjectName("h1")
        h1.setStyleSheet("font-size: 24px;")
        lay.addWidget(h1)
        sub = QLabel("Name it, choose a slide format and how many slides you need. You can change both later.")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(10)
        lay.addWidget(self.head("Project name"))
        self.name = QLineEdit("Untitled")
        self.name.textChanged.connect(self.check)
        lay.addWidget(self.name)
        lay.addSpacing(6)
        lay.addWidget(self.head("Save to"))
        row = QHBoxLayout()
        self.loc = QLineEdit(default_projects_dir())
        self.loc.textChanged.connect(self.check)
        row.addWidget(self.loc, 1)
        b = QPushButton("Choose...")
        b.clicked.connect(self.choose)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addSpacing(6)
        lay.addWidget(self.head("Slide format"))
        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self.radios = []
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for i, (label, sz) in enumerate(NEW_SIZES):
            r = SizeTile(label, sz)
            r.setChecked(i == 0)
            grp.addButton(r)
            self.radios.append(r)
            tiles.addWidget(r)
        lay.addLayout(tiles)
        lay.addSpacing(6)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.head("Number of slides"))
        hint = QLabel("A carousel can have up to 20 slides")
        hint.setObjectName("sub")
        col.addWidget(hint)
        row.addLayout(col)
        row.addStretch()
        self.n = QSpinBox()
        self.n.setRange(1, 20)
        self.n.setValue(3)
        self.n.setFixedWidth(96)
        row.addWidget(self.n)
        lay.addLayout(row)
        lay.addSpacing(10)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #ff6b6b;")
        self.msg.setWordWrap(True)
        self.msg.hide()
        lay.addWidget(self.msg)
        self.create = QPushButton("Create project")
        self.create.setObjectName("primary")
        self.create.setMinimumHeight(40)
        self.create.setDefault(True)
        self.create.clicked.connect(self.make)
        lay.addWidget(self.create)
        self.fit()

    def fit(self):
        """Exactly as tall as its content (no empty space); the message line only takes room when shown."""
        self.setFixedSize(560, self.lay.sizeHint().height())

    @staticmethod
    def head(t):
        l = QLabel(t)
        l.setStyleSheet("font-weight: 700;")
        return l

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, "Where should the project be saved?", self.loc.text() or str(Path.home()))
        if d:
            self.loc.setText(d)

    def check(self, *_):
        ok = bool(self.name.text().strip()) and bool(self.loc.text().strip())
        bad = set('<>:"/\\|?*') & set(self.name.text())
        self.create.setEnabled(ok and not bad)
        self.msg.setText("A file name cannot contain  < > : \" / \\ | ? *" if bad else "")
        self.msg.setVisible(bool(bad))
        self.fit()

    def make(self):
        name, folder = self.name.text().strip(), Path(self.loc.text().strip()).expanduser()
        if name.lower().endswith(".carousel"):
            name = name[:-9]
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            self.msg.setText(f"Cannot use that folder: {ex}")
            self.msg.show()
            self.fit()
            return
        path = folder / f"{name}.carousel"
        if path.exists() and QMessageBox.question(self, "Replace?", f"{path.name} already exists in that folder. Replace it?") != QMessageBox.Yes:
            return
        size = next(sz for r, (_, sz) in zip(self.radios, NEW_SIZES) if r.isChecked())
        self.info = {"path": str(path), "size": size, "n": self.n.value()}
        self.accept()


def glyph_icon(kind, color, size=24):
    """Tiny line icons for the start screen cards (drawn, so no image files are needed)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), size / 12, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    u = size / 24
    if kind == "plus":
        p.drawLine(QPointF(12 * u, 5 * u), QPointF(12 * u, 19 * u))
        p.drawLine(QPointF(5 * u, 12 * u), QPointF(19 * u, 12 * u))
    elif kind == "folder":
        path = QPainterPath()
        path.moveTo(3 * u, 8 * u); path.lineTo(3 * u, 18 * u); path.quadTo(3 * u, 20 * u, 5 * u, 20 * u)
        path.lineTo(19 * u, 20 * u); path.quadTo(21 * u, 20 * u, 21 * u, 18 * u); path.lineTo(21 * u, 9 * u)
        path.quadTo(21 * u, 7 * u, 19 * u, 7 * u); path.lineTo(11 * u, 7 * u); path.lineTo(9 * u, 4.5 * u)
        path.lineTo(5 * u, 4.5 * u); path.quadTo(3 * u, 4.5 * u, 3 * u, 6.5 * u); path.closeSubpath()
        p.drawPath(path)
    elif kind == "grid":
        for x, y, w, h in ((4, 4, 7, 9), (13, 4, 7, 5), (13, 11, 7, 9), (4, 15, 7, 5)):
            p.drawRoundedRect(QRectF(x * u, y * u, w * u, h * u), 1.8 * u, 1.8 * u)
    else:                                              # "image"
        p.drawRoundedRect(QRectF(3.5 * u, 4.5 * u, 17 * u, 15 * u), 3 * u, 3 * u)
        p.drawEllipse(QPointF(9 * u, 10 * u), 1.6 * u, 1.6 * u)
        p.drawPolyline([QPointF(4 * u, 17 * u), QPointF(10 * u, 12.5 * u), QPointF(14 * u, 15.5 * u), QPointF(17 * u, 13 * u), QPointF(20 * u, 16 * u)])
    p.end()
    return pm


def icon_pixmap(name, color, size=24):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    pp = QPainter(pm)
    draw_ui_icon(pp, name, color, size * 2)
    pp.end()
    pm.setDevicePixelRatio(2)
    return pm


def rel_time(ts):
    """'Edited 3 hours ago' style text for the recent project cards."""
    d = max(0, time.time() - ts)
    if d < 90:
        return "Just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    if d < 172800:
        return "Yesterday"
    if d < 86400 * 30:
        return f"{int(d // 86400)} days ago"
    return time.strftime("%d %b %Y", time.localtime(ts))


class ActionCard(QPushButton):
    """Big action tile on the start screen: round icon, title, one line of help."""
    def __init__(self, kind, title, sub, hero=False):
        super().__init__()
        self.setObjectName("cardHero" if hero else "card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(88)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(14)
        t = theme_tokens()
        ic = QLabel()
        ic.setFixedSize(44, 44)
        ic.setAlignment(Qt.AlignCenter)
        ic.setObjectName("cardIconHero" if hero else "cardIcon")
        ic.setPixmap(icon_pixmap(kind, t["accent_text"] if hero else t["accent"], 22))
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addStretch()
        tl = QLabel(title)
        tl.setObjectName("cardTitle")
        sb = QLabel(sub)
        sb.setObjectName("cardSub")
        col.addWidget(tl)
        col.addWidget(sb)
        col.addStretch()
        row.addWidget(ic)
        row.addLayout(col, 1)
        for w in (ic, tl, sb):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)


class RecentCard(QPushButton):
    """One recent project: picture, name, when it was last edited. Right-click for Open / Remove."""
    W, H = 206, 190

    def __init__(self, path, pm, when):
        super().__init__()
        self.path = path
        self.setObjectName("rcard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.W, self.H)
        self.setToolTip(str(path))
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 10)
        v.setSpacing(1)
        img = QLabel()
        img.setFixedSize(190, 107)
        img.setPixmap(pm)
        img.setAttribute(Qt.WA_TransparentForMouseEvents)
        nm = QLabel(QFontMetricsF(self.font()).elidedText(Path(path).stem, Qt.ElideRight, 176))
        nm.setObjectName("rname")
        dt = QLabel(when)
        dt.setObjectName("rdate")
        for w in (nm, dt):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(img)
        v.addSpacing(6)
        v.addWidget(nm)
        v.addWidget(dt)
        v.addStretch()


class TemplateCard(QPushButton):
    """A template on the start screen (all its slides side by side)."""
    def __init__(self, t, pm):
        super().__init__()
        self.t = t
        self.setObjectName("rcard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(278, 156)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 10)
        v.setSpacing(1)
        img = QLabel()
        img.setFixedSize(262, 94)
        img.setAlignment(Qt.AlignCenter)
        img.setObjectName("tplImg")
        if pm is not None:
            img.setPixmap(pm)
        img.setAttribute(Qt.WA_TransparentForMouseEvents)
        nm = QLabel(t["name"])
        nm.setObjectName("rname")
        dt = QLabel(f"{t['n']} slides  \u00b7  {t['pw']} \u00d7 {t['ph']}")
        dt.setObjectName("rdate")
        for w in (nm, dt):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(img)
        v.addSpacing(6)
        v.addWidget(nm)
        v.addWidget(dt)
        v.addStretch()


class StartScreen(QDialog):
    """Shown before the editor opens: a sidebar (new, open, templates, settings), big action cards, recent projects
    and a few templates to start from."""
    @staticmethod
    def make_style():
        t = theme_tokens()
        q = """
        QDialog { background: @bg@; }
        QFrame#sidebar { background: @panel@; border: none; border-right: 1px solid @border@; border-radius: 0; }
        QLabel#brand { color: @text@; font-size: 20px; font-weight: 800; }
        QLabel#badge { color: @accent@; background: @accent_soft@; border-radius: 8px; padding: 2px 8px; font-size: 10px; font-weight: 800; }
        QPushButton#navItem { background: transparent; border: none; border-radius: 9px; text-align: left; padding: 10px 12px;
            color: @muted@; font-size: 13px; font-weight: 600; }
        QPushButton#navItem:hover { background: @hover@; color: @text@; }
        QPushButton#navItem:checked { background: @accent_soft@; color: @accent@; }
        QLabel#navCap { color: @muted@; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; padding: 16px 12px 4px 12px; }
        QLabel#ver { color: @muted@; font-size: 11px; }
        QLabel#title { color: @text@; font-size: 32px; font-weight: 800; }
        QLabel#intro { color: @muted@; font-size: 14px; }
        QLabel#head { color: @text@; font-size: 16px; font-weight: 700; }
        QLabel#emptybox { color: @muted@; font-size: 13px; background: transparent; }
        QLabel#emptytitle { color: @text@; font-size: 15px; font-weight: 700; background: transparent; }
        QFrame#emptyCard { background: transparent; border: 1px dashed @border2@; border-radius: 14px; }
        QPushButton#card, QPushButton#cardHero { background: @panel@; border: 1px solid @border@; border-radius: 14px; text-align: left; padding: 0; }
        QPushButton#card:hover { background: @hover@; border-color: @accent@; }
        QPushButton#cardHero { border: none;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent@, stop:1 @accent2@); }
        QPushButton#cardHero:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent_hover@, stop:1 @accent2@); }
        QLabel#cardTitle { color: @text@; font-size: 16px; font-weight: 700; background: transparent; }
        QLabel#cardSub { color: @muted@; font-size: 12px; background: transparent; }
        QPushButton#cardHero QLabel#cardTitle, QPushButton#cardHero QLabel#cardSub { color: @accent_text@; }
        QLabel#cardIcon { background: @accent_soft@; border-radius: 12px; }
        QLabel#cardIconHero { background: rgba(255, 255, 255, 0.24); border-radius: 12px; }
        QPushButton#rcard { background: @panel@; border: 1px solid @border@; border-radius: 14px; text-align: left; padding: 0; }
        QPushButton#rcard:hover { background: @hover@; border-color: @accent@; }
        QLabel#rname { color: @text@; font-size: 13px; font-weight: 700; background: transparent; }
        QLabel#rdate { color: @muted@; font-size: 11px; background: transparent; }
        QLabel#tplImg { background: @field@; border-radius: 9px; }
        QPushButton#link { background: transparent; border: none; color: @muted@; padding: 4px 6px; font-size: 12px; font-weight: 600; }
        QPushButton#link:hover { color: @accent@; }
        QScrollArea { background: transparent; border: none; }
        QWidget#mainBody { background: transparent; }
        QFrame#stepsCard { background: @panel@; border: 1px solid @border@; border-radius: 14px; }
        QLabel#stepNum { color: @accent@; background: @accent_soft@; border-radius: 11px; font-size: 11px; font-weight: 800; }
        QLabel#stepText { color: @text@; font-size: 12px; background: transparent; }
        QLabel#stepSub { color: @muted@; font-size: 11px; background: transparent; }
        """
        for k, v in sorted(t.items(), key=lambda kv: -len(kv[0])):
            if isinstance(v, str):
                q = q.replace(f"@{k}@", v)
        return q

    def __init__(self, main):
        super().__init__(None)
        self.main, self.result_action = main, None
        self.setWindowTitle(APP_NAME)
        self.setStyleSheet(self.make_style())
        self.setFixedSize(1180, 780)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        t = theme_tokens()
        # ---------------- sidebar
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(240)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 24, 16, 18)
        sl.setSpacing(2)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(40, 40)
        icon_file = resource_path("assets", "aero_icon_256.png")
        if os.path.exists(icon_file):
            lp = QPixmap(icon_file).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lp.setDevicePixelRatio(2)
            logo.setPixmap(lp)
        brand.addWidget(logo)
        bn = QLabel(APP_NAME)
        bn.setObjectName("brand")
        brand.addWidget(bn)
        brand.addStretch()
        sl.addLayout(brand)
        sl.addSpacing(14)

        def nav(kind, text, fn, checked=False):
            b = QPushButton("   " + text)
            b.setObjectName("navItem")
            b.setCheckable(True)
            b.setChecked(checked)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(QIcon(icon_pixmap(kind, t["accent"] if checked else t["muted"], 20)))
            b.setIconSize(QSize(20, 20))
            b.clicked.connect(lambda c=False: (b.setChecked(checked), fn()))
            return b
        sl.addWidget(nav("home", "Home", lambda: None, True))
        sl.addWidget(nav("plus", "New project", self.new))
        sl.addWidget(nav("folder", "Open project", self.open))
        sl.addWidget(nav("template", "Templates", self.template))
        cap = QLabel("MORE")
        cap.setObjectName("navCap")
        sl.addWidget(cap)
        sl.addWidget(nav("settings", "Settings", self.settings))
        sl.addWidget(nav("tips", "Quick tips", self.tips))
        sl.addWidget(nav("info", "About Aero", self.about))
        sl.addStretch()
        v0 = QLabel("Aero version " + APP_VERSION)
        v0.setObjectName("ver")
        sl.addWidget(v0)
        for txt in VERSION_LINES[1:]:
            v = QLabel(txt)
            v.setObjectName("ver")
            sl.addWidget(v)
        outer.addWidget(side)
        # ---------------- main column (scrolls on small screens)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("mainBody")
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        root = QVBoxLayout(body)
        root.setContentsMargins(36, 24, 36, 16)
        root.setSpacing(0)
        h1 = QLabel("Welcome to " + APP_NAME)
        h1.setObjectName("title")
        root.addWidget(h1)
        root.addSpacing(6)
        intro = QLabel("Welcome to Aero, an editor built for Instagram, Threads, and Facebook Album creation. Content purpose-built social media design platform made specifically for creators.")
        intro.setObjectName("intro")
        intro.setWordWrap(True)
        root.addWidget(intro)
        root.addSpacing(16)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        for kind, title, sub, fn, hero in (("plus", "New project", "Pick a slide size and count", self.new, True),
                                           ("folder", "Open project", "Continue a saved project", self.open, False),
                                           ("template", "Templates", "Ready-made carousel layouts", self.template, False)):
            c = ActionCard(kind, title, sub, hero)
            c.clicked.connect(fn)
            cards.addWidget(c, 1)
        root.addLayout(cards)
        root.addSpacing(14)
        steps = QFrame()
        steps.setObjectName("stepsCard")
        stl = QHBoxLayout(steps)
        stl.setContentsMargins(16, 9, 16, 9)
        stl.setSpacing(18)
        for n_, (a_, b_) in enumerate((("Create", "pick size and slide count"), ("Add", "photos, video and text"),
                                       ("Drag across", "the pink lines to join slides"), ("Export", "every slide saved in order")), 1):
            cell = QHBoxLayout()
            cell.setSpacing(9)
            nl = QLabel(str(n_))
            nl.setObjectName("stepNum")
            nl.setFixedSize(22, 22)
            nl.setAlignment(Qt.AlignCenter)
            tx = QVBoxLayout()
            tx.setSpacing(0)
            l1, l2 = QLabel(a_), QLabel(b_)
            l1.setObjectName("stepText")
            l1.setStyleSheet("font-weight: 700;")
            l2.setObjectName("stepSub")
            tx.addWidget(l1)
            tx.addWidget(l2)
            cell.addWidget(nl)
            cell.addLayout(tx)
            stl.addLayout(cell, 1)
        root.addWidget(steps)
        root.addSpacing(20)
        hr = QHBoxLayout()
        h = QLabel("Recent projects")
        h.setObjectName("head")
        hr.addWidget(h)
        hr.addStretch()
        self.show_all = QPushButton("Show all")
        self.show_all.setObjectName("link")
        self.show_all.setCursor(Qt.PointingHandCursor)
        self.show_all.clicked.connect(self.toggle_all)
        hr.addWidget(self.show_all)
        self.clr = QPushButton("Clear list")
        self.clr.setObjectName("link")
        self.clr.setCursor(Qt.PointingHandCursor)
        self.clr.clicked.connect(self.clear_recent)
        hr.addWidget(self.clr)
        root.addLayout(hr)
        root.addSpacing(10)
        self.recent_grid = QGridLayout()
        self.recent_grid.setHorizontalSpacing(14)
        self.recent_grid.setVerticalSpacing(14)
        self.recent_grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        root.addLayout(self.recent_grid)
        self.empty = QFrame()
        self.empty.setObjectName("emptyCard")
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(20, 26, 20, 26)
        el.setSpacing(4)
        ei = QLabel()
        ei.setPixmap(icon_pixmap("image", t["muted"], 36))
        ei.setAlignment(Qt.AlignCenter)
        et = QLabel("No projects yet")
        et.setObjectName("emptytitle")
        et.setAlignment(Qt.AlignCenter)
        eb = QLabel("Your recent projects appear here.\nNew to this? Don't worry, this is designed and made to be easy.")
        eb.setObjectName("emptybox")
        eb.setAlignment(Qt.AlignCenter)
        for w in (ei, et, eb):
            el.addWidget(w)
        root.addWidget(self.empty)
        root.addSpacing(20)
        tr = QHBoxLayout()
        th = QLabel("Start from a template")
        th.setObjectName("head")
        tr.addWidget(th)
        tr.addStretch()
        more = QPushButton("Browse all templates")
        more.setObjectName("link")
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(self.template)
        tr.addWidget(more)
        root.addLayout(tr)
        root.addSpacing(10)
        self.tpl_row = QHBoxLayout()
        self.tpl_row.setSpacing(14)
        self.tpl_row.addStretch()
        root.addLayout(self.tpl_row)
        root.addStretch()
        self.refill()
        QTimer.singleShot(60, self.load_templates)

    def load_templates(self):
        """A few template pictures along the bottom (drawn after the window is up, so it opens instantly)."""
        seen, picks = set(), []
        for tpl in TEMPLATES:
            if tpl["cat"] not in seen:
                seen.add(tpl["cat"])
                picks.append(tpl)
            if len(picks) == 3:
                break
        while self.tpl_row.count() > 1:
            it = self.tpl_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for tpl in picks:
            try:
                pm = self.main.template_pixmap(tpl, H=190).scaled(524, 188, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm.setDevicePixelRatio(2)
            except Exception:
                pm = None
            c = TemplateCard(tpl, pm)
            c.clicked.connect(lambda checked=False, t_=tpl: self.finish(("template", t_)))
            self.tpl_row.insertWidget(self.tpl_row.count() - 1, c)

    def tips(self):
        QMessageBox.information(self, "Quick tips", "1. Click New project, choose a slide size and how many slides.\n"
                                "2. Add photos, videos and text from the tool bar on the left.\n"
                                "3. Drag a photo across the pink dashed lines: it continues into the next slide.\n"
                                "4. Double-click text to edit. Right-click anything for more options.\n"
                                "5. Press Export when you are done: every slide is saved in order.")

    def settings(self):
        SettingsDialog(self.main).exec()
        self.restyle()

    def about(self):
        d = SettingsDialog(self.main)
        d.go_to(3)
        d.exec()
        self.restyle()

    def restyle(self):
        self.setStyleSheet(self.make_style())

    def card_menu(self, card, pos):
        m = QMenu(self)
        m.addAction("Open", lambda: self.finish(("open", card.path)))
        m.addAction("Remove from list", lambda: self.remove_recent(card.path))
        m.exec(card.mapToGlobal(pos))

    def remove_recent(self, path):
        cur = [x for x in recent_projects() if Path(x) != Path(path)]
        QSettings("AeroPhotoEditor", "Editor").setValue("recent", cur)
        self.refill()

    @staticmethod
    def thumb_icon(tp, W=400, H=224, r=18):
        """Project picture cropped to a 16:9 card with rounded corners."""
        src = QPixmap(str(tp))
        if src.isNull():
            return placeholder_icon()
        src = src.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        out = QPixmap(W, H)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, W, H), r, r)
        p.setClipPath(path)
        p.drawPixmap((W - src.width()) // 2, (H - src.height()) // 2, src)
        p.setClipping(False)
        p.setPen(QPen(QColor(128, 128, 140, 70), 2))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), r, r)
        p.end()
        return QIcon(out)

    def refill(self):
        while self.recent_grid.count():
            it = self.recent_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rec = recent_projects()
        self.recent_all = getattr(self, "recent_all", False)
        shown = rec if self.recent_all else rec[:4]
        self.show_all.setVisible(len(rec) > 4)
        self.show_all.setText("Show fewer" if self.recent_all else f"Show all ({len(rec)})")
        for n, pth in enumerate(shown):
            tp = thumb_path(pth)
            ic = self.thumb_icon(tp, 380, 214, 20) if tp.exists() else placeholder_icon()
            pm = ic.pixmap(380, 214).scaled(380, 214, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2)
            try:
                when = "Edited " + rel_time(Path(pth).stat().st_mtime)
            except OSError:
                when = ""
            c = RecentCard(pth, pm, when)
            c.clicked.connect(lambda checked=False, p_=pth: self.finish(("open", p_)))
            c.setContextMenuPolicy(Qt.CustomContextMenu)
            c.customContextMenuRequested.connect(lambda pos, c=c: self.card_menu(c, pos))
            self.recent_grid.addWidget(c, n // 4, n % 4)
        self.empty.setVisible(not rec)
        self.clr.setVisible(bool(rec))

    def toggle_all(self):
        self.recent_all = not getattr(self, "recent_all", False)
        self.refill()

    def clear_recent(self):
        QSettings("AeroPhotoEditor", "Editor").setValue("recent", [])
        self.refill()

    def finish(self, action):
        self.result_action = action
        self.accept()

    def new(self):
        d = NewProjectDialog(self)
        if d.exec() and d.info:
            self.finish(("new", d.info))

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", FILTER)
        if path:
            self.finish(("open", path))

    def template(self):
        d = TemplatesDialog(self.main, self)
        if d.exec() and d.chosen:
            self.finish(("template", d.chosen))

    def perform(self):
        w, a = self.main, self.result_action
        if not a:
            return
        if a[0] == "new":
            w.create_project(a[1], ask=False)
        elif a[0] == "open":
            w.open_path(a[1])
        elif a[0] == "template":
            w.apply_template(a[1], ask=False)


class ClickRow(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class Section(QWidget):
    """Collapsible inspector section: small-caps title with a chevron on the right, the controls below it."""
    def __init__(self, title, expanded=True):
        super().__init__()
        self.title, self.on = title, expanded
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.head = ClickRow()
        self.head.setObjectName("secHeadRow")
        self.head.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(0, 12, 0, 8)
        self.lab = QLabel(title.upper().replace("&&", "&"))
        self.lab.setObjectName("secTitle")
        self.chev = QLabel()
        hl.addWidget(self.lab)
        hl.addStretch()
        hl.addWidget(self.chev)
        self.body = QWidget()
        self.body.setObjectName("plainBody")
        self.body.setStyleSheet("QWidget#plainBody { background: transparent; }")
        self.bl = QVBoxLayout(self.body)
        self.bl.setContentsMargins(0, 0, 0, 14)
        self.bl.setSpacing(8)
        line = QFrame()
        line.setObjectName("secLine")
        line.setFrameShape(QFrame.HLine)
        v.addWidget(self.head)
        v.addWidget(self.body)
        v.addWidget(line)
        self.head.clicked.connect(lambda: self.toggle(not self.on))
        self.toggle(expanded)

    def toggle(self, on):
        self.on = on
        self.body.setVisible(on)
        self.refresh_chev()

    def refresh_chev(self):
        self.chev.setPixmap(icon_pixmap("chevd" if self.on else "chevr", theme_tokens()["muted"], 16))


class LayerDelegate(QStyledItemDelegate):
    """One row of the Layers list: picture, name, kind and size, lock and eye buttons."""
    H = 58

    @staticmethod
    def parts(r):
        eye = QRectF(r.right() - 36, r.center().y() - 14, 28, 28)
        lock = QRectF(r.right() - 68, r.center().y() - 14, 28, 28)
        return eye, lock

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.H)

    def paint(self, p, option, index):
        pal = QApplication.palette()
        text, muted, acc = pal.color(QPalette.WindowText), pal.color(QPalette.PlaceholderText), pal.color(QPalette.Highlight)
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        hidden, locked = bool(index.data(Qt.UserRole + 2)), bool(index.data(Qt.UserRole + 3))
        p.save()
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        sel, hov = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
        if sel or hov:
            bg = QColor(acc)
            bg.setAlpha(46 if sel else 0)
            p.setPen(QPen(QColor(acc.red(), acc.green(), acc.blue(), 150), 1) if sel else Qt.NoPen)
            p.setBrush(bg if sel else pal.color(QPalette.AlternateBase))
            p.drawRoundedRect(r, 11, 11)
        th = QRectF(r.left() + 8, r.center().y() - 20, 40, 40)
        ic = index.data(Qt.DecorationRole)
        if isinstance(ic, QIcon):
            pm = ic.pixmap(80, 80)
            clip = QPainterPath()
            clip.addRoundedRect(th, 9, 9)
            p.save()
            p.setClipPath(clip)
            p.setOpacity(0.4 if hidden else 1.0)
            p.drawPixmap(th, pm, QRectF(pm.rect()))
            p.restore()
            p.setPen(QPen(QColor(128, 128, 140, 60), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(th, 9, 9)
        f = QFont(option.font)
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(muted if hidden else text)
        tx = QRectF(th.right() + 12, r.top() + 9, r.width() - 140, 20)
        p.drawText(tx, Qt.AlignLeft | Qt.AlignVCenter, QFontMetricsF(f).elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, tx.width()))
        f.setPixelSize(11)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(muted)
        p.drawText(QRectF(th.right() + 12, r.top() + 29, r.width() - 140, 18), Qt.AlignLeft | Qt.AlignVCenter, index.data(Qt.UserRole + 1) or "")
        eye, lock = self.parts(r)
        for rect, name, on in ((lock, "lock", locked), (eye, "eyeoff" if hidden else "eye", True)):
            if name == "lock" and not locked and not (hov or sel):
                continue
            col = QColor(acc) if (name == "lock" and locked) else QColor(muted if (name != "lock" or not locked) else text)
            if name == "lock" and not locked:
                col.setAlpha(110)
            p.save()
            p.translate(rect.topLeft() + QPointF(5, 5))
            draw_ui_icon(p, name, col, 18)
            p.restore()
        p.restore()


class LayerClicks(QObject):
    """Clicks on the lock / eye buttons inside the Layers list (the list itself keeps selecting and dragging rows)."""
    def __init__(self, view, on_eye, on_lock):
        super().__init__(view)
        self.view, self.on_eye, self.on_lock = view, on_eye, on_lock
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress and ev.button() == Qt.LeftButton:
            idx = self.view.indexAt(ev.position().toPoint())
            if idx.isValid():
                r = QRectF(self.view.visualRect(idx)).adjusted(2, 2, -2, -2)
                eye, lock = LayerDelegate.parts(r)
                pt = ev.position()
                if eye.contains(pt):
                    self.on_eye(idx.data(Qt.UserRole))
                    return True
                if lock.contains(pt):
                    self.on_lock(idx.data(Qt.UserRole))
                    return True
        return False


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1300, 800)
        self.setContentsMargins(0, 0, 0, 0)
        self.scene = Canvas()
        self.scene.on_change = self.commit
        self.scene.on_transform = lambda: self.sync_controls(False)
        self.scene.on_error = self.video_error
        self.view = View(self.scene)
        self.gpu_active, self.gpu_note = setup_gpu(self.view)
        self.view.on_delete = self.delete_selected
        self.view.on_nudge = lambda dx, dy: self.nudge(dx, dy)
        self.setCentralWidget(self.view)
        self.assets, self.pixmaps = {}, {}   # image id -> file bytes / QPixmap
        self.tex_ids, self.syncing = {}, False
        self.path = None
        self.states, self.pos, self.saved = [], -1, 0
        self.restoring = False
        self.clip, self.paste_n = None, 0
        self.thumbs = {}
        self.crop_state = None
        self.view.on_key = self.crop_key
        self.view.on_context = self.canvas_menu
        self.scene.on_shape_edit = self.shape_panel
        self._build_menus()
        self._build_toolbar()
        self._build_float_bar()
        self._build_side_panel()
        self._build_layers_dock()
        self.crop_panel = CropPanel(self)                      # appears in the right panel only while cropping
        self.crop_dock = QDockWidget("Crop image", self)
        self.crop_dock.setWidget(self.crop_panel)
        self.crop_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.crop_dock.setTitleBarWidget(self._dock_head("Crop")[0])
        self.crop_panel.setObjectName("panelBody")
        self.addDockWidget(Qt.RightDockWidgetArea, self.crop_dock)
        self.tabifyDockWidget(self.side_dock, self.crop_dock)
        self.crop_dock.hide()
        self.scene.selectionChanged.connect(self.sync_controls)
        self.reset_history(DEFAULT)
        self.resizeDocks([self.side_dock, self.layers_dock], [400, 400], Qt.Vertical)
        self.resizeDocks([self.side_dock], [330], Qt.Horizontal)
        self.update_status()
        self.sync_controls(False)
        self.fit()

    # ---------- UI ----------
    def _act(self, menu, text, fn, key=None):
        a = QAction(text, self)
        if key:
            a.setShortcut(key)
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    def fill_text_menu(self, m):
        """Text options: used by the menu bar's Text menu and the toolbar's Text dropdown."""
        self._act(m, "Font...", self.pick_font)
        self._act(m, "Text Color...", self.pick_text_color)
        m.addSeparator()
        for label, key in (("Align Left", "left"), ("Align Center", "center"), ("Align Right", "right"), ("Justify", "justify")):
            self._act(m, label, lambda checked=False, k=key: self.text_align(k))
        m.addSeparator()
        self._act(m, "Line Spacing, Indent && Outline...", self.text_panel)
        for title, entries, fn in (
            ("Text Style", (("Bold", "b"), ("Italic", "i"), ("Underline", "u"), ("Strikethrough", "s")), self.text_style),
            ("Text Box", (("Auto Width", "auto"), ("Manual Width...", "manual")), self.text_box),
        ):
            sub = m.addMenu(title)
            for label, key in entries:
                self._act(sub, label, lambda checked=False, f=fn, k=key: f(k))

    def _build_menus(self):
        self.mbar = QMenuBar()
        self.mbar.setObjectName("mbar")
        self.mbar.setNativeMenuBar(False)
        m = self.mbar.addMenu("&File")
        self._act(m, "New", self.new_project, QKeySequence.New)
        self._act(m, "Open...", self.open_project, QKeySequence.Open)
        self.recent_menu = m.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self.fill_recent_menu)
        self._act(m, "Save", self.save, QKeySequence.Save)
        self._act(m, "Save As...", self.save_as, QKeySequence.SaveAs)
        self._act(m, "Close Project", self.close_project, "Ctrl+W")
        m.addSeparator()
        self._act(m, "Export...", self.export)
        m.addSeparator()
        self._act(m, "Settings...", lambda: SettingsDialog(self).exec())
        e = self.mbar.addMenu("&Edit")
        self._act(e, "Undo", self.undo, QKeySequence.Undo)
        self._act(e, "Redo", self.redo, QKeySequence.Redo)
        e.addSeparator()
        self._act(e, "Copy", self.copy_layers, QKeySequence.Copy)
        self._act(e, "Paste", self.paste_layers, QKeySequence.Paste)
        m = self.mbar.addMenu("&View")
        a = self._act(m, "Zoom In", lambda: self.zoom(1.2))
        a.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+="), QKeySequence("Ctrl+Shift+=")])
        a = self._act(m, "Zoom Out", lambda: self.zoom(1 / 1.2))
        a.setShortcuts([QKeySequence("Ctrl+-"), QKeySequence("Ctrl+_")])
        self._act(m, "Fit View", self.fit, "Ctrl+0")
        m.addSeparator()
        self._act(m, "Full Screen Preview (2 slides)", self.preview_fullscreen, "F11")
        self._act(m, "Toggle Guides", self.toggle_guides)
        m = self.mbar.addMenu("&Insert")
        self._act(m, "Add Image", self.add_image)
        self._act(m, "Add Video", self.add_video)
        self._act(m, "Templates...", self.templates)
        m.addSeparator()
        self._act(m, "Rectangle", lambda: self.add_shape("rect"))
        self._act(m, "Ellipse", lambda: self.add_shape("ellipse"))
        self._act(m, "Line", lambda: self.add_shape("line"))
        self._act(m, "Edit Shape... (opacity, corners, shadow, border)", self.shape_panel)
        self._act(m, "Grid Layouts...", self.add_grid)
        self._act(m, "Grid (plain 2 x 2)", self.add_grid_simple)
        self._act(m, "Overlay (tinted layer over all slides)", self.add_overlay)
        self._act(m, "Play / Pause Videos", self.toggle_video)
        m = self.mbar.addMenu("&Layer")
        self._act(m, "Duplicate", self.duplicate, "Ctrl+D")
        self._act(m, "Center in Slide", self.center_in_slide)
        self._act(m, "Crop Image...", self.crop_image)
        self._act(m, "Replace Image...", self.replace_image)
        self._act(m, "Trim Video Length...", self.trim_video)
        self._act(m, "Fill Grid Cells with Images...", self.fill_grid)
        self._act(m, "Grid Settings...", self.grid_settings)
        self._act(m, "Lock / Unlock", self.toggle_lock, "Ctrl+L")
        for title, entries, fn in (
            ("Arrange", (("Send to Front", "forward"), ("Send to Back", "backward")), self.arrange),
            ("Align to Slide", (("Left", "left"), ("Center", "hcenter"), ("Right", "right"), ("Top", "top"), ("Middle", "vcenter"), ("Bottom", "bottom")), self.align),
            ("Flip", (("Horizontally", "h"), ("Vertically", "v")), self.flip),
        ):
            sub = m.addMenu(title)
            for label, key in entries:
                self._act(sub, label, lambda checked=False, f=fn, k=key: f(k))
        m.addSeparator()
        self._act(m, "Shape Fill Color...", lambda: self.shape_prop("fill"))
        self._act(m, "Shape Border Color...", lambda: self.shape_prop("border"))
        self._act(m, "Shape Border Width...", lambda: self.shape_prop("width"))
        m = self.mbar.addMenu("&Image")
        self._act(m, "Edit Image...", self.edit_image, "Ctrl+E")
        self._act(m, "Crop...", self.crop_image)
        self._act(m, "Crop to Frame (keep size)", lambda: self.crop_image(True))
        self._act(m, "Replace Image...", self.replace_image)
        self.fill_fit_menu(m.addMenu("Fit"))
        m = self.mbar.addMenu("&Text")
        self.fill_text_menu(m)
        m = self.mbar.addMenu("&Background Tools")
        self.fill_bg_menu(m)
        m = self.mbar.addMenu("&Canvas")
        self._act(m, "Background (solid / gradient / texture)...", self.pick_bg)
        self._act(m, "Custom Slide Size...", self.custom_size)

    def _icon_for(self, target, name, on_accent=False):
        self.icon_targets.append((target, name, on_accent))
        self._set_icon(target, name, on_accent)

    def _set_icon(self, target, name, on_accent=False):
        t = theme_tokens()
        ic = ui_icon(name, t["accent_text"], t["accent_text"], t["muted"]) if on_accent else ui_icon(name)
        target.setIcon(ic)

    def refresh_icons(self):
        for sec in self.findChildren(Section):
            sec.refresh_chev()
        for target, name, on_accent in getattr(self, "icon_targets", []):
            try:
                self._set_icon(target, name, on_accent)
            except RuntimeError:
                pass

    def _tool(self, bar, text, name, fn, tip="", checkable=False, checked=False):
        a = QAction(text, self)
        a.setToolTip(tip or text)
        a.setCheckable(checkable)
        if checkable:
            a.setChecked(checked)
            a.toggled.connect(fn)
        else:
            a.triggered.connect(lambda checked=False: fn())
        self._icon_for(a, name)
        bar.addAction(a)
        return a

    def _fbtn(self, name, tip, fn, checkable=False):
        """Small square icon button for the tool options bar."""
        b = QToolButton()
        b.setObjectName("fmt")
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setIconSize(QSize(18, 18))
        self._icon_for(b, name)
        b.clicked.connect(lambda checked=False: fn())
        return b

    def _tbtn(self, text, name, tip, fn, menu=None):
        """Icon + text button for the tool options bar (optionally with a drop-down menu)."""
        b = QToolButton()
        b.setObjectName("fmtText")
        b.setText(text)
        b.setToolTip(tip)
        b.setIconSize(QSize(18, 18))
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._icon_for(b, name)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.InstantPopup)
        else:
            b.clicked.connect(lambda checked=False: fn())
        return b

    def _build_toolbar(self):
        self.icon_targets = []
        self.ctx_sync = False
        # ---- left tool rail: everything you add or change a layer with
        rail = QToolBar("Tools")
        rail.setObjectName("tools")
        rail.setMovable(False)
        rail.setFloatable(False)
        rail.setOrientation(Qt.Vertical)
        rail.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        rail.setIconSize(QSize(22, 22))
        self.addToolBar(Qt.LeftToolBarArea, rail)
        self.rail = rail
        self._tool(rail, "Image", "image", self.add_image, "Add images")
        self._tool(rail, "Video", "video", self.add_video, "Add a video")
        self._tool(rail, "Text", "text", self.add_text, "Add text")
        shapes = QAction("Shapes", self)
        shapes.setToolTip("Rectangle, ellipse, line, overlay")
        sm = QMenu(self)
        for label, fn in (("Rectangle", lambda: self.add_shape("rect")), ("Ellipse", lambda: self.add_shape("ellipse")),
                          ("Line", lambda: self.add_shape("line")), ("Overlay (tinted layer)", self.add_overlay)):
            sm.addAction(label, fn)
        shapes.setMenu(sm)
        self._icon_for(shapes, "shape")
        rail.addAction(shapes)
        rail.widgetForAction(shapes).setPopupMode(QToolButton.InstantPopup)
        self._tool(rail, "Grids", "grid", self.add_grid, "Photo grid layouts")
        self._tool(rail, "Templates", "template", self.templates, "Ready-made carousel templates")
        rail.addSeparator()
        self._tool(rail, "Canvas", "canvas", self.pick_bg, "Slide background: colour, gradient, texture")
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        rail.addWidget(sp)

        # ---- top app bar: home, menus | project name | undo, redo, zoom, preview, export
        top = QWidget()
        top.setObjectName("topbar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 10, 14, 4)
        tl.setSpacing(8)
        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        home = QToolButton()
        home.setObjectName("homeBtn")
        home.setToolTip("Home - back to the start screen")
        home.setIconSize(QSize(32, 32))
        logo = resource_path("assets", "aero_icon_256.png")
        if os.path.exists(logo):
            home.setIcon(QIcon(QPixmap(logo)))
        home.clicked.connect(lambda checked=False: self.close_project())
        ll.addWidget(home)
        self.mbar.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        ll.addWidget(self.mbar)
        ll.addStretch()
        center = QWidget()
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        self.proj_title = QLabel("Untitled")
        self.proj_title.setObjectName("projTitle")
        self.proj_state = QLabel("Saved")
        self.proj_state.setObjectName("chipSaved")
        cl.addWidget(self.proj_title)
        cl.addWidget(self.proj_state)
        right = QWidget()
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addStretch()
        for name, fn, tip in (("undo", self.undo, "Undo (Ctrl+Z)"), ("redo", self.redo, "Redo (Ctrl+Y)")):
            b = QToolButton()
            b.setToolTip(tip)
            b.setIconSize(QSize(20, 20))
            b.clicked.connect(lambda checked=False, f=fn: f())
            self._icon_for(b, name)
            rl.addWidget(b)
        pv = QPushButton(" Preview")
        pv.setObjectName("ghost")
        pv.setToolTip("Full screen preview of two slides (F11)")
        pv.clicked.connect(lambda: self.preview_fullscreen())
        self._icon_for(pv, "play")
        rl.addWidget(pv)
        ex = QPushButton(" Export")
        ex.setObjectName("primary")
        ex.setToolTip("Save every slide as image / video files")
        ex.clicked.connect(lambda: self.export())
        self._icon_for(ex, "export", True)
        rl.addWidget(ex)
        lw, rw = left.sizeHint().width(), right.sizeHint().width()
        left.setMinimumWidth(lw)
        right.setMinimumWidth(rw)
        left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tl.addWidget(left, 1)
        tl.addWidget(center, 0)
        tl.addWidget(right, 1)
        self.setMenuWidget(top)
        self.topbar = top

        # ---- tool options bar: shows what you can do with the selected layer (font, size, alignment, crop, fill ...)
        bar = QToolBar("Options")
        bar.setObjectName("opts")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.opts = bar
        self.ctx = QStackedWidget()
        self.ctx.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        def page(*widgets):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            for x in widgets:
                if x == "|":
                    ln = QFrame()
                    ln.setObjectName("vline")
                    ln.setFixedHeight(20)
                    h.addSpacing(4)
                    h.addWidget(ln)
                    h.addSpacing(4)
                else:
                    h.addWidget(x)
            h.addStretch()
            return w
        hint = QLabel("Nothing selected  -  click a photo, text or shape on the canvas to see its tools here")
        hint.setObjectName("ctxHint")
        self.ctx.addWidget(page(hint))
        # text
        self.c_font = QFontComboBox()
        self.c_font.setMinimumWidth(190)
        self.c_font.setMaxVisibleItems(14)
        self.c_font.setToolTip("Font")
        self.c_font.currentFontChanged.connect(lambda f: self.ctx_font_family(f.family()))
        self.c_size = QSpinBox()
        self.c_size.setRange(4, 600)
        self.c_size.setSuffix(" pt")
        self.c_size.setKeyboardTracking(False)
        self.c_size.setFixedWidth(84)
        self.c_size.setToolTip("Font size")
        self.c_size.valueChanged.connect(self.ctx_font_size)
        self.c_b = self._fbtn("bold", "Bold", lambda: self.text_style("b"), True)
        self.c_i = self._fbtn("italic", "Italic", lambda: self.text_style("i"), True)
        self.c_u = self._fbtn("underline", "Underline", lambda: self.text_style("u"), True)
        self.c_col = QToolButton()
        self.c_col.setObjectName("fmt")
        self.c_col.setToolTip("Text colour")
        self.c_col.clicked.connect(lambda checked=False: self.pick_text_color())
        self.c_al = {}
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for key, name, tip in (("left", "alignl", "Align left"), ("center", "alignc", "Align centre"),
                               ("right", "alignr", "Align right"), ("justify", "alignj", "Justify")):
            b = self._fbtn(name, tip, lambda k=key: self.text_align(k), True)
            grp.addButton(b)
            self.c_al[key] = b
        tm = QMenu(self)
        self.fill_text_menu(tm)
        self.ctx.addWidget(page(self.c_font, self.c_size, "|", self.c_b, self.c_i, self.c_u, self.c_col, "|",
                                *self.c_al.values(), "|", self._tbtn("More", "more", "Line spacing, indent, outline, text box", None, tm)))
        # photo / video / grid
        fm = QMenu(self)
        self.fill_fit_menu(fm)
        bm = QMenu(self)
        self.fill_bg_menu(bm)
        self.c_crop = self._tbtn("Crop", "crop", "Crop the selected photo or video", self.crop_image)
        self.c_replace = self._tbtn("Replace", "replace", "Replace the photo, keeping its size", self.replace_image)
        self.c_filters = self._tbtn("Filters", "adjust", "Filters and adjustments (Ctrl+E)", self.edit_image)
        self.c_fit = self._tbtn("Fit", "fit", "Fill height / width / 2 slides", None, fm)
        self.c_bgtools = self._tbtn("Background", "layers", "Remove background, cut out, erase", None, bm)
        self.c_trim = self._tbtn("Trim", "video", "Trim video length", self.trim_video)
        self.c_snd_on = self._tbtn("Sound on", "volume", "This video's sound is in the export. Click to mute it", lambda: self.set_mute(True))
        self.c_snd_off = self._tbtn("Muted", "mute", "This video is muted in the export. Click to turn its sound on", lambda: self.set_mute(False))
        self.c_fill = self._tbtn("Fill cells", "grid", "Fill the grid cells with photos", self.fill_grid)
        self.c_gset = self._tbtn("Grid settings", "settings", "Rows, columns, gap, corners", self.grid_settings)
        self.c_flipx = self._fbtn("fliph", "Flip horizontally", lambda: self.flip("h"))
        self.c_flipy = self._fbtn("flipv", "Flip vertically", lambda: self.flip("v"))
        self.ctx.addWidget(page(self.c_crop, self.c_replace, self.c_filters, self.c_fit, self.c_bgtools, self.c_trim, self.c_snd_on, self.c_snd_off, self.c_fill,
                                self.c_gset, "|", self.c_flipx, self.c_flipy))
        # shape
        self.c_sfill = self._tbtn("Fill", "shape", "Fill colour", lambda: self.shape_prop("fill"))
        self.c_sborder = self._tbtn("Border", "shape", "Border colour", lambda: self.shape_prop("border"))
        self.c_sedit = self._tbtn("Edit shape", "settings", "Opacity, corners, shadow, border style", self.shape_panel)
        self.ctx.addWidget(page(self.c_sfill, self.c_sborder, self.c_sedit))
        bar.addWidget(self.ctx)
        sp2 = QWidget()
        sp2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(sp2)
        self._tool(bar, "Guides", "guides", lambda on: (setattr(self.scene, "show_guides", on), self.scene.update()),
                   "Show or hide the slide cut guides", True, self.scene.show_guides)
        self._tool(bar, "Snap", "snap", lambda v: setattr(self.scene, "snap_enabled", v), "Snap to slides, layers and angles", True, True)
        # ---- status bar
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.st_info = QLabel("")
        sb.addWidget(self.st_info, 1)
        self.st_gpu = QLabel("")
        sb.addPermanentWidget(self.st_gpu)
        self.zoom_timer = QTimer(self)
        self.zoom_timer.timeout.connect(self.update_zoom_label)
        self.zoom_timer.start(250)

    def _build_float_bar(self):
        """Floating bar at the bottom of the canvas: go to a slide, zoom, fit."""
        bar = QFrame(self.view.viewport())
        bar.setObjectName("floatBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)

        def btn(name, tip, fn):
            b = QToolButton()
            b.setToolTip(tip)
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda checked=False: fn())
            self._icon_for(b, name)
            return b

        def vline():
            ln = QFrame()
            ln.setObjectName("vline")
            ln.setFixedSize(1, 18)
            return ln
        self.st_slide = QLabel("Slide 1 of 1")
        self.st_slide.setMinimumWidth(86)
        self.st_slide.setAlignment(Qt.AlignCenter)
        self.st_zoom = QToolButton()
        self.st_zoom.setToolTip("Click to fit the whole project in the window (Ctrl+0)")
        self.st_zoom.setMinimumWidth(52)
        self.st_zoom.clicked.connect(lambda: self.fit())
        for w in (btn("chevl", "Previous slide", lambda: self.goto_slide(-1)), self.st_slide,
                  btn("chevr", "Next slide", lambda: self.goto_slide(1)), vline(),
                  btn("minus", "Zoom out (Ctrl+-)", lambda: self.zoom(1 / 1.2)), self.st_zoom,
                  btn("plus", "Zoom in (Ctrl++)", lambda: self.zoom(1.2)), vline(),
                  btn("fit", "Fit the whole project (Ctrl+0)", self.fit)):
            lay.addWidget(w)
        sh = QGraphicsDropShadowEffect(bar)
        sh.setBlurRadius(28)
        sh.setOffset(0, 6)
        sh.setColor(QColor(0, 0, 0, 90))
        bar.setGraphicsEffect(sh)
        self.fbar = bar
        bar.adjustSize()
        self.view.on_resize = self.place_float_bar
        self.place_float_bar()

    def place_float_bar(self):
        vp = self.view.viewport()
        self.fbar.adjustSize()
        self.fbar.move((vp.width() - self.fbar.width()) // 2, vp.height() - self.fbar.height() - 18)
        self.fbar.raise_()

    def cur_slide(self):
        sc = self.scene
        c = self.view.mapToScene(self.view.viewport().rect().center())
        col = min(max(int(c.x() // sc.pw), 0), sc.n - 1)
        row = min(max(int(c.y() // sc.ph), 0), sc.rows - 1)
        return row * sc.n + col

    def goto_slide(self, d):
        sc = self.scene
        k = min(max(self.cur_slide() + d, 0), sc.n * sc.rows - 1)
        self.view.centerOn(slide_rect(sc, k).center())

    # ---- tool options: text
    def _text_items(self):
        return [i for i in self.layers_sel() if isinstance(i, TextItem) and not i.data(1)]

    def ctx_font_family(self, fam):
        if self.ctx_sync:
            return
        its = self._text_items()
        for it in its:
            f = it.font()
            f.setFamily(fam)
            it.setFont(f)
            self.relayout(it)
        if its:
            self.commit()

    def ctx_font_size(self, v):
        if self.ctx_sync:
            return
        its = self._text_items()
        for it in its:
            f = it.font()
            f.setPointSize(int(v))
            it.setFont(f)
            self.relayout(it)
        if its:
            self.commit()

    def update_context(self):
        """Show the tools that fit the selected layer and fill them with its current values."""
        if not hasattr(self, "ctx"):
            return
        try:
            it = self.selected()
        except RuntimeError:
            return
        self.ctx_sync = True
        try:
            if it is None or not isinstance(it, LAYERS):
                idx = 0
            elif isinstance(it, TextItem):
                idx = 1
                f = it.font()
                self.c_font.setCurrentFont(f)
                self.c_size.setValue(f.pointSize() if f.pointSize() > 0 else 12)
                self.c_b.setChecked(f.bold())
                self.c_i.setChecked(f.italic())
                self.c_u.setChecked(f.underline())
                set_swatch(self.c_col, it.defaultTextColor().name(QColor.HexArgb))
                (self.c_al.get(it.align) or self.c_al["left"]).setChecked(True)
            elif isinstance(it, ShapeItem):
                idx = 3
                set_swatch(self.c_sfill, "#00000000" if it.no_fill else it.fill.name(QColor.HexArgb))
                set_swatch(self.c_sborder, "#00000000" if it.no_border else it.border.name(QColor.HexArgb))
            else:
                idx = 2
                is_vid = HAS_VIDEO and isinstance(it, VideoItem)
                is_grid = isinstance(it, GridItem)
                is_pic = isinstance(it, QGraphicsPixmapItem)
                for w, on in ((self.c_crop, is_pic or is_vid), (self.c_replace, is_pic), (self.c_filters, True), (self.c_fit, is_pic),
                              (self.c_bgtools, is_pic), (self.c_trim, is_vid), (self.c_snd_on, is_vid and not it.muted),
                              (self.c_snd_off, is_vid and it.muted), (self.c_fill, is_grid), (self.c_gset, is_grid),
                              (self.c_flipx, True), (self.c_flipy, True)):
                    w.setVisible(on)
            self.ctx.setCurrentIndex(idx)
            kind = "" if it is None or not isinstance(it, LAYERS) else self.layer_kind(it).split("  ")[0]
            self.prop_kind.setText(kind if kind else "Canvas")
        finally:
            self.ctx_sync = False

    def update_zoom_label(self):
        try:
            self.st_zoom.setText(f"{int(round(self.view.transform().m11() * 100))}%")
            self.st_slide.setText(f"Slide {self.cur_slide() + 1} of {self.scene.n * self.scene.rows}")
        except RuntimeError:
            self.zoom_timer.stop()

    def update_status(self):
        if not hasattr(self, "st_info"):
            return
        sc = self.scene
        total = sc.n * sc.rows
        self.st_info.setText(f"{sc.pw} \u00d7 {sc.ph} px   \u00b7   {total} slide{'s' if total != 1 else ''}"
                             f"   \u00b7   {len(self.content_items())} layer{'s' if len(self.content_items()) != 1 else ''}")
        self.st_gpu.setText("\u25cf GPU drawing" if getattr(self, "gpu_active", False) else "\u25cb Software drawing")

    def _dock_head(self, title, count=False):
        w = QWidget()
        w.setObjectName("dockHead")
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 0, 12, 0)
        t = QLabel(title)
        t.setObjectName("dockTitle")
        h.addWidget(t)
        h.addStretch()
        c = None
        if count:
            c = QLabel("")
            c.setObjectName("dockCount")
            h.addWidget(c)
        return w, c

    def _build_side_panel(self):
        body = QWidget()
        body.setObjectName("panelBody")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        inner = QWidget()
        inner.setObjectName("plainBody")
        inner.setStyleSheet("QWidget#plainBody { background: transparent; }")
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(14, 4, 14, 12)
        lay.setSpacing(0)
        # ---- Canvas: size, number of slides, background (always available)
        sec = Section("Canvas", True)
        self.sec_canvas = sec
        lab = QLabel("Slide size")
        lab.setObjectName("fieldLab")
        sec.bl.addWidget(lab)
        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.preset.currentTextChanged.connect(self.set_preset)
        sec.bl.addWidget(self.preset)
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(2)
        self.n_spin, self.rows_spin = QSpinBox(), QSpinBox()
        for k, (lb, sp_, fn) in enumerate((("Slides across", self.n_spin, self.set_panels), ("Rows", self.rows_spin, self.set_rows))):
            sp_.setRange(1, 20)
            sp_.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            sp_.valueChanged.connect(fn)
            l_ = QLabel(lb)
            l_.setObjectName("fieldLab")
            g.addWidget(l_, 0, k)
            g.addWidget(sp_, 1, k)
        sec.bl.addLayout(g)
        bgb = QPushButton("  Background...")
        bgb.setToolTip("Solid colour, gradient or texture behind all slides")
        bgb.clicked.connect(lambda: self.pick_bg())
        self._icon_for(bgb, "canvas")
        sec.bl.addWidget(bgb)
        lay.addWidget(sec)
        # ---- selection
        self.prop_hint = QLabel("Select a photo, text, shape or video on the canvas to change its position, size and look. With nothing selected you change the slides here.")
        self.prop_hint.setObjectName("hint")
        self.prop_hint.setWordWrap(True)
        self.prop_hint.setContentsMargins(0, 12, 0, 0)
        lay.addWidget(self.prop_hint)
        self.prop_body = QWidget()
        self.prop_body.setObjectName("plainBody")
        self.prop_body.setStyleSheet("QWidget#plainBody { background: transparent; }")
        pl = QVBoxLayout(self.prop_body)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        st = Section("Transform", True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        self.pos_boxes = {}
        for i, (k, label, lo, hi, suf) in enumerate((("x", "X", -30000, 60000, " px"), ("y", "Y", -30000, 60000, " px"),
                                                      ("w", "Width", 1, 30000, " px"), ("h", "Height", 1, 30000, " px"),
                                                      ("r", "Rotation", -180, 180, "\u00b0"))):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setSuffix(suf)
            sb.setKeyboardTracking(False)
            sb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            sb.setMinimumWidth(60)
            sb.valueChanged.connect(lambda v, k=k: self.apply_pos(k, v))
            self.pos_boxes[k] = sb
            lb = QLabel(label)
            lb.setObjectName("fieldLab")
            grid.addWidget(lb, (i // 2) * 2, i % 2)
            grid.addWidget(sb, (i // 2) * 2 + 1, i % 2)
        st.bl.addLayout(grid)
        note = QLabel("Width and height keep the aspect ratio.")
        note.setObjectName("hint")
        st.bl.addWidget(note)
        pl.addWidget(st)
        sa = Section("Appearance", True)
        self.slider_vals = {}
        self.s_scale = self._slider(sa.bl, "Scale", 2, 1000, self.apply_scale, "%")
        self.s_rot = self._slider(sa.bl, "Rotation", -180, 180, self.apply_rot, "\u00b0")
        self.s_op = self._slider(sa.bl, "Opacity", 5, 100, self.apply_opacity, "%")
        pl.addWidget(sa)
        lay.addWidget(self.prop_body)
        # ---- help
        sh = Section("Tips && shortcuts", False)
        tips = QLabel("Mouse wheel = zoom\nMiddle mouse drag = move the workspace\nDouble-click text to edit it\n"
                      "Drag corner squares to resize, the round handle to rotate (Shift = 15\u00b0 steps)\n"
                      "Moving and resizing snap to slides, layers and angles (hold Alt to bypass)\n"
                      "Right-click a layer for lock, duplicate, delete...\nF11 = full screen preview (Esc leaves)\n"
                      "Del = delete    Ctrl+Z / Ctrl+Y = undo / redo    Ctrl+S = save\nPink dashed lines = slide cuts")
        tips.setObjectName("hint")
        tips.setWordWrap(True)
        sh.bl.addWidget(tips)
        lay.addWidget(sh)
        lay.addStretch()
        self.side_dock = dock = QDockWidget("Properties", self)
        head, self.prop_kind = self._dock_head("Properties", True)
        dock.setTitleBarWidget(head)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setWidget(body)
        body.setMinimumWidth(310)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _slider(self, lay, label, lo, hi, fn, unit=""):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lb = QLabel(label)
        lb.setObjectName("fieldLab")
        lb.setFixedWidth(58)
        val = QLabel("")
        val.setObjectName("val")
        val.setFixedWidth(48)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.valueChanged.connect(fn)
        s.valueChanged.connect(lambda v, s=s: self.show_slider_value(s))
        s.sliderReleased.connect(self.commit)
        row.addWidget(lb)
        row.addWidget(s, 1)
        row.addWidget(val)
        lay.addLayout(row)
        self.slider_vals[s] = (val, unit)
        return s

    def show_slider_value(self, s):
        val, unit = self.slider_vals[s]
        val.setText(f"{s.value()}{unit}")

    # ---------- state snapshot / history ----------
    def content_items(self):
        return [i for i in self.scene.items() if isinstance(i, LAYERS)]

    def item_dict(self, it, z):
        d = {"x": round(it.x(), 2), "y": round(it.y(), 2), "scale": round(it.scale(), 4),
             "rot": round(it.rotation(), 2), "op": round(it.opacity(), 2), "z": z,
             "locked": bool(it.data(1)), "fx": bool(it.data(2)), "fy": bool(it.data(3)), "hidden": bool(it.data(8))}
        if isinstance(it, TextItem):
            d.update(type="text", text=it.toPlainText(), font=it.font().toString(),
                     color=it.defaultTextColor().name(QColor.HexArgb), align=it.align, box_w=it.box_w,
                     line_h=it.line_h, indent=it.indent, outline_w=it.outline_w,
                     outline=it.outline.name(QColor.HexArgb))
        elif isinstance(it, GridItem):
            d.update(type="grid", rows=it.rows, cols=it.cols, w=it.w, h=it.h, gap=it.gap, radius=it.radius,
                     fill=it.fill.name(QColor.HexArgb), ids=list(it.ids), cells=it.cells,
                     adjs=[a or {} for a in it.adjs], crops=list(it.crops), fills=list(it.fills))
        elif isinstance(it, ShapeItem):
            d.update(type="shape", kind=it.kind, w=it.w, h=it.h, bw=it.bw,
                     fill=it.fill.name(QColor.HexArgb), border=it.border.name(QColor.HexArgb),
                     radius=it.radius, corners=list(it.corners), shadow=it.shadow, dash=it.dash,
                     bpos=it.bpos, bjoin=it.bjoin, nofill=it.no_fill, noborder=it.no_border)
        elif HAS_VIDEO and isinstance(it, VideoItem):
            d.update(type="video", path=it.path, w=round(it.size().width(), 1), h=round(it.size().height(), 1),
                     crop=it.crop, adj=it.adj(), trim=list(it.trim) if it.trim else None, muted=it.muted)
        else:
            d.update(type="image", id=it.data(0), adj=json.loads(it.data(5) or "{}"), crop=json.loads(it.data(6) or "null"),
                     mask=it.data(7))
        return d

    def snapshot(self):
        items = [self.item_dict(it, z) for z, it in
                 enumerate(sorted(self.content_items(), key=lambda i: i.zValue()))]
        s = self.scene
        return {"pw": s.pw, "ph": s.ph, "n": s.n, "rows": s.rows, "bg": s.bg.name(), "bg2": s.bg2.name(),
                "bg_mode": s.bg_mode, "bg_angle": s.bg_angle, "bg_tex": s.bg_tex, "items": items}

    def build_item(self, d, scene=None):
        t = d["type"]
        if t == "text":
            it = TextItem(d["text"])
            f = QFont()
            f.fromString(d["font"])
            it.setFont(f)
            it.setDefaultTextColor(QColor(d["color"]))
            it.align, it.box_w = d.get("align", "left"), d.get("box_w", 0)
            it.line_h, it.indent, it.outline_w = d.get("line_h", 100), d.get("indent", 0), d.get("outline_w", 0)
            it.outline = QColor(d.get("outline", "#000000"))
            it.apply_layout()
        elif t == "grid":
            ids = d.get("ids") or []
            it = GridItem(d["rows"], d["cols"], d["w"], d["h"], d["gap"], d["radius"], d["fill"],
                          ids, [self.pixmaps.get(i) for i in ids])
            if d.get("cells"):
                it.set_cells(d["cells"])
            if d.get("fills"):
                it.fills = (list(d["fills"]) + [None] * it.count())[:it.count()]
            if d.get("adjs") or d.get("crops"):
                it.adjs = (list(d.get("adjs") or []) + [{}] * it.count())[:it.count()]
                it.crops = (list(d.get("crops") or []) + [None] * it.count())[:it.count()]
                for k in range(it.count()):
                    if it.ids[k] and (it.adjs[k] or it.crops[k]):
                        it.pms[k] = self.cell_pixmap(it, k)
        elif t == "shape":
            it = ShapeItem(d["kind"], d["w"], d["h"], d["fill"], d["border"], d["bw"])
            it.radius, it.corners = d.get("radius", 0), list(d.get("corners", [True] * 4))
            it.dash, it.bpos, it.bjoin = d.get("dash", "solid"), d.get("bpos", "center"), d.get("bjoin", "miter")
            it.no_fill, it.no_border = d.get("nofill", False), d.get("noborder", False)
            it.set_shadow(d.get("shadow", False))
        elif t == "video":
            if not HAS_VIDEO:
                return
            it = VideoItem(d["path"], QSizeF(d["w"], d["h"]), crop=d.get("crop"), adj=d.get("adj"), trim=d.get("trim"), muted=d.get("muted", False))
        else:
            pm = self.pixmaps.get(d["id"])
            if pm is None:
                return
            it = QGraphicsPixmapItem(pm)
            it.setTransformationMode(Qt.SmoothTransformation)
            it.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
            it.setData(0, d["id"])
            it.setData(5, json.dumps(d.get("adj") or {}))
            it.setData(6, json.dumps(d.get("crop")))
            it.setData(7, d.get("mask"))
            self.refresh_image(it)
        it.setFlags(QGraphicsPixmapItem.ItemIsMovable | QGraphicsPixmapItem.ItemIsSelectable)
        it.setTransformOriginPoint(it.boundingRect().center())
        it.setPos(d["x"], d["y"])
        it.setScale(d["scale"])
        it.setRotation(d["rot"])
        it.setOpacity(d["op"])
        it.setZValue(d["z"])
        self.set_locked(it, d.get("locked", False))
        if d.get("hidden"):
            it.setData(8, True)
            it.setVisible(False)
        it.setData(2, d.get("fx", False))
        it.setData(3, d.get("fy", False))
        apply_flip(it)
        (scene or self.scene).addItem(it)
        return it

    def restore(self, snap):
        if self.crop_state:                      # the layers are about to be rebuilt: drop crop mode silently
            self.crop_state = None
            self.scene.crop_overlay = None
            self.crop_dock.hide()
        self.restoring = True
        if getattr(self, "adj_panel", None):
            self.adj_panel.close()
        s = self.scene
        s.clear()
        s.pw, s.ph, s.n = snap["pw"], snap["ph"], snap["n"]
        s.bg = QColor(snap["bg"])
        s.rows, s.bg2 = snap.get("rows", 1), QColor(snap.get("bg2", "#7b5cff"))
        s.bg_angle, s.bg_mode, s.bg_tex = snap.get("bg_angle", 0), snap.get("bg_mode", "solid"), snap.get("bg_tex")
        s.tex_pm = self.pixmaps.get(s.bg_tex) if s.bg_tex else None
        s.resize_canvas()
        for d in snap["items"]:
            self.build_item(d)
        for w in (self.n_spin, self.rows_spin, self.preset):
            w.blockSignals(True)
        self.n_spin.setValue(s.n)
        self.rows_spin.setValue(s.rows)
        for name, size in PRESETS.items():
            if size == (s.pw, s.ph):
                self.preset.setCurrentText(name)
        for w in (self.n_spin, self.rows_spin, self.preset):
            w.blockSignals(False)
        self.restoring = False

    def reset_history(self, snap):
        self.restore(snap)
        self.states, self.pos, self.saved = [self.snapshot()], 0, 0
        self.update_title()

    def commit(self):
        if self.restoring or self.scene.exporting or self.crop_state:
            return
        snap = self.snapshot()
        if self.pos >= 0 and snap == self.states[self.pos]:
            return
        del self.states[self.pos + 1:]
        self.states.append(snap)
        self.pos += 1
        if len(self.states) > 100:
            self.states.pop(0)
            self.pos -= 1
            self.saved -= 1
        self.update_title()

    def undo(self):
        if self.crop_state:
            self.end_crop(False)
            return
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem) and fi.hasFocus():
            fi.document().undo()   # undo typing inside the text box first
            return
        if self.pos > 0:
            self.pos -= 1
            self.restore(self.states[self.pos])
            self.update_title()

    def redo(self):
        if self.crop_state:
            self.end_crop(False)
            return
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem) and fi.hasFocus():
            fi.document().redo()
            return
        if self.pos < len(self.states) - 1:
            self.pos += 1
            self.restore(self.states[self.pos])
            self.update_title()

    def dirty(self):
        return self.pos != self.saved

    def update_title(self):
        name = Path(self.path).name if self.path else "Untitled"
        self.setWindowTitle(f"{name}{'*' if self.dirty() else ''} - Aero")
        if hasattr(self, "proj_title"):
            self.proj_title.setText(Path(self.path).stem if self.path else "Untitled project")
            dirty = self.dirty()
            self.proj_state.setText(("Unsaved changes" if self.path else "Not saved yet") if dirty else "Saved")
            self.proj_state.setObjectName("chipDirty" if dirty else "chipSaved")
            self.proj_state.style().unpolish(self.proj_state)
            self.proj_state.style().polish(self.proj_state)
        self.update_context()
        self.update_status()
        if hasattr(self, "layer_list") and not self.syncing:
            self.refresh_layers()

    # ---------- project files ----------
    def maybe_save(self):
        if not self.dirty():
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save changes to this project?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_project(self):
        d = NewProjectDialog(self)
        if d.exec() and d.info:
            self.create_project(d.info)

    def create_project(self, info, ask=True):
        """Start an empty project of the chosen size and save it right away at the chosen name / location."""
        if ask and not self.maybe_save():
            return
        self.assets, self.pixmaps, self.path = {}, {}, None
        w, h = info["size"]
        self.reset_history(dict(DEFAULT, pw=w, ph=h, n=info["n"], items=[]))
        self.fit()
        self.write(info["path"])

    def close_project(self):
        """Back to the opening menu (new project / open / templates / recent projects)."""
        if not self.maybe_save():
            return
        if self.crop_state:
            self.end_crop(True)
        self.hide()
        start = StartScreen(self)
        if start.exec() == QDialog.Accepted:
            start.perform()
            self.show()
            self.raise_()
            self.activateWindow()
        else:                                         # X on the opening menu closes the application
            self.quitting = True
            QApplication.quit()

    def save(self):
        return self.write(self.path) if self.path else self.save_as()

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "", FILTER)
        if not path:
            return False
        if not path.endswith(".carousel"):
            path += ".carousel"
        return self.write(path)

    def write(self, path):
        if self.crop_state:
            self.end_crop(True)
        snap = self.snapshot()
        ids = {d["id"] for d in snap["items"] if d["type"] == "image"}
        ids.update(d["mask"] for d in snap["items"] if d["type"] == "image" and d.get("mask"))
        for d in snap["items"]:
            if d["type"] == "grid":
                ids.update(i for i in d["ids"] if i)
        if snap.get("bg_tex"):
            ids.add(snap["bg_tex"])
        data = {"version": 1, "canvas": snap,
                "assets": {i: base64.b64encode(self.assets[i]).decode() for i in ids if i in self.assets}}
        try:
            Path(path).write_text(json.dumps(data), encoding="utf-8")
        except OSError as ex:
            QMessageBox.critical(self, "Save failed", str(ex))
            return False
        self.path, self.saved = path, self.pos
        self.update_title()
        add_recent(path)
        self.save_thumb(path)
        return True

    def open_project(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            snap = data["canvas"]
            assets = {k: base64.b64decode(v) for k, v in data.get("assets", {}).items()}
            pixmaps = {}
            for k, b in assets.items():
                pixmaps[k] = to_pixmap(b)
        except (OSError, KeyError, ValueError) as ex:
            QMessageBox.critical(self, "Open failed", f"Not a valid project file.\n{ex}")
            return
        self.assets, self.pixmaps, self.path = assets, pixmaps, path
        self.reset_history(snap)
        self.fit()
        add_recent(path)
        self.save_thumb(path)

    def closeEvent(self, e):
        """X on the editor: ask to save / discard, then go back to the opening menu (X there closes the app)."""
        if getattr(self, "quitting", False):
            e.accept()
            return
        e.ignore()
        QTimer.singleShot(0, self.close_project)

    # ---------- helpers ----------
    def selected(self):
        s = self.scene.selectedItems()
        return s[0] if s else None

    def view_center(self):
        return self.view.mapToScene(self.view.viewport().rect().center())

    def fit(self):
        self.view.fitInView(self.scene.canvas_rect().adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)

    # ---------- actions ----------
    def load_image(self, f):
        try:
            raw = read_image(f)
        except ImportError:
            QMessageBox.warning(self, "HEIC support", "HEIC photos need two extra packages:\n\npip install pillow pillow-heif")
            return None
        except Exception as ex:
            QMessageBox.warning(self, "Can't open image", f"{Path(f).name}\n{ex}")
            return None
        pm = to_pixmap(raw)
        return (raw, pm) if not pm.isNull() else None

    def video_error(self, msg):
        QMessageBox.warning(self, "Video problem", msg + "\n\nH.264 and HEVC/H.265 (iPhone) videos normally play "
                            "through Qt's built-in FFmpeg backend. If this one doesn't, run: pip install -U PySide6. "
                            "On Windows you can also install 'HEVC Video Extensions' from the Microsoft Store.")

    def add_image(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add images", "", "Images (" + IMG_EXT + ")")
        for f in files:
            res = self.load_image(f)
            if not res:
                continue
            raw, pm = res
            iid = uuid.uuid4().hex[:10]
            self.assets[iid], self.pixmaps[iid] = raw, pm
            it = QGraphicsPixmapItem(pm)
            it.setData(0, iid)
            it.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
            it.setTransformationMode(Qt.SmoothTransformation)
            it.setScale(min(1.0, 0.8 * self.scene.pw / pm.width()))
            self.scene.add_item(it, self.view_center())
        self.commit()

    def add_text(self):
        it = TextItem("Double-click to edit")
        f = it.font()
        f.setPointSize(60)
        f.setBold(True)
        it.setFont(f)
        it.setDefaultTextColor(QColor("black"))
        it.box_w = int(self.scene.pw * 0.8)
        it.apply_layout()
        self.scene.add_item(it, self.view_center())
        self.commit()

    def pick_font(self):
        it = self.selected()
        if isinstance(it, TextItem) and not self.is_locked(it):
            ok, font = QFontDialog.getFont(it.font(), self)
            if ok:
                it.setFont(font)
                self.relayout(it)
                self.commit()

    def pick_text_color(self):
        it = self.selected()
        if isinstance(it, TextItem) and not self.is_locked(it):
            c = QColorDialog.getColor(it.defaultTextColor(), self)
            if c.isValid():
                it.setDefaultTextColor(c)
                self.commit()

    def sync_pos(self, it):
        if not isinstance(it, LAYERS):
            return
        br, sc = it.boundingRect(), it.scale()
        w, h, c = br.width() * sc, br.height() * sc, it.mapToScene(it.transformOriginPoint())
        vals = {"x": c.x() - w / 2, "y": c.y() - h / 2, "w": w, "h": h, "r": it.rotation()}
        for k, sb in self.pos_boxes.items():
            sb.blockSignals(True)
            sb.setValue(int(round(vals[k])))
            sb.blockSignals(False)

    def apply_pos(self, k, v):
        it = self.selected()
        if not isinstance(it, LAYERS) or it.data(1):
            return
        br, sc = it.boundingRect(), it.scale()
        w, h, c = br.width() * sc, br.height() * sc, it.mapToScene(it.transformOriginPoint())
        if k == "x":
            it.moveBy(v - (c.x() - w / 2), 0)
        elif k == "y":
            it.moveBy(0, v - (c.y() - h / 2))
        elif k == "w":
            it.setScale(max(0.02, min(10.0, v / br.width())))
        elif k == "h":
            it.setScale(max(0.02, min(10.0, v / br.height())))
        else:
            it.setRotation(v)
        self.scene.update()
        self.sync_pos(it)
        self.commit()

    def process_image(self, orig, adj, crop, mid=None, preview=False):
        """Original photo -> photo after mask / crop / adjustments (full resolution unless preview)."""
        if not adj and not crop and not mid:
            return orig
        img, W, H = orig.toImage(), orig.width(), orig.height()
        if mid and mid in self.pixmaps:                       # Remove Background / Cut out / Erase result
            mk = self.pixmaps[mid].toImage()
            if mk.size() == img.size():
                img = img.convertToFormat(QImage.Format_ARGB32)
                mp = QPainter(img)
                mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                mp.drawImage(0, 0, mk)
                mp.end()
        if crop:
            x0, y0 = int(crop[0] * W), int(crop[1] * H)
            img = img.copy(x0, y0, max(1, int(crop[2] * W) - x0), max(1, int(crop[3] * H) - y0))
        if adj and np is not None:
            full = img.size()
            if preview and max(full.width(), full.height()) > 1000:
                img = img.scaled(1000, 1000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            rgb, alpha = qimage_to_np(img)
            pm = np_to_pixmap(adjust_rgb(rgb, adj), alpha)
            return pm if pm.size() == full else pm.scaled(full, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return QPixmap.fromImage(img)

    def refresh_image(self, it, preview=False):
        if isinstance(it, CellRef):
            return it.refresh(self, preview)
        if HAS_VIDEO and isinstance(it, VideoItem):
            return it.refresh(preview)
        orig = self.pixmaps.get(it.data(0))
        if orig is None:
            return
        adj, crop = json.loads(it.data(5) or "{}"), json.loads(it.data(6) or "null")
        it.setPixmap(self.process_image(orig, adj, crop, it.data(7), preview))

    # ---------- photos inside grids
    def cell_pixmap(self, g, i, preview=False):
        orig = self.pixmaps.get(g.ids[i])
        return None if orig is None else self.process_image(orig, g.adjs[i], g.crops[i], None, preview)

    def rebuild_cell(self, g, i, preview=False):
        g.pms[i] = self.cell_pixmap(g, i, preview)
        g.update()
        self.scene.update()

    def grid_cell_at(self, g, spos):
        return g.cell_at(g.mapFromScene(spos))

    def edit_cell(self, g, i):
        if np is None:
            QMessageBox.warning(self, "Edit image", "Image adjustments need numpy:\n\npip install numpy")
            return
        self.adj_panel = AdjustPanel(self, CellRef(g, i))
        self.adj_panel.show()

    def crop_cell(self, g, i):
        """Crop one photo of a grid right on the canvas (same box, snapping and panel as cropping a slide photo)."""
        if self.crop_state:
            self.end_crop(True)
        iid = g.ids[i]
        orig = self.pixmaps.get(iid)
        if orig is None or g.data(1):
            return
        W, H = orig.width(), orig.height()
        cr = g.cell_rect(i)
        crop = g.crops[i]
        if crop is None:                                     # what the cell shows now: the centred cover-fit region
            b = CropBox(W, H)
            b.set_ratio(cr.width() / max(cr.height(), 1))
            crop = [round(v, 6) for v in b.c]
        proxy = QGraphicsPixmapItem(orig)
        proxy.setTransformationMode(Qt.SmoothTransformation)
        proxy.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        proxy.setData(0, iid)
        proxy.setData(5, json.dumps(g.adjs[i] or {}))
        proxy.setData(6, json.dumps(crop))
        proxy.cell_ref = (g, i)
        self.refresh_image(proxy)
        proxy.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        proxy.setTransformOriginPoint(proxy.boundingRect().center())
        proxy.setScale(max(0.02, min(10.0, cr.width() * g.scale() / max((crop[2] - crop[0]) * W, 1))))
        proxy.setRotation(g.rotation())
        proxy.setZValue(max([x.zValue() for x in self.scene.items()] + [0]) + 1)
        self.scene.addItem(proxy)
        cur = proxy.mapToScene(proxy.boundingRect().center())
        tgt = g.mapToScene(cr.center())
        proxy.moveBy(tgt.x() - cur.x(), tgt.y() - cur.y())   # the shown region sits exactly on the cell
        g.skip = i
        g.update()
        self.scene.clearSelection()
        proxy.setSelected(True)
        self.crop_image(keep=True)

    def finish_cell_crop(self, proxy, apply, target):
        g, i = proxy.cell_ref
        try:
            if apply:
                g.crops[i] = target
            g.skip = None
            self.rebuild_cell(g, i)
            self.scene.removeItem(proxy)
            g.setSelected(True)
        except RuntimeError:
            pass

    def pick_cell_photo(self, g, i):
        """Replace the photo of a cell (or put one into an empty cell)."""
        f, _ = QFileDialog.getOpenFileName(self, "Photo for this cell", "", "Images (" + IMG_EXT + ")")
        if not f:
            return
        res = self.load_image(f)
        if not res:
            return
        raw, pm = res
        iid = uuid.uuid4().hex[:10]
        self.assets[iid], self.pixmaps[iid] = raw, pm
        g.ids[i], g.pms[i], g.adjs[i], g.crops[i] = iid, pm, {}, None
        g.update()
        self.scene.update()
        self.commit()

    def set_cell_fill(self, g, i, hexcolor):
        g.fills[i] = hexcolor
        g.update()
        self.scene.update()
        self.commit()

    def cell_color(self, g, i):
        cur = QColor(g.fills[i]) if g.fills[i] else QColor(g.fill)
        c = pick_color_transparent(self, cur, "Cell color")
        if c is not None:
            self.set_cell_fill(g, i, c.name(QColor.HexArgb))

    def remove_cell_photo(self, g, i):
        g.ids[i], g.pms[i], g.adjs[i], g.crops[i] = None, None, {}, None
        g.update()
        self.scene.update()
        self.commit()

    def add_text_in_cell(self, g, i):
        """New text sized to the cell: its box is the cell's width and it snaps to the cell's edges / centre."""
        cr = g.mapToScene(g.cell_rect(i)).boundingRect()
        it = TextItem("Your text")
        f = it.font()
        f.setPixelSize(max(24, int(cr.height() * 0.13)))
        f.setBold(True)
        it.setFont(f)
        has_photo = g.pms[i] is not None and not g.pms[i].isNull()
        it.setDefaultTextColor(QColor("white" if has_photo else "#222222"))
        it.align = "center"
        it.box_w = max(60, int(cr.width() * 0.88))
        it.apply_layout()
        self.scene.add_item(it, cr.center())
        it.setRotation(g.rotation())
        self.commit()

    def selected_image(self):
        if self.crop_state:
            self.end_crop(True)
        it = self.selected()
        if isinstance(it, QGraphicsPixmapItem) and it.data(0) in self.pixmaps:
            return it
        QMessageBox.information(self, "Image", "Select an image layer first.")
        return None

    def selected_video(self):
        it = self.selected()
        return it if (HAS_VIDEO and isinstance(it, VideoItem)) else None

    def edit_image(self):
        v = self.selected_video()
        if v is not None:
            return self.edit_video(v)
        it = self.selected_image()
        if not it or self.is_locked(it):
            return
        if np is None:
            QMessageBox.warning(self, "Edit image", "Image adjustments need numpy:\n\npip install numpy")
            return
        self.adj_panel = AdjustPanel(self, it)
        self.adj_panel.show()

    def crop_image(self, keep=False):
        """Crop right on the canvas: box on the photo + a temporary Crop panel on the right.
        keep=True: 'Crop to Frame' - the visible frame keeps its size, only the part shown changes."""
        if self.crop_state:
            self.end_crop(True)
            return
        v = self.selected_video()
        if v is not None:
            return self.crop_video(v)
        it = self.selected_image()
        if not it or self.is_locked(it):
            return
        orig = self.pixmaps[it.data(0)]
        W, H = orig.width(), orig.height()
        old = json.loads(it.data(6) or "null")
        c = old or [0, 0, 1, 1]
        self.crop_state = {"item": it, "old": old, "keep": bool(keep), "box": None, "overlay": None,
                           "frame": ((c[2] - c[0]) * W * it.scale(), (c[3] - c[1]) * H * it.scale()),
                           "center": it.mapToScene(it.transformOriginPoint())}
        self.change_crop(it, old, None)                      # show the whole photo while cropping
        box = CropBox(W, H, c)
        if keep:
            box.ratio = ((c[2] - c[0]) * W) / max((c[3] - c[1]) * H, 1)
        ov = CropOverlay(it, box, self.crop_panel.sync)
        it.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.scene.crop_overlay = ov
        self.crop_state.update(box=box, overlay=ov)
        self.crop_panel.load(box, ov, self.scene.pw / self.scene.ph, keep)
        self.crop_dock.show()
        self.crop_dock.raise_()
        self.scene.update()
        self.statusBar().showMessage("Crop: drag the box on the photo. Enter = apply, Esc = cancel, "
                                     "click away from the photo to apply.", 8000)

    def change_crop(self, it, old, new):
        """Switch an image layer from crop `old` to crop `new` without the visible part jumping."""
        orig = self.pixmaps[it.data(0)]
        o, n = old or [0, 0, 1, 1], new or [0, 0, 1, 1]
        before = it.mapToScene(QPointF((n[0] - o[0]) * orig.width(), (n[1] - o[1]) * orig.height()))
        it.setData(6, json.dumps(new))
        self.refresh_image(it)
        it.setTransformOriginPoint(it.boundingRect().center())
        apply_flip(it)
        after = it.mapToScene(QPointF(0, 0))
        it.moveBy(before.x() - after.x(), before.y() - after.y())

    def end_crop(self, apply=True, only=None):
        st = self.crop_state
        if not st or (only is not None and st is not only):     # `only`: a deferred call meant for an older crop session
            return
        self.crop_state = None                   # commits work again from here on
        it, ov, box = st["item"], st["overlay"], st["box"]
        target = None
        try:
            seam = ov.seam_targets() if (apply and it.scene() is self.scene and not st["keep"]) else {}
            if it.scene() is self.scene:
                new = None if box.is_full() else [round(v, 4) for v in box.c]
                target = new if apply else st["old"]
                self.change_crop(it, None, target)
                if seam:
                    self.seam_fix(it, seam)
                if apply and st["keep"]:         # same frame size as before, centred where it was
                    c = target or [0, 0, 1, 1]
                    orig = self.pixmaps[it.data(0)]
                    s = st["frame"][0] / max((c[2] - c[0]) * orig.width(), 1)
                    it.setScale(max(0.02, min(10.0, s)))
                    now = it.mapToScene(it.transformOriginPoint())
                    it.moveBy(st["center"].x() - now.x(), st["center"].y() - now.y())
                it.setFlag(QGraphicsItem.ItemIsMovable, not it.data(1))
            ov.setParentItem(None)
            if ov.scene() is not None:
                self.scene.removeItem(ov)
            if getattr(it, "cell_ref", None):    # a photo of a grid: hand the crop back to its cell
                self.finish_cell_crop(it, apply, target if apply else None)
            if getattr(it, "video_ref", None):   # a video: hand the crop back to the video layer
                self.finish_video_crop(it, apply, target)
        except RuntimeError:
            pass                                 # the layer was deleted meanwhile
        self.scene.crop_overlay = None
        self.crop_dock.hide()
        self.scene.update()
        self.sync_controls(False)
        self.commit()

    def seam_fix(self, it, seam):
        """Pixel-exact finish: edges that were snapped to a slide edge / neighbour end up exactly on it (no hairline gap)."""
        if abs(it.rotation() % 90) > 0.01 and abs(it.rotation() % 90 - 90) > 0.01:
            return
        for ax in ("v", "h"):                         # 1) scale so a box snapped on both sides fits exactly
            lo, hi = seam.get(ax, (None, None))
            r = it.sceneBoundingRect()
            a0, a1 = (r.left(), r.right()) if ax == "v" else (r.top(), r.bottom())
            if lo is not None and hi is not None and a1 - a0 > 1:
                f = (hi - lo) / (a1 - a0)
                if 0.97 < f < 1.03 and abs(f - 1) > 1e-9:
                    it.setScale(max(0.02, min(10.0, it.scale() * f)))
                    break
        for ax in ("v", "h"):                         # 2) then move so snapped edges sit exactly on their target
            lo, hi = seam.get(ax, (None, None))
            r = it.sceneBoundingRect()
            a0, a1 = (r.left(), r.right()) if ax == "v" else (r.top(), r.bottom())
            d = (lo - a0) if lo is not None else ((hi - a1) if hi is not None else 0.0)
            if d:
                it.moveBy(d, 0) if ax == "v" else it.moveBy(0, d)

    def crop_key(self, key):
        if not self.crop_state:
            return False
        if key == Qt.Key_Escape:
            self.end_crop(False)
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.end_crop(True)
            return True
        return False

    def fit_image(self, mode):
        """Fill Height / Fill Width / Fill Width 2x: scale the image to the slide(s) it sits on and centre it there."""
        if self.crop_state:
            self.end_crop(True)
        sc, done = self.scene, False
        for it in self.layers_sel():
            if not isinstance(it, QGraphicsPixmapItem) or it.data(1):
                continue
            br, c = it.boundingRect(), it.sceneBoundingRect().center()
            col = min(max(int(c.x() // sc.pw), 0), sc.n - 1)
            row = min(max(int(c.y() // sc.ph), 0), sc.rows - 1)
            if mode == "height":
                s, x0, w = sc.ph / br.height(), col * sc.pw, sc.pw
            elif mode == "width":
                s, x0, w = sc.pw / br.width(), col * sc.pw, sc.pw
            else:
                s, x0, w = 2 * sc.pw / br.width(), min(col, max(sc.n - 2, 0)) * sc.pw, 2 * sc.pw
            it.setScale(max(0.02, min(10.0, s)))
            now = it.mapToScene(it.transformOriginPoint())
            it.moveBy(x0 + w / 2 - now.x(), row * sc.ph + sc.ph / 2 - now.y())
            done = True
        if done:
            self.scene.update()
            self.sync_controls(False)
            self.commit()
        else:
            self.statusBar().showMessage("Select an unlocked image first.", 3000)

    def fill_fit_menu(self, m):
        self._act(m, "Fill Height", lambda: self.fit_image("height"))
        self._act(m, "Fill Width", lambda: self.fit_image("width"))
        self._act(m, "Fill Width 2x (2 slides)", lambda: self.fit_image("width2"))

    def zoom(self, f):
        cur = self.view.transform().m11()
        if not 0.02 < cur * f < 30:
            return
        v = self.view
        vw = v.viewport()
        mg = max(2000, int(1.1 * max(vw.width(), vw.height()) / (cur * f)))   # room to scroll so the anchor can hold
        self.scene.setSceneRect(self.scene.canvas_rect().adjusted(-mg, -mg, mg, mg))
        pos = v.viewport().mapFromGlobal(QCursor.pos())
        anchor = v.transformationAnchor()
        v.setTransformationAnchor(QGraphicsView.NoAnchor)
        if v.viewport().rect().contains(pos):         # pointer over the editor: zoom around the pointer
            sp = v.mapToScene(pos)
            v.scale(f, f)
            d = v.mapToScene(pos) - sp
            v.translate(d.x(), d.y())
        else:                                          # pointer elsewhere (Layers, menus...): zoom where it is viewed
            c = QPoint(v.viewport().width() // 2, v.viewport().height() // 2)
            sp = v.mapToScene(c)
            v.scale(f, f)
            d = v.mapToScene(c) - sp
            v.translate(d.x(), d.y())
        v.setTransformationAnchor(anchor)

    def pick_bg(self):
        if not hasattr(self, "bg_panel"):
            self.bg_panel = BackgroundPanel(self)
        self.bg_panel.refresh()
        self.bg_panel.show()
        self.bg_panel.raise_()

    def set_bg_solid(self, c):
        sc = self.scene
        sc.bg, sc.bg_mode = QColor(c), "solid"
        sc.update()
        self.commit()

    def set_bg_gradient(self, c1, c2, ang):
        sc = self.scene
        sc.bg, sc.bg2, sc.bg_angle, sc.bg_mode = QColor(c1), QColor(c2), ang, "gradient"
        sc.update()
        self.commit()

    def _use_texture(self, iid):
        sc = self.scene
        sc.bg_mode, sc.bg_tex, sc.tex_pm = "texture", iid, self.pixmaps[iid]
        sc.update()
        self.commit()

    def set_bg_texture(self, name):
        iid = self.tex_ids.get(name)
        if iid is None or iid not in self.pixmaps:
            base, kind = TEXDEF[name]
            img = make_texture(base, kind)
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            iid = uuid.uuid4().hex[:10]
            self.assets[iid], self.pixmaps[iid], self.tex_ids[name] = bytes(buf.data()), QPixmap.fromImage(img), iid
        self._use_texture(iid)

    def bg_texture_from_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Texture", "", "Images (" + IMG_EXT + ")")
        res = self.load_image(f) if f else None
        if res:
            iid = uuid.uuid4().hex[:10]
            self.assets[iid], self.pixmaps[iid] = res
            self._use_texture(iid)

    # ---------- layers panel
    def _build_layers_dock(self):
        self.layer_refs, self.syncing = [], False
        self.layer_list = QListWidget()
        self.layer_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.layer_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.layer_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layer_list.customContextMenuRequested.connect(self.layer_menu)
        self.layer_list.itemSelectionChanged.connect(self.list_select)
        self.layer_list.model().rowsMoved.connect(lambda *a: QTimer.singleShot(0, self.list_reordered))
        self.layer_list.setObjectName("layers")
        self.layer_list.setIconSize(QSize(40, 40))
        self.layer_list.setSpacing(0)
        self.layer_list.setMouseTracking(True)
        self.layer_list.setItemDelegate(LayerDelegate(self.layer_list))
        self.layer_clicks = LayerClicks(self.layer_list, self.toggle_hidden_k, self.toggle_lock_k)
        body = QWidget()
        body.setObjectName("panelBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 8, 8, 8)
        bl.setSpacing(6)
        self.layer_search = QLineEdit()
        self.layer_search.setObjectName("search")
        self.layer_search.setPlaceholderText("Search layers")
        self.layer_search.setClearButtonEnabled(True)
        self.layer_search.textChanged.connect(lambda *_: self.refresh_layers())
        sic = QLabel(self.layer_search)
        sic.setPixmap(icon_pixmap("search", theme_tokens()["muted"], 16))
        sic.move(10, 8)
        sic.setAttribute(Qt.WA_TransparentForMouseEvents)
        bl.addWidget(self.layer_search)
        chips = QHBoxLayout()
        chips.setSpacing(4)
        self.layer_filter = "all"
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        for key, label in (("all", "All"), ("photo", "Photos"), ("video", "Video"), ("text", "Text"), ("shape", "Shapes")):
            c = QToolButton()
            c.setObjectName("chip")
            c.setText(label)
            c.setCheckable(True)
            c.setChecked(key == "all")
            c.clicked.connect(lambda checked=False, k=key: self.set_layer_filter(k))
            self.chip_group.addButton(c)
            chips.addWidget(c)
        chips.addStretch()
        bl.addLayout(chips)
        bl.addWidget(self.layer_list, 1)
        foot = QFrame()
        foot.setObjectName("layerFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 6, 0, 0)
        fl.setSpacing(2)
        for name, tip, fn in (("front", "Bring to front", lambda: self.arrange("forward")), ("back", "Send to back", lambda: self.arrange("backward")),
                              ("duplicate", "Duplicate (Ctrl+D)", self.duplicate)):
            b = QToolButton()
            b.setToolTip(tip)
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda checked=False, f=fn: f())
            self._icon_for(b, name)
            fl.addWidget(b)
        fl.addStretch()
        b = QToolButton()
        b.setToolTip("Delete (Del)")
        b.setIconSize(QSize(18, 18))
        b.clicked.connect(lambda checked=False: self.delete_selected())
        self._icon_for(b, "trash")
        fl.addWidget(b)
        bl.addWidget(foot)
        body.setMinimumWidth(310)
        self.layers_dock = dock = QDockWidget("Layers", self)
        head, self.layer_count = self._dock_head("Layers", True)
        dock.setTitleBarWidget(head)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setWidget(body)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def set_layer_filter(self, key):
        self.layer_filter = key
        self.refresh_layers()

    def layer_matches(self, it):
        f = getattr(self, "layer_filter", "all")
        if f == "all":
            return True
        if f == "text":
            return isinstance(it, TextItem)
        if f == "shape":
            return isinstance(it, ShapeItem)
        if f == "video":
            return HAS_VIDEO and isinstance(it, VideoItem)
        return not isinstance(it, (TextItem, ShapeItem)) and not (HAS_VIDEO and isinstance(it, VideoItem))

    def layer_label(self, it):
        if isinstance(it, TextItem):
            return it.toPlainText().strip().replace("\n", " ")[:32] or "Text"
        if isinstance(it, ShapeItem):
            return {"rect": "Rectangle", "ellipse": "Ellipse", "line": "Line"}[it.kind]
        if isinstance(it, GridItem):
            return f"Grid ({it.count()} cells)" if it.cells else f"Grid {it.rows}x{it.cols}"
        if HAS_VIDEO and isinstance(it, VideoItem):
            return Path(it.path).name
        return "Image"

    def layer_kind(self, it):
        kind = ("Text" if isinstance(it, TextItem) else "Shape" if isinstance(it, ShapeItem) else "Grid" if isinstance(it, GridItem)
                else "Video" if (HAS_VIDEO and isinstance(it, VideoItem)) else "Image")
        try:
            br, k = it.boundingRect(), it.scale()
            extra = "  \u00b7  Muted" if (HAS_VIDEO and isinstance(it, VideoItem) and it.muted) else ""
            return f"{kind}  \u00b7  {int(br.width() * k)} \u00d7 {int(br.height() * k)} px{extra}"
        except RuntimeError:
            return kind

    def refresh_layers(self):
        self.syncing = True
        self.layer_list.clear()
        self.layer_refs = sorted(self.content_items(), key=lambda i: -i.zValue())
        q = self.layer_search.text().strip().lower() if hasattr(self, "layer_search") else ""
        filt = getattr(self, "layer_filter", "all") != "all"
        self.layer_list.setDragDropMode(QAbstractItemView.NoDragDrop if (q or filt) else QAbstractItemView.InternalMove)
        for k, it in enumerate(self.layer_refs):
            name = self.layer_label(it)
            if q and q not in name.lower() and q not in self.layer_kind(it).lower():
                continue
            if not self.layer_matches(it):
                continue
            li = QListWidgetItem(QIcon(self.layer_icon(it)), name)
            li.setData(Qt.UserRole, k)
            li.setData(Qt.UserRole + 1, self.layer_kind(it))
            li.setData(Qt.UserRole + 2, bool(it.data(8)))
            li.setData(Qt.UserRole + 3, bool(it.data(1)))
            self.layer_list.addItem(li)
            li.setSelected(it.isSelected())
        n = len(self.layer_refs)
        self.layer_count.setText(f"{n} layer{'s' if n != 1 else ''}")
        self.syncing = False

    def toggle_hidden_k(self, k):
        if k is None or not (0 <= k < len(self.layer_refs)):
            return
        it = self.layer_refs[k]
        hide = not it.data(8)
        it.setData(8, hide)
        it.setVisible(not hide)
        if hide:
            it.setSelected(False)
            if HAS_VIDEO and isinstance(it, VideoItem):
                it.pause()
        self.scene.update()
        self.commit()
        self.refresh_layers()

    def toggle_lock_k(self, k):
        if k is None or not (0 <= k < len(self.layer_refs)):
            return
        it = self.layer_refs[k]
        self.set_locked(it, not it.data(1))
        self.scene.update()
        self.sync_controls()
        self.commit()

    def layer_icon(self, it, S=88):
        """Small picture of what the layer looks like (cached for photos)."""
        pm = QPixmap(S, S)
        pm.fill(QColor(70, 70, 78))
        p = QPainter(pm)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        try:
            if isinstance(it, QGraphicsPixmapItem):
                src = it.pixmap()
                key = src.cacheKey()
                th = self.thumbs.get(key)
                if th is None:
                    th = src.scaled(S - 8, S - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    if len(self.thumbs) > 300:
                        self.thumbs.clear()
                    self.thumbs[key] = th
                p.drawPixmap((S - th.width()) // 2, (S - th.height()) // 2, th)
            elif HAS_VIDEO and isinstance(it, VideoItem):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(230, 230, 235))
                p.drawPolygon(QPolygonF([QPointF(S * .38, S * .28), QPointF(S * .38, S * .72), QPointF(S * .72, S * .5)]))
            else:
                br = it.boundingRect()
                k = min((S - 10) / max(br.width(), 1), (S - 10) / max(br.height(), 1))
                p.translate(S / 2, S / 2)
                p.scale(k, k)
                p.translate(-br.center().x(), -br.center().y())
                it.paint(p, QStyleOptionGraphicsItem(), None)
        except Exception:
            pass
        p.end()
        return pm

    def layer_menu(self, pos):
        if self.layer_list.itemAt(pos) is None:
            return
        li = self.layer_list.itemAt(pos)
        k = li.data(Qt.UserRole)
        hit = self.layer_refs[k] if k is not None and 0 <= k < len(self.layer_refs) else None
        if hit is None:
            return
        if not hit.isSelected():
            self.scene.clearSelection()
            hit.setSelected(True)
        menu = QMenu(self)
        self.fill_item_menu(menu, hit)
        menu.exec(self.layer_list.mapToGlobal(pos))

    def canvas_menu(self, gpos, spos):
        """Right-click on the canvas."""
        hit = next((i for i in self.scene.items(spos) if isinstance(i, LAYERS)), None)
        menu = QMenu(self)
        if hit is None:
            menu.addAction("Paste", self.paste_layers).setEnabled(self.clip is not None)
            menu.exec(gpos)
            return
        if not hit.isSelected():
            self.scene.clearSelection()
            hit.setSelected(True)
        cell = self.grid_cell_at(hit, spos) if isinstance(hit, GridItem) else None
        self.fill_item_menu(menu, hit, cell)
        menu.exec(gpos)

    def fill_item_menu(self, menu, hit, cell=None):
        """Type-specific right-click menu, shared by the canvas and the Layers list."""
        sel = self.layers_sel()
        locked = all(i.data(1) for i in sel)
        edit = []
        if isinstance(hit, QGraphicsPixmapItem):
            edit += [menu.addAction("Edit Image...", self.edit_image), menu.addAction("Crop...", self.crop_image),
                     menu.addAction("Crop to Frame (keep size)", lambda: self.crop_image(True)),
                     menu.addAction("Replace Image...", self.replace_image)]
            fit = menu.addMenu("Fit")
            self.fill_fit_menu(fit)
            edit.append(fit.menuAction())
            bg = menu.addMenu("Background Tools")
            self.fill_bg_menu(bg)
            edit.append(bg.menuAction())
        elif HAS_VIDEO and isinstance(hit, VideoItem):
            edit += [menu.addAction("Crop Video...", self.crop_image),
                     menu.addAction("Trim Video Length...", self.trim_video),
                     menu.addAction("Edit Video (Filters)...", self.edit_image),
                     menu.addAction("Play / Pause", self.toggle_video),
                     menu.addAction("Turn sound on" if hit.muted else "Mute this video", lambda: self.set_mute(not hit.muted)),
                     menu.addAction("Sound only from this video", self.solo_sound)]
        elif isinstance(hit, TextItem):
            edit.append(menu.addAction("Text Options...", self.text_panel))
            for label, key in (("Align Left", "left"), ("Align Center", "center"), ("Align Right", "right"), ("Justify", "justify")):
                edit.append(menu.addAction(label, lambda checked=False, k=key: self.text_align(k)))
            st = menu.addMenu("Text Style")
            for label, key in (("Bold", "b"), ("Italic", "i"), ("Underline", "u"), ("Strikethrough", "s")):
                st.addAction(label, lambda checked=False, k=key: self.text_style(k))
            bx = menu.addMenu("Text Box")
            bx.addAction("Auto Width", lambda: self.text_box("auto"))
            bx.addAction("Manual Width...", lambda: self.text_box("manual"))
            edit += [st.menuAction(), bx.menuAction()]
        elif isinstance(hit, ShapeItem):
            edit.append(menu.addAction("Edit Shape...", self.shape_panel))
        elif isinstance(hit, GridItem):
            if cell is not None:
                filled = hit.pms[cell] is not None and not hit.pms[cell].isNull()
                if filled:
                    edit += [menu.addAction("Crop Photo...", lambda: self.crop_cell(hit, cell)),
                             menu.addAction("Edit Photo...", lambda: self.edit_cell(hit, cell)),
                             menu.addAction("Replace Photo...", lambda: self.pick_cell_photo(hit, cell)),
                             menu.addAction("Remove Photo", lambda: self.remove_cell_photo(hit, cell))]
                else:
                    edit.append(menu.addAction("Add Photo Here...", lambda: self.pick_cell_photo(hit, cell)))
                edit.append(menu.addAction("Add Text in This Cell", lambda: self.add_text_in_cell(hit, cell)))
                edit += [menu.addAction("Cell Color...", lambda: self.cell_color(hit, cell)),
                         menu.addAction("Make Cell Transparent", lambda: self.set_cell_fill(hit, cell, "#00000000"))]
                if hit.fills[cell]:
                    edit.append(menu.addAction("Reset Cell Color", lambda: self.set_cell_fill(hit, cell, None)))
                menu.addSeparator()
            edit += [menu.addAction("Fill Grid Cells...", self.fill_grid), menu.addAction("Grid Settings...", self.grid_settings)]
        for a in edit:
            a.setEnabled(not locked and len(sel) == 1)
        if edit:
            menu.addSeparator()
        menu.addAction("Copy", self.copy_layers)
        menu.addAction("Paste", self.paste_layers).setEnabled(self.clip is not None)
        menu.addAction("Duplicate", self.duplicate)
        menu.addAction("Delete", self.delete_selected)
        menu.addSeparator()
        menu.addAction("Unlock" if locked else "Lock", self.toggle_lock)
        ar = menu.addMenu("Arrange")
        for label, key in (("Send to Front", "forward"), ("Send to Back", "backward")):
            ar.addAction(label, lambda checked=False, k=key: self.arrange(k))

    def fill_bg_menu(self, m):
        self._act(m, "Remove Background...", lambda: self.bg_tool("remove"))
        self._act(m, "Cut Out...", lambda: self.bg_tool("cutout"))
        self._act(m, "Erase...", lambda: self.bg_tool("erase"))
        m.addSeparator()
        self._act(m, "Reset Background Edits", self.reset_mask)

    def bg_tool(self, tool):
        it = self.selected_image()
        if not it or self.is_locked(it):
            return
        orig = self.pixmaps[it.data(0)].toImage().convertToFormat(QImage.Format_ARGB32)
        W, H = orig.width(), orig.height()
        k = min(1.0, 1600 / max(W, H))                       # edit at a comfortable size, apply at full size
        ws = QSize(max(1, round(W * k)), max(1, round(H * k)))
        base = orig if k >= 1 else orig.scaled(ws, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        mid = it.data(7)
        if mid and mid in self.pixmaps:
            mask = self.pixmaps[mid].toImage().convertToFormat(QImage.Format_ARGB32)
            if mask.size() != ws:
                mask = mask.scaled(ws, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        else:
            mask = QImage(ws, QImage.Format_ARGB32)
            mask.fill(QColor(255, 255, 255))
        dlg = MaskEditor(self, base, mask.copy(), tool)
        if not dlg.exec() or not dlg.changed:
            return
        new = dlg.mask
        if new.size() != orig.size():
            new = new.scaled(orig.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.apply_mask(it, new)

    def apply_mask(self, it, mask):
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        mask.save(buf, "PNG")
        iid = uuid.uuid4().hex[:10]
        self.assets[iid], self.pixmaps[iid] = bytes(buf.data()), QPixmap.fromImage(mask)
        it.setData(7, iid)
        self.refresh_image(it)
        self.scene.update()
        self.commit()

    def reset_mask(self):
        it = self.selected_image()
        if it and not self.is_locked(it) and it.data(7):
            it.setData(7, None)
            self.refresh_image(it)
            self.scene.update()
            self.commit()

    def list_select(self):
        if self.syncing:
            return
        rows = {i.data(Qt.UserRole) for i in self.layer_list.selectedItems()}
        self.syncing = True
        self.scene.clearSelection()
        for r in rows:
            if r is not None and 0 <= r < len(self.layer_refs):
                self.layer_refs[r].setSelected(True)
        self.syncing = False

    def list_reordered(self):
        order = [self.layer_refs[self.layer_list.item(r).data(Qt.UserRole)] for r in range(self.layer_list.count())]
        for z, it in enumerate(reversed(order)):
            it.setZValue(z)
        self.commit()
        self.refresh_layers()

    # ---------- copy / paste ----------
    def copy_layers(self):
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem) and fi.hasFocus():       # typing in a text box: copy the selected words
            QApplication.clipboard().setText(fi.textCursor().selectedText().replace("\u2029", "\n"))
            return
        sel = sorted(self.layers_sel(), key=lambda i: i.zValue())
        if not sel:
            return
        items = [self.item_dict(it, z) for z, it in enumerate(sel)]
        ids = {d["id"] for d in items if d["type"] == "image"}
        ids.update(d["mask"] for d in items if d["type"] == "image" and d.get("mask"))
        for d in items:
            if d["type"] == "grid":
                ids.update(i for i in d["ids"] if i)
        self.clip = {"items": items, "assets": {i: self.assets[i] for i in ids if i in self.assets}}
        self.paste_n = 0
        self.statusBar().showMessage(f"Copied {len(items)} layer(s)", 3000)

    def paste_layers(self):
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem) and fi.hasFocus():       # typing in a text box: paste plain text
            cur = fi.textCursor()
            cur.insertText(QApplication.clipboard().text())
            fi.setTextCursor(cur)
            return
        if not self.clip:
            return
        for iid, raw in self.clip["assets"].items():         # also works after New / Open
            if iid not in self.pixmaps:
                self.assets[iid], self.pixmaps[iid] = raw, to_pixmap(raw)
        self.paste_n += 1
        off = 40 * self.paste_n
        top = max([i.zValue() for i in self.content_items()] + [0])
        self.scene.clearSelection()
        for k, d0 in enumerate(self.clip["items"]):
            d = json.loads(json.dumps(d0))
            d["x"] += off
            d["y"] += off
            d["z"] = top + 1 + k
            it = self.build_item(d)
            if it is not None:
                it.setSelected(True)
        self.commit()

    # ---------- text format panel ----------
    def text_panel(self):
        if not hasattr(self, "txt_panel"):
            self.txt_panel = TextPanel(self)
        self.txt_panel.refresh()
        self.txt_panel.show()
        self.txt_panel.raise_()

    def relayout(self, it):
        """Re-apply a text layer's formatting and keep its centre where it was."""
        c0 = it.mapToScene(it.transformOriginPoint())
        it.apply_layout()
        it.setTransformOriginPoint(it.boundingRect().center())
        apply_flip(it)
        c1 = it.mapToScene(it.transformOriginPoint())
        it.moveBy(c0.x() - c1.x(), c0.y() - c1.y())

    # ---------- templates / preview / recent ----------
    def template_pixmap(self, t, H=170):
        """Small picture of a whole template (all slides side by side)."""
        snap = template_snapshot(t)
        tmp = Canvas()
        tmp.pw, tmp.ph, tmp.n, tmp.rows = snap["pw"], snap["ph"], snap["n"], 1
        tmp.bg, tmp.bg2, tmp.bg_mode, tmp.bg_angle = QColor(snap["bg"]), QColor(snap["bg2"]), snap["bg_mode"], snap["bg_angle"]
        tmp.exporting = True
        for d in snap["items"]:
            self.build_item(d, tmp)
        k = H / tmp.ph
        img = QImage(int(tmp.n * tmp.pw * k), H, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        tmp.render(p, QRectF(0, 0, img.width(), H), QRectF(0, 0, tmp.n * tmp.pw, tmp.ph))
        p.setPen(QPen(QColor(255, 255, 255, 140), 1, Qt.DashLine))
        for i in range(1, tmp.n):
            p.drawLine(int(i * tmp.pw * k), 0, int(i * tmp.pw * k), H)
        p.end()
        tmp.clear()
        return QPixmap.fromImage(img)

    def save_thumb(self, path):
        """Small picture of the whole carousel, shown in the start screen's Recent Projects."""
        try:
            sc, r = self.scene, self.scene.canvas_rect()
            k = min(560 / r.width(), 170 / r.height())
            w, h = max(1, int(r.width() * k)), max(1, int(r.height() * k))
            img = QImage(w, h, QImage.Format_RGB32)
            img.fill(sc.bg)
            sel, was = list(sc.selectedItems()), (sc.exporting, sc.show_guides)
            sc.clearSelection()
            sc.exporting = True
            p = QPainter(img)
            p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
            sc.render(p, QRectF(0, 0, w, h), r)
            p.end()
            sc.exporting, sc.show_guides = was
            for it in sel:
                it.setSelected(True)
            img.save(str(thumb_path(path)), "PNG")
        except Exception:
            pass

    def templates(self):
        dlg = TemplatesDialog(self, self)
        if dlg.exec() and dlg.chosen:
            self.apply_template(dlg.chosen)

    def apply_template(self, t, ask=True):
        if ask and not self.maybe_save():
            return
        self.assets, self.pixmaps, self.path = {}, {}, None
        self.reset_history(template_snapshot(t))
        self.fit()
        self.statusBar().showMessage(f"Template '{t['name']}' loaded - select a grid, then Layer > Fill Grid Cells with Images.", 9000)

    def preview_fullscreen(self):
        if getattr(self, "preview", None):
            return
        self.preview = PreviewWindow(self)
        self.preview.showFullScreen()
        self.preview.setFocus()
        self.preview.activateWindow()

    def fill_recent_menu(self):
        m = self.recent_menu
        m.clear()
        rec = recent_projects()
        for pth in rec:
            m.addAction(f"{Path(pth).name}   -   {Path(pth).parent}", lambda checked=False, q=pth: self.open_recent(q))
        m.setEnabled(bool(rec))

    def open_recent(self, path):
        if self.maybe_save():
            self.open_path(path)

    # ---------- shapes ----------
    def recenter(self, it):
        """After a size / geometry change: keep the layer's centre where it was."""
        c0 = it.mapToScene(it.transformOriginPoint())
        it.prepareGeometryChange()
        if isinstance(it, TextItem):
            it.apply_layout()
        it.setTransformOriginPoint(it.boundingRect().center())
        apply_flip(it)
        c1 = it.mapToScene(it.transformOriginPoint())
        it.moveBy(c0.x() - c1.x(), c0.y() - c1.y())

    def shape_changed(self, it):
        self.recenter(it)
        it.update()
        self.scene.update()
        self.sync_controls(False)

    def shape_panel(self):
        if not hasattr(self, "shp_panel"):
            self.shp_panel = ShapePanel(self)
        self.shp_panel.refresh()
        self.shp_panel.show()
        self.shp_panel.raise_()

    # ---------- replace image ----------
    def replace_image(self):
        """The new photo goes into the SAME frame: same size, same position. It is auto-cropped (centre) to fill the
        frame; use Crop to Frame to choose which part shows."""
        it = self.selected_image()
        if not it or self.is_locked(it):
            return
        f, _ = QFileDialog.getOpenFileName(self, "Replace image", "", "Images (" + IMG_EXT + ")")
        res = self.load_image(f) if f else None
        if not res:
            return
        if getattr(self, "adj_panel", None):
            self.adj_panel.close()
        raw, pm = res
        iid = uuid.uuid4().hex[:10]
        self.assets[iid], self.pixmaps[iid] = raw, pm
        br, sc = it.boundingRect(), it.scale()
        fw, fh = br.width() * sc, br.height() * sc         # the frame size the user chose - must not change
        old_c = it.mapToScene(it.transformOriginPoint())
        W2, H2 = pm.width(), pm.height()
        s = max(fw / W2, fh / H2)                          # scale that covers the whole frame
        vw, vh = min(1.0, fw / (s * W2)), min(1.0, fh / (s * H2))
        crop = None if vw > 0.999 and vh > 0.999 else [(1 - vw) / 2, (1 - vh) / 2, (1 + vw) / 2, (1 + vh) / 2]
        it.setData(0, iid)
        it.setData(6, json.dumps(crop))
        it.setData(7, None)                                # the old cut-out mask belongs to the old photo
        self.refresh_image(it)                             # keeps filters / adjustments
        nb = it.boundingRect()
        it.setTransformOriginPoint(nb.center())
        it.setScale(max(0.02, min(10.0, fw / max(nb.width(), 1))))   # exact width of the old frame (no rounding drift)
        apply_flip(it)
        new_c = it.mapToScene(it.transformOriginPoint())
        it.moveBy(old_c.x() - new_c.x(), old_c.y() - new_c.y())   # same centre as before
        self.scene.update()
        self.sync_controls()
        self.commit()
        self.statusBar().showMessage("Replaced - the frame keeps its size. Right-click > Crop to Frame to pick which part shows.", 7000)

    # ---------- text alignment / box ----------
    def text_align(self, how):
        its = [i for i in self.layers_sel() if isinstance(i, TextItem) and not i.data(1)]
        widened = False
        for it in its:
            it.align = how
            if it.box_w == 0:                         # an auto-width box is exactly as wide as the text: nothing to align
                it.box_w = max(math.ceil(it.boundingRect().width()), int(self.scene.pw * 0.8))
                widened = True
            self.relayout(it)
        if its:
            self.scene.update()
            self.commit()
            if widened:
                self.statusBar().showMessage("The text box was widened so the alignment shows. "
                                             "Text > Text Box > Auto Width shrinks it back.", 6000)

    def text_box(self, how):
        it = self.selected()
        if not isinstance(it, TextItem) or self.is_locked(it):
            return
        if how == "auto":
            it.box_w = 0
        else:
            cur = it.box_w or it.boundingRect().width()
            w, ok = QInputDialog.getInt(self, "Text box", "Wrap width (px):", int(cur), 50, 20000)
            if not ok:
                return
            it.box_w = w
        self.relayout(it)
        self.scene.update()
        self.sync_controls()
        self.commit()

    # ---------- grid ----------
    def add_grid(self):
        """Insert > Grid: opens the layout picker."""
        d = GridsDialog(self)
        if d.exec() and d.chosen is not None:
            g = GridItem(2, 2, 900, 900, 5, 0)
            g.set_cells(GRID_LAYOUTS[d.chosen])
            self.scene.add_item(g, self.view_center())
            self.commit()

    def add_grid_simple(self):
        self.scene.add_item(GridItem(2, 2, 800, 800), self.view_center())
        self.commit()

    def selected_grid(self):
        it = self.selected()
        if isinstance(it, GridItem):
            return None if self.is_locked(it) else it
        QMessageBox.information(self, "Grid", "Select a grid layer first.")
        return None

    def grid_settings(self):
        g = self.selected_grid()
        if not g:
            return
        dlg = GridDialog(self, g)
        if not dlg.exec():
            return
        s = {k: v.value() for k, v in dlg.sp.items()}
        g.set_dims(s["rows"], s["cols"])
        g.gap, g.radius, g.fill = s["gap"], s["radius"], dlg.color
        g.update()
        self.scene.update()
        self.commit()

    def fill_grid(self):
        g = self.selected_grid()
        if not g:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Photos for the grid", "", "Images (" + IMG_EXT + ")")
        if not files:
            return
        empty = [i for i, x in enumerate(g.ids) if x is None]
        slots = empty if empty else list(range(len(g.ids)))     # fill empty cells first, else start over
        for slot, f in zip(slots, files):
            res = self.load_image(f)
            if not res:
                continue
            raw, pm = res
            iid = uuid.uuid4().hex[:10]
            self.assets[iid], self.pixmaps[iid] = raw, pm
            g.ids[slot], g.pms[slot], g.adjs[slot], g.crops[slot] = iid, pm, {}, None
        if len(files) > len(slots):
            QMessageBox.information(self, "Grid", f"The grid has {len(slots)} free cells; extra photos were skipped.")
        g.update()
        self.scene.update()
        self.commit()

    def add_shape(self, kind):
        it = ShapeItem("line", 600, 40, "#ff5078", "#ff5078", 8) if kind == "line" else \
            ShapeItem(kind, 500, 300 if kind == "rect" else 500)
        self.scene.add_item(it, self.view_center())
        self.commit()

    def add_overlay(self):
        sc = self.scene
        it = ShapeItem("rect", sc.n * sc.pw, sc.rows * sc.ph, QColor(0, 0, 0, 110).name(QColor.HexArgb))
        sc.add_item(it, sc.canvas_rect().center())
        self.commit()

    def shape_prop(self, what):
        it = self.selected()
        if not isinstance(it, ShapeItem) or self.is_locked(it):
            return
        if what == "width":
            w, ok = QInputDialog.getInt(self, "Border width", "Pixels:", int(it.bw), 0, 200)
            if not ok:
                return
            it.prepareGeometryChange()
            it.bw = w
        else:
            c = QColorDialog.getColor(it.fill if what == "fill" else it.border, self, "Color",
                                      QColorDialog.ShowAlphaChannel)
            if not c.isValid():
                return
            if what == "fill":
                it.fill, it.no_fill = c, False
            else:
                it.border, it.no_border = c, False
        it.setTransformOriginPoint(it.boundingRect().center())
        it.update()
        self.commit()

    def add_video(self):
        if not HAS_VIDEO:
            QMessageBox.warning(self, "Video", "Video needs OpenCV and numpy:\n\npip install opencv-python numpy")
            return
        f, _ = QFileDialog.getOpenFileName(self, "Add video", "", "Video (" + VID_EXT + ")")
        if f:
            self.scene.add_item(VideoItem(f, None, int(self.scene.pw * 0.8)), self.view_center())
            self.commit()

    def edit_video(self, v):
        if self.is_locked(v):
            return
        if np is None:
            QMessageBox.warning(self, "Edit video", "Video filters need numpy:\n\npip install numpy")
            return
        self.adj_panel = AdjustPanel(self, v)
        self.adj_panel.setWindowTitle("Edit video")
        self.adj_panel.show()

    def crop_video(self, v):
        """Crop a video right on the canvas: same box, snapping and panel as cropping a photo."""
        if self.is_locked(v):
            return
        poster = v.poster()
        if poster is None:
            QMessageBox.information(self, "Crop video", "The video is still loading - try again in a moment.")
            return
        pm = QPixmap.fromImage(poster)
        if max(pm.width(), pm.height()) > 1600:
            pm = pm.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        W, H = pm.width(), pm.height()
        key = "vidcrop-" + uuid.uuid4().hex[:8]
        self.pixmaps[key] = pm
        crop = v.crop or [0, 0, 1, 1]
        proxy = QGraphicsPixmapItem(pm)
        proxy.setTransformationMode(Qt.SmoothTransformation)
        proxy.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        proxy.setData(0, key)
        proxy.setData(6, json.dumps(v.crop))
        proxy.video_ref = (v, key)
        self.refresh_image(proxy)                            # shows exactly what the video shows now
        proxy.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        proxy.setTransformOriginPoint(proxy.boundingRect().center())
        proxy.setScale(max(0.02, min(10.0, v.size().width() * v.scale() / max((crop[2] - crop[0]) * W, 1))))
        proxy.setRotation(v.rotation())
        proxy.setZValue(v.zValue() + 0.5)
        self.scene.addItem(proxy)
        cur = proxy.mapToScene(proxy.boundingRect().center())
        tgt = v.mapToScene(v.boundingRect().center())
        proxy.moveBy(tgt.x() - cur.x(), tgt.y() - cur.y())
        v.setVisible(False)
        self.scene.clearSelection()
        proxy.setSelected(True)
        self.crop_image()

    def finish_video_crop(self, proxy, apply, target):
        v, key = proxy.video_ref
        try:
            if apply:
                new = None if target is None or target == [0, 0, 1, 1] else list(target)
                size = proxy.boundingRect().size()           # the kept region, in the same units as the proxy
                centre = proxy.mapToScene(proxy.boundingRect().center())
                v.crop = new
                v.setSize(size)
                v.setTransformOriginPoint(v.boundingRect().center())
                v.setScale(proxy.scale())
                v.setRotation(proxy.rotation())
                cur = v.mapToScene(v.boundingRect().center())
                v.moveBy(centre.x() - cur.x(), centre.y() - cur.y())
                v.refresh()
            v.setVisible(True)
            self.scene.removeItem(proxy)
            self.pixmaps.pop(key, None)
            v.setSelected(True)
        except RuntimeError:
            pass

    def trim_video(self):
        v = self.selected_video()
        if v is None:
            QMessageBox.information(self, "Video", "Select a video layer first.")
            return
        if self.is_locked(v):
            return
        d = TrimDialog(self, v)
        if d.exec():
            v.set_trim(d.result_trim())
            self.commit()
        else:
            v.set_trim(d.old)
        v.play()

    def selected_videos(self):
        return [i for i in self.scene.selectedItems() if HAS_VIDEO and isinstance(i, VideoItem)]

    def set_mute(self, on):
        """Mute (or unmute) the selected videos: a muted video adds no sound to the exported slide."""
        vids = self.selected_videos()
        if not vids:
            return
        for v in vids:
            v.muted = on
        self.commit()
        self.refresh_layers()
        self.sync_controls()
        self.statusBar().showMessage("Muted: its sound will not be in the exported slide." if on
                                     else "Sound on: its sound will be in the exported slide.", 4000)

    def solo_sound(self):
        """Keep the sound of the selected video and mute every other video that shares a slide with it."""
        vids = self.selected_videos()
        if not vids:
            return
        keep = set(vids)
        vmap = video_slide_map(self.scene)
        n = 0
        for lst in vmap.values():
            if any(v in keep for v in lst):
                for v in lst:
                    if v not in keep and not v.muted:
                        v.muted = True
                        n += 1
        for v in keep:
            v.muted = False
        self.commit()
        self.refresh_layers()
        self.sync_controls()
        self.statusBar().showMessage(f"Only the selected video has sound now ({n} other video(s) muted).", 5000)

    def toggle_video(self):
        if HAS_VIDEO:
            for it in self.content_items():
                if isinstance(it, VideoItem):
                    it.toggle_play()

    def layers_sel(self):
        return [i for i in self.scene.selectedItems() if isinstance(i, LAYERS)]

    def set_locked(self, it, v):
        """Locked = cannot be moved, resized, rotated, edited or deleted until unlocked."""
        it.setData(1, bool(v))
        it.setFlag(QGraphicsItem.ItemIsMovable, not v)
        if isinstance(it, TextItem) and v:
            it.setTextInteractionFlags(Qt.NoTextInteraction)

    def is_locked(self, it, warn=True):
        if it is not None and it.data(1):
            if warn:
                self.statusBar().showMessage("This layer is locked. Right-click it and choose Unlock to edit it.", 4000)
            return True
        return False

    def toggle_lock(self):
        sel = self.layers_sel()
        if not sel:
            return
        lock = not all(i.data(1) for i in sel)          # everything locked -> unlock, otherwise lock all
        for it in sel:
            self.set_locked(it, lock)
        self.scene.update()
        self.sync_controls()
        self.commit()
        self.statusBar().showMessage("Locked" if lock else "Unlocked", 2500)

    def arrange(self, how):
        it = self.selected()
        if not it:
            return
        items = sorted(self.content_items(), key=lambda i: i.zValue())
        i = items.index(it)
        items.pop(i)
        # "Send to Front" / "Send to Back" move the layer ONE step through the stack
        items.insert({"forward": min(i + 1, len(items)), "backward": max(i - 1, 0)}[how], it)
        for z, x in enumerate(items):
            x.setZValue(z)
        self.commit()

    def align(self, mode):
        sc = self.scene
        for it in self.layers_sel():
            if it.data(1):
                continue
            r = it.sceneBoundingRect()
            c = r.center()
            L = min(max(int(c.x() // sc.pw), 0), sc.n - 1) * sc.pw
            T = min(max(int(c.y() // sc.ph), 0), sc.rows - 1) * sc.ph
            dx = {"left": L - r.left(), "hcenter": L + sc.pw / 2 - c.x(), "right": L + sc.pw - r.right()}.get(mode, 0)
            dy = {"top": T - r.top(), "vcenter": T + sc.ph / 2 - c.y(), "bottom": T + sc.ph - r.bottom()}.get(mode, 0)
            it.moveBy(dx, dy)
        sc.update()
        self.commit()

    def flip(self, axis):
        for it in self.layers_sel():
            if it.data(1):
                continue
            key = 2 if axis == "h" else 3
            it.setData(key, not it.data(key))
            apply_flip(it)
        self.scene.update()
        self.commit()

    def nudge(self, dx, dy):
        moved = [it for it in self.layers_sel() if not it.data(1)]
        for it in moved:
            it.moveBy(dx, dy)
        if moved:
            self.scene.update()
            self.commit()

    def text_style(self, kind):
        it = self.selected()
        if isinstance(it, TextItem) and not self.is_locked(it):
            f = it.font()
            if kind == "b":
                f.setBold(not f.bold())
            elif kind == "i":
                f.setItalic(not f.italic())
            elif kind == "u":
                f.setUnderline(not f.underline())
            else:
                f.setStrikeOut(not f.strikeOut())
            it.setFont(f)
            self.relayout(it)
            self.commit()

    def prepare_videos(self, vmap):
        """Read every video on the canvas once: frames, fps, kept range, sound. Returns (infos, fps, frames, error)."""
        infos = {}
        for k in sorted(vmap):
            for v in vmap[k]:
                if v in infos:
                    continue
                cap = cv2.VideoCapture(v.path)
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                fps_v = cap.get(cv2.CAP_PROP_FPS) or 30.0
                ok = cap.isOpened() and n > 0 and int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) > 0
                cap.release()
                if not ok:
                    return None, 0, 0, (f"Could not read {Path(v.path).name}. HEVC / H.265 videos may need the Microsoft "
                                        f"'HEVC Video Extensions' from the Microsoft Store.")
                a, b = (int(v.trim[0] / 1000.0 * fps_v), int(v.trim[1] / 1000.0 * fps_v)) if v.trim else (0, n)
                a = min(max(a, 0), n - 1)
                b = min(max(b, a + 1), n)
                infos[v] = {"v": v, "n": n, "fps": fps_v, "a": a, "b": b, "audio": probe_audio(FFMPEG, v.path)}
        fps = max(i["fps"] for i in infos.values())
        frames = max(1, min(int(round(max((i["b"] - i["a"]) / i["fps"] for i in infos.values()) * fps)), int(fps * 600)))
        return infos, fps, frames, None

    def render_video_slides(self, folder, ex, vmap, infos, fps, total, progress, base, limits):
        """Export every slide in vmap as slide_NN.mp4, one slide at a time (one encoder in memory, not many).
        Returns (number done, error text or None, info text)."""
        sc = self.scene
        fs = fps_str(fps)
        OW, OH = int(sc.pw * ex) // 2 * 2, int(sc.ph * ex) // 2 * 2
        auds = {k: [infos[v] for v in vmap[k] if infos[v]["audio"] and not v.muted] for k in vmap}
        gpu = bool(getattr(limits, "gpu", False))
        level, log = preflight_encoder(FFMPEG, next((a for a in auds.values() if a), []), fs, folder, gpu, (OW, OH))
        if level is None:
            return 0, ("The video encoder could not start.\n\nffmpeg: " + str(FFMPEG) + "\n\n" + "\n".join(log)), ""
        all_vids = list(infos)
        old_guides = sc.show_guides
        sc.clearSelection()
        sc.exporting, sc.show_guides = True, False
        for v in all_vids:
            v.pause()
            v.setVisible(False)
        slides = sorted(vmap)
        done_n, err, canceled = 0, None, False
        try:
            for si, k in enumerate(slides):
                if progress.canceled():
                    canceled = True
                    break
                out = Path(folder) / f"slide_{k + 1:02d}.mp4"
                ef = tempfile.TemporaryFile()
                pc = run_hidden(encoder_cmd(FFMPEG, OW, OH, fs, auds[k], out, level, limits.threads),
                                low_priority=limits.low_priority, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=ef)
                caps, proxies, pool = {}, [], None
                try:
                    for v in vmap[k]:
                        i = dict(infos[v])
                        i["cap"], i["last"] = cv2.VideoCapture(v.path), -2
                        tw, th = max(1, int(round(v.size().width() * ex))), max(1, int(round(v.size().height() * ex)))
                        i["tw"], i["th"] = tw, th
                        pr = QGraphicsPixmapItem(QPixmap(tw, th))
                        pr.setTransformOriginPoint(QPointF(tw / 2, th / 2))
                        pr.setScale(v.scale() * v.size().width() / tw)
                        pr.setRotation(v.rotation())
                        pr.setOpacity(v.opacity())
                        pr.setZValue(v.zValue())
                        pr.setPos(v.pos())
                        sc.addItem(pr)
                        cur = pr.mapToScene(pr.boundingRect().center())
                        tgt = v.mapToScene(v.boundingRect().center())
                        pr.moveBy(tgt.x() - cur.x(), tgt.y() - cur.y())
                        i["pr"] = pr
                        proxies.append(pr)
                        caps[v] = i
                    img = QImage(OW, OH, QImage.Format_RGB32)
                    nbytes = OW * OH * 4
                    # frames are decoded in order here, but the filters (the slow part) run on several worker threads at once,
                    # a few frames ahead of the one being drawn; the result is identical to doing it one by one.
                    nw = video_workers(limits, [(i["tw"], i["th"]) for i in caps.values()], any(i["v"].adj() for i in caps.values()))
                    pool = ThreadPoolExecutor(nw)
                    depth = nw + 2
                    for i in caps.values():
                        i.update(nxt=0, sub_idx=-2, sub_fut=None, futs={}, shown=None, adj=i["v"].adj())
                    for fi in range(total):
                        for i in caps.values():
                            while i["nxt"] < min(total, fi + depth):
                                f2 = i["nxt"]
                                idx = i["a"] + int(f2 / fps * i["fps"]) % (i["b"] - i["a"])
                                if idx != i["sub_idx"]:
                                    if idx != i["sub_idx"] + 1:
                                        i["cap"].set(cv2.CAP_PROP_POS_FRAMES, idx)
                                    ok, fr = i["cap"].read()
                                    if ok:
                                        i["sub_fut"] = pool.submit(video_frame_image, cv2, fr, i["v"].crop, i["adj"], i["tw"], i["th"])
                                    i["sub_idx"] = idx
                                i["futs"][f2] = i["sub_fut"]
                                i["nxt"] += 1
                            fut = i["futs"].pop(fi)
                            if fut is not None and fut is not i["shown"]:
                                i["pr"].setPixmap(QPixmap.fromImage(fut.result()))
                                i["shown"] = fut
                        img.fill(sc.bg)
                        p = QPainter(img)
                        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
                        sc.render(p, QRectF(0, 0, OW, OH), slide_rect(sc, k))
                        p.end()
                        data = memoryview(img.constBits())[:nbytes]
                        try:
                            for pos in range(0, nbytes, 1 << 20):            # small chunks: kind to Windows pipes
                                pc.stdin.write(data[pos:pos + (1 << 20)])
                            pc.stdin.flush()
                        except (OSError, ValueError) as e:
                            ef.seek(0)
                            why = ef.read().decode(errors="replace").strip()[-700:]
                            raise RuntimeError(f"The video encoder stopped while writing slide {k + 1} ({e}).\n\n{why or 'No message from the encoder.'}")
                        if fi % 3 == 0 or fi == total - 1:
                            progress.update(base + si * total + fi + 1, f"Slide {k + 1} (video): frame {fi + 1} of {total}   "
                                                                         f"[slide {si + 1} of {len(slides)} with video]")
                            if progress.canceled():
                                canceled = True
                                break
                    try:
                        pc.stdin.close()
                    except OSError:
                        pass
                    if canceled:
                        pc.kill()
                        break
                    progress.update(base + (si + 1) * total, f"Slide {k + 1}: finishing the video file...")
                    if pc.wait() != 0:
                        ef.seek(0)
                        raise RuntimeError("The video encoder reported an error:\n" + ef.read().decode(errors="replace")[-700:])
                    done_n += 1
                finally:
                    if pc.poll() is None:
                        pc.kill()
                    if pool is not None:
                        pool.shutdown(wait=True, cancel_futures=True)
                    for i in caps.values():
                        i["cap"].release()
                    for pr in proxies:
                        sc.removeItem(pr)
                    ef.close()
                    img = None
                    gc.collect()
        except Exception as e:
            err = str(e)
        finally:
            for v in all_vids:
                v.setVisible(not v.data(8))
                v.play()
            sc.exporting, sc.show_guides = False, old_guides
            sc.update()
        if canceled and not err:
            err = "Export cancelled."
        has_snd = [i for i in infos.values() if i["audio"]]
        n_mut = sum(1 for i in has_snd if i["v"].muted)
        if not has_snd:
            sound = "no audio in the source video"
        elif n_mut == len(has_snd):
            sound = "all videos muted (no sound)"
        elif n_mut:
            sound = f"sound kept from {len(has_snd) - n_mut} video(s), {n_mut} muted"
        else:
            sound = "original audio kept"
        if level == -1:
            quality, note = "high-quality H.264 (graphics card encoder)", ""
        else:
            quality = "near-lossless H.264"
            note = "" if level == 0 else " (compatibility mode: this PC's encoder could not use the best settings)"
            if gpu:
                note += " (the graphics card encoder was not available, the processor was used)"
        return done_n, err, f"videos {OW} x {OH} px, {fps:.3f} fps (same as the source), {quality}, {sound}{note}"

    def export_images(self, slides, fmt, scale, folder, progress, base, per_slide, limits):
        """Photos / text slides: render on this thread, encode on a second thread, so the window and the progress bar
        keep moving and only about two slides are ever in memory. Returns (number done, error text or None)."""
        sc = self.scene
        W, H = int(sc.pw * scale), int(sc.ph * scale)
        q = queue.Queue(maxsize=1)
        state = {"done": 0, "err": None, "busy": None}

        def worker():
            while True:
                item = q.get()
                if item is None:
                    return
                i, img = item
                state["busy"] = i
                if state["err"] is None:
                    state["err"] = save_image_hq(img, Path(folder) / f"slide_{i + 1:02d}", fmt)
                    if state["err"] is None:
                        state["done"] += 1
                state["busy"] = None
                del img

        th = threading.Thread(target=worker, daemon=True)
        th.start()
        sc.clearSelection()
        old_guides = sc.show_guides
        sc.exporting, sc.show_guides = True, False
        canceled = False
        try:
            for n, i in enumerate(slides):
                if progress.canceled() or state["err"]:
                    canceled = bool(progress.canceled())
                    break
                progress.update(base + n * per_slide + per_slide * 0.3, f"Slide {i + 1}: drawing {W} x {H} px...")
                img = QImage(W, H, QImage.Format_RGB32)
                img.fill(sc.bg)
                p = QPainter(img)
                p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
                sc.render(p, QRectF(0, 0, W, H), slide_rect(sc, i))
                p.end()
                progress.update(base + n * per_slide + per_slide * 0.5, f"Slide {i + 1}: saving as {fmt.upper()}...")
                while True:                                    # hand over (waits while the previous slide is still saving)
                    try:
                        q.put((i, img), timeout=0.05)
                        break
                    except queue.Full:
                        progress.update(base + n * per_slide + per_slide * 0.5, f"Slide {i + 1}: saving as {fmt.upper()}...")
                        if progress.canceled():
                            break
                img = None
            while True:                                        # last slide: wait for it, bar stays alive
                try:
                    q.put(None, timeout=0.05)
                    break
                except queue.Full:
                    progress.update(base + len(slides) * per_slide * 0.9, "Saving the last image slide...")
            while th.is_alive():
                th.join(0.05)
                progress.update(base + len(slides) * per_slide * 0.97, "Saving the last image slide...")
        finally:
            sc.exporting, sc.show_guides = False, old_guides
            sc.update()
            gc.collect()
        err = state["err"] or ("Export cancelled." if canceled else None)
        return state["done"], err

    def export(self):
        """One export for everything: slides with video become MP4, the others are saved in the chosen image format.
        Files are numbered in slide order (slide_01, slide_02, ...), whatever their type. One progress bar, and the PC
        stays usable (lower priority, only part of the CPU cores)."""
        sc = self.scene
        if self.crop_state:
            self.end_crop(True)
        vmap = video_slide_map(sc)
        if vmap and not need_video_tools(self):
            return
        auto = self.auto_export_scale()
        if vmap:
            need = 1.0
            for v in {v for l in vmap.values() for v in l}:
                try:
                    c = v.crop or [0, 0, 1, 1]
                    need = max(need, (c[2] - c[0]) * (v.native[0] or 0) / max(v.size().width() * v.scale(), 1))
                except Exception:
                    pass
            auto = int(min(4, max(auto, math.ceil(need - 0.05))))
        d = ExportDialog(self, auto, len({v for l in vmap.values() for v in l}), sorted(vmap))
        if not d.exec():
            return
        fmt, scale, folder = d.fmt, d.scale, d.folder
        if not folder:
            return
        # ---- memory check: never start something the PC cannot hold
        avail = available_ram_mb()
        while avail:
            need = est_export_mb(fmt, int(sc.pw * scale), int(sc.ph * scale)) + 1200
            if vmap:
                vk = video_scale(scale)
                need = max(need, est_video_mb(int(sc.pw * vk), int(sc.ph * vk)) + 1200)
            if need <= avail * 0.6 or scale <= 1:
                break
            box = QMessageBox(self)
            box.setWindowTitle("Not enough free memory")
            box.setText(f"Exporting at {scale}x needs about {need / 1024:.1f} GB, but only {avail / 1024:.1f} GB of memory is free.\n\n"
                        f"Exporting anyway could make your computer very slow.")
            lower = box.addButton(f"Use {scale - 1}x instead", QMessageBox.AcceptRole)
            go = box.addButton("Export anyway", QMessageBox.DestructiveRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            c = box.clickedButton()
            if c is lower:
                scale -= 1
            elif c is go:
                break
            else:
                return
        img_slides = [i for i in range(sc.n * sc.rows) if i not in vmap]
        infos, fps, frames = {}, 30.0, 0
        if vmap:
            infos, fps, frames, perr = self.prepare_videos(vmap)
            if perr:
                QMessageBox.warning(self, "Export", perr)
                return
        per_slide = 25.0
        total_units = len(img_slides) * per_slide + len(vmap) * frames
        done_img, err, done_vid, verr, vinfo = 0, None, 0, None, ""
        limits = ExportLimits(d.perf)
        limits.gpu = getattr(d, "gpu", False)
        progress = ExportProgress(self, total_units)
        self.view.setUpdatesEnabled(False)           # the editor view behind the progress window does not need to redraw
        try:
            with limits:
                if img_slides:
                    done_img, err = self.export_images(img_slides, fmt, scale, folder, progress, 0, per_slide, limits)
                if not err and vmap:
                    done_vid, verr, vinfo = self.render_video_slides(folder, video_scale(scale), vmap, infos, fps, frames, progress,
                                                                    len(img_slides) * per_slide, limits)
        finally:
            self.view.setUpdatesEnabled(True)
            progress.close()
            gc.collect()
        if err or verr:
            QMessageBox.warning(self, "Export", err or ("Video export failed:\n\n" + verr))
        if done_img or done_vid:
            lines = [f"Exported {done_img + done_vid} slide(s) to:\n{folder}\n"]
            if done_img:
                lines.append(f"{done_img} image slide(s): {int(sc.pw * scale)} x {int(sc.ph * scale)} px, {fmt}, no quality loss")
            if done_vid:
                lines.append(f"{done_vid} video slide(s): {vinfo}")
            lines.append("Files are numbered in slide order: slide_01, slide_02, ...")
            if d.perf != "fast":
                lines.append("Computer load: " + (limits.status if limits.status else "no limit could be applied on this PC") + ".")
            QMessageBox.information(self, "Done", "\n".join(lines))

    def duplicate(self):
        top = max([i.zValue() for i in self.content_items()] + [0])
        new = []
        for k, it in enumerate(list(self.scene.selectedItems())):
            if isinstance(it, LAYERS):
                d = self.item_dict(it, top + 1 + k)
                d["x"] += 40
                d["y"] += 40
                self.build_item(d)
                new.append(d)
        self.commit()

    def center_in_slide(self):
        sc = self.scene
        for it in sc.selectedItems():
            if isinstance(it, LAYERS) and not it.data(1):
                c = it.sceneBoundingRect().center()
                col = min(max(int(c.x() // sc.pw), 0), sc.n - 1)
                row = min(max(int(c.y() // sc.ph), 0), sc.rows - 1)
                it.setPos(it.pos() + QPointF((col + .5) * sc.pw, (row + .5) * sc.ph) - c)
        sc.update()
        self.commit()

    def custom_size(self):
        w, ok = QInputDialog.getInt(self, "Slide size", "Width (px):", self.scene.pw, 100, 8000)
        if not ok:
            return
        h, ok = QInputDialog.getInt(self, "Slide size", "Height (px):", self.scene.ph, 100, 8000)
        if ok:
            self.scene.pw, self.scene.ph = w, h
            self.scene.resize_canvas()
            self.fit()
            self.commit()

    def z_shift(self, d):
        it = self.selected()
        if it:
            zs = [i.zValue() for i in self.scene.items()]
            it.setZValue(max(zs) + 1 if d > 0 else min(zs) - 1)
            self.commit()

    def delete_selected(self):
        sel = [i for i in self.scene.selectedItems() if not i.data(1)]
        if len(sel) < len(self.scene.selectedItems()):
            self.is_locked(self.scene.selectedItems()[0] if not sel else next(i for i in self.scene.selectedItems() if i.data(1)))
        for it in sel:
            self.scene.removeItem(it)
        if sel:
            self.commit()

    def set_rows(self, r):
        if r * self.scene.n > 20:   # 20 slides per project
            r = max(1, 20 // self.scene.n)
            self.rows_spin.blockSignals(True)
            self.rows_spin.setValue(r)
            self.rows_spin.blockSignals(False)
        self.scene.rows = r
        self.scene.resize_canvas()
        self.fit()
        self.commit()

    def set_panels(self, n):
        if n * self.scene.rows > 20:
            n = max(1, 20 // self.scene.rows)
            self.n_spin.blockSignals(True)
            self.n_spin.setValue(n)
            self.n_spin.blockSignals(False)
        self.scene.n = n
        self.scene.resize_canvas()
        self.fit()
        self.commit()

    def set_preset(self, name):
        self.scene.pw, self.scene.ph = PRESETS[name]
        self.scene.resize_canvas()
        self.fit()
        self.commit()

    def toggle_guides(self):
        self.scene.show_guides = not self.scene.show_guides
        self.scene.update()

    # ---------- slider sync ----------
    def sync_controls(self, refresh=True):
        st = self.crop_state
        if st is not None:                       # selecting something else (or nothing) closes the crop panel
            try:
                still = st["item"].scene() is self.scene and st["item"].isSelected()
            except RuntimeError:
                still = False
            if not still:
                QTimer.singleShot(0, lambda s0=st: self.end_crop(True, s0))
        try:
            it = self.selected()
        except RuntimeError:
            return
        sl = (self.s_scale, self.s_rot, self.s_op)
        for s in sl:
            s.blockSignals(True)
        if it:
            self.s_scale.setValue(int(it.scale() * 100))
            self.s_rot.setValue(int(it.rotation()))
            self.s_op.setValue(int(it.opacity() * 100))
            self.sync_pos(it)
        for s in sl:
            s.blockSignals(False)
            self.show_slider_value(s)
        self.prop_body.setVisible(it is not None)
        self.prop_hint.setVisible(it is None)
        self.sec_canvas.setVisible(it is None)         # slide size / count / background show when nothing is selected
        self.update_context()
        if refresh and not self.syncing:
            self.refresh_layers()

    def _apply(self, slider, setter):
        it = self.selected()
        if it and not it.data(1):
            setter(it)
            if not slider.isSliderDown():
                self.commit()

    def apply_scale(self, v):
        self._apply(self.s_scale, lambda it: it.setScale(v / 100))

    def apply_rot(self, v):
        self._apply(self.s_rot, lambda it: it.setRotation(v))

    def apply_opacity(self, v):
        self._apply(self.s_op, lambda it: it.setOpacity(v / 100))

    # ---------- export ----------
    def auto_export_scale(self):
        """Resolution multiplier that keeps the detail of the photos: source pixels per slide pixel, 2x .. 4x."""
        need = 1.0
        for it in self.scene.items():
            try:
                if isinstance(it, QGraphicsPixmapItem):
                    w = it.sceneBoundingRect().width()
                    if w > 1:
                        need = max(need, it.pixmap().width() / w)
                elif isinstance(it, GridItem):
                    for i in range(it.count()):
                        pm = it.pms[i]
                        if pm is not None and not pm.isNull():
                            cw = it.mapToScene(it.cell_rect(i)).boundingRect().width()
                            if cw > 1:
                                need = max(need, pm.width() / cw)
            except RuntimeError:
                pass
        return int(max(2, min(4, math.ceil(need))))


# ---------------------------------------------------------------- splash screen
class SplashScreen(QWidget):
    """Animated launch screen: phone swipe -> web view -> 'Aero.' wordmark, with a progress bar.
    Drawn entirely in code (no network, no image files). Click or press a key to skip."""
    W, H, M = 520, 320, 30            # panel size and shadow margin
    TOTAL, HOLD, FADE = 4.2, 0.4, 0.25
    PHONE_END, WEB_END = 1.6, 3.0

    def __init__(self, version=""):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.W + 2 * self.M, self.H + 2 * self.M)
        self.version = version
        self.force_t = None
        self.skipped = False
        self.clock = None
        self.loop = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.pics = [self.make_pic(i, 160, 240) for i in range(2)]
        self.wide = [self.make_pic(i + 2, 240, 160) for i in range(2)]
        scr = QApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)

    @staticmethod
    def make_pic(k, w, h):
        """Soft gradient 'photo' placeholder (sky, sun, hills)."""
        pal = [("#7dd3fc", "#fbcfe8", "#312e81"), ("#fde68a", "#fb923c", "#7c2d12"),
               ("#a5b4fc", "#67e8f9", "#134e4a"), ("#fecdd3", "#c4b5fd", "#1e1b4b")][k % 4]
        pm = QPixmap(w, h)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(pal[0]))
        g.setColorAt(1, QColor(pal[1]))
        p.fillRect(pm.rect(), g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 170))
        p.drawEllipse(QPointF(w * 0.68, h * 0.30), w * 0.11, w * 0.11)
        for j, a in enumerate((120, 200)):
            c = QColor(pal[2]); c.setAlpha(a)
            path = QPainterPath()
            path.moveTo(0, h)
            path.lineTo(0, h * (0.70 + 0.04 * j))
            path.cubicTo(w * 0.3, h * (0.52 + 0.1 * j), w * 0.6, h * (0.82 - 0.06 * j), w, h * (0.62 + 0.08 * j))
            path.lineTo(w, h)
            p.fillPath(path, c)
        p.end()
        return pm

    # ---- timing
    def t(self):
        if self.force_t is not None:
            return self.force_t
        return self.clock.elapsed() / 1000.0 if self.clock else 0.0

    def run(self):
        """Show the animation and block (event loop running) until it finishes or is skipped."""
        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer.start()
        self.loop = QEventLoop()
        self.loop.exec()
        self.timer.stop()

    def tick(self):
        self.update()
        if self.skipped or self.t() >= self.TOTAL + self.HOLD + self.FADE:
            if self.loop:
                self.loop.quit()

    def mousePressEvent(self, e):
        self.skipped = True

    def keyPressEvent(self, e):
        self.skipped = True

    # ---- drawing helpers
    @staticmethod
    def ease(x):
        x = max(0.0, min(1.0, x))
        return 1 - (1 - x) ** 4

    def paintEvent(self, ev):
        t = self.t()
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        fade = 1.0 - max(0.0, (t - self.TOTAL - self.HOLD) / self.FADE)
        p.setOpacity(max(0.0, min(1.0, fade)))
        M, W, H = self.M, self.W, self.H
        panel = QRectF(M, M, W, H)
        # soft shadow
        for i in range(14):
            r = panel.adjusted(-i * 1.6, -i * 1.6 + 8, i * 1.6, i * 1.6 + 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 9))
            p.drawRoundedRect(r, 16 + i * 1.6, 16 + i * 1.6)
        clip = QPainterPath()
        clip.addRoundedRect(panel, 16, 16)
        p.save()
        p.setClipPath(clip)
        bg = QLinearGradient(panel.topLeft(), panel.bottomRight())
        bg.setColorAt(0, QColor("#0a0d18")); bg.setColorAt(0.5, QColor("#10142a")); bg.setColorAt(1, QColor("#1a1d44"))
        p.fillRect(panel, bg)
        for c, col, a in ((panel.topLeft(), QColor(56, 189, 248), 55), (panel.bottomRight(), QColor(129, 140, 248), 45)):
            rg = QRadialGradient(c, 230)
            col.setAlpha(a); rg.setColorAt(0, col)
            col.setAlpha(0); rg.setColorAt(1, col)
            p.fillRect(panel, rg)
        self.draw_header(p, panel, t)
        content = QRectF(panel.left() + 24, panel.top() + 50, W - 48, H - 50 - 24 - 4 - 8 - 18 - 8)
        if t < self.PHONE_END:
            self.draw_phone(p, content, t)
        elif t < self.WEB_END:
            self.draw_web(p, content, t - self.PHONE_END)
        else:
            self.draw_wordmark(p, content, t - self.WEB_END)
        self.draw_progress(p, panel, t)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(panel.adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)
        p.end()

    def draw_header(self, p, panel, t):
        x, y = panel.left() + 24, panel.top() + 24
        p.setPen(Qt.NoPen)
        pulse = 0.55 + 0.45 * math.sin(t * 5)
        p.setBrush(QColor(34, 211, 238, int(210 * pulse)))
        p.drawEllipse(QPointF(x + 5, y + 6), 4.5, 4.5)
        f = QFont("Segoe UI", 8); f.setBold(True); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        p.setFont(f)
        p.setPen(QColor(226, 232, 240, 100))
        p.drawText(QPointF(x + 18, y + 10), "LAUNCHING APPLICATION")
        f2 = QFont("Consolas", 8)
        p.setFont(f2)
        p.drawText(QRectF(panel.right() - 24 - 160, y - 2, 160, 18), Qt.AlignRight | Qt.AlignVCenter, self.version)

    def marquee(self, p, rect, pics, iw, ih, gap, t, radius):
        """Pictures sliding left -> right, seamless loop."""
        period = 2 * (iw + gap)
        off = ((t % 3.5) / 3.5) * period - period
        p.save()
        p.setClipRect(rect)
        y = rect.center().y() - ih / 2
        for k in range(-1, int(rect.width() / (iw + gap)) + 3):
            x = rect.left() + off + k * (iw + gap)
            pm = pics[k % 2]
            path = QPainterPath()
            r = QRectF(x, y, iw, ih)
            path.addRoundedRect(r, radius, radius)
            p.save()
            p.setClipPath(path, Qt.IntersectClip)
            p.drawPixmap(r, pm, QRectF(pm.rect()))
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 28), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, radius, radius)
        p.restore()

    def draw_phone(self, p, c, t):
        e = self.ease(t / 0.8)
        pw, ph = 130.0, 188.0
        cx, cy = c.center().x(), c.center().y()
        p.save()
        p.setOpacity(p.opacity() * e)
        p.translate(cx, cy + 120 * (1 - e))
        p.rotate(-10 * (1 - e))
        p.translate(-pw / 2, -ph / 2)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.setBrush(QColor("#1e293b"))
        p.drawRoundedRect(QRectF(-12, 56, 22, 36), 10, 10)                      # thumb
        for i in range(3):
            p.drawRoundedRect(QRectF(pw - 10, 36 + i * 32, 22, 26), 10, 10)      # fingers
        body = QRectF(0, 0, pw, ph)
        p.setPen(QPen(QColor(51, 65, 85, 205), 2))
        p.setBrush(QColor("#0f172a"))
        p.drawRoundedRect(body, 26, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#020617"))
        p.drawRoundedRect(QRectF(pw / 2 - 18, 9, 36, 7), 3.5, 3.5)               # notch
        screen = QRectF(8, 24, pw - 16, ph - 32)
        path = QPainterPath()
        path.addRoundedRect(screen, 16, 16)
        p.fillPath(path, QColor("#020617"))
        p.save()
        p.setClipPath(path, Qt.IntersectClip)
        self.marquee(p, screen, self.pics, 86, 130, 12, t, 8)
        p.restore()
        p.restore()

    def draw_web(self, p, c, t):
        a = self.ease(t / 0.35)
        p.save()
        p.setOpacity(p.opacity() * a)
        box = QRectF(c.left(), c.center().y() - 78, c.width(), 156)
        path = QPainterPath()
        path.addRoundedRect(box, 12, 12)
        p.fillPath(path, QColor(15, 23, 42, 230))
        p.save()
        p.setClipPath(path, Qt.IntersectClip)
        bar = QRectF(box.left(), box.top(), box.width(), 28)
        p.fillRect(bar, QColor("#1e293b"))
        for i, col in enumerate(("#ef4444", "#eab308", "#22c55e")):
            cc = QColor(col); cc.setAlpha(205)
            p.setPen(Qt.NoPen); p.setBrush(cc)
            p.drawEllipse(QPointF(bar.left() + 16 + i * 15, bar.center().y()), 4.5, 4.5)
        pill = QRectF(bar.left() + 70, bar.top() + 5, bar.width() - 86, 18)
        p.setBrush(QColor(2, 6, 23, 155))
        p.drawRoundedRect(pill, 6, 6)
        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(148, 163, 184))
        p.drawText(pill, Qt.AlignCenter, "Aero  -  Carousel Preview")
        gal = QRectF(box.left(), bar.bottom(), box.width(), box.height() - bar.height())
        self.marquee(p, gal, self.wide, 120, 80, 12, t, 8)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 12, 12)
        p.restore()

    def draw_wordmark(self, p, c, t):
        f = QFont("Segoe UI", 1)
        f.setPixelSize(78)
        f.setWeight(QFont.ExtraBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, -1.5)
        thin = QFont(f)
        thin.setWeight(QFont.Medium)
        letters = [("A", f), ("e", f), ("r", f), ("o", f), (".", thin)]
        adv = [QFontMetricsF(fo).horizontalAdvance(ch) for ch, fo in letters]
        total = sum(adv) + 2
        x = c.center().x() - total / 2
        base = c.center().y() + 26
        for i, (ch, fo) in enumerate(letters):
            e = self.ease((t - (0.1 + 0.15 * i)) / 0.85)
            if e > 0:
                path = QPainterPath()
                path.addText(0, 0, fo, ch)
                br = path.boundingRect()
                p.save()
                p.setOpacity(p.opacity() * e)
                p.translate(x + adv[i] / 2 - 60 * (1 - e), base)
                p.scale(0.92 + 0.08 * e, 0.92 + 0.08 * e)
                p.translate(-adv[i] / 2, 0)
                if ch == ".":
                    p.fillPath(path, QColor("#22d3ee"))
                else:
                    g = QLinearGradient(0, -56, 0, 0)
                    g.setColorAt(0, QColor("#ffffff")); g.setColorAt(1, QColor("#cbd5e1"))
                    p.fillPath(path, g)
                p.restore()
            x += adv[i] + (2 if ch == "o" else 0)

    def draw_progress(self, p, panel, t):
        x, w = panel.left() + 24, panel.width() - 48
        y = panel.bottom() - 24 - 4
        frac = max(0.0, min(1.0, t / self.TOTAL))
        sm = frac * frac * (3 - 2 * frac)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 41, 59, 205))
        p.drawRoundedRect(QRectF(x, y, w, 4), 2, 2)
        if sm > 0:
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0, QColor("#06b6d4")); g.setColorAt(0.5, QColor("#38bdf8")); g.setColorAt(1, QColor("#6366f1"))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(x, y, w * sm, 4), 2, 2)
        status = ("Preparing tools and filters" if t < self.PHONE_END else
                  "Get ready to unleash your inner creativity" if t < self.WEB_END else "Launching Aero...")
        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor(148, 163, 184))
        p.drawText(QRectF(x, y - 24, w - 60, 18), Qt.AlignLeft | Qt.AlignVCenter, status)
        p.setFont(QFont("Consolas", 9))
        p.setPen(QColor(34, 211, 238, 230))
        p.drawText(QRectF(x + w - 60, y - 24, 60, 18), Qt.AlignRight | Qt.AlignVCenter, f"{int(frac * 100)}%")


def resource_path(*parts):
    """Bundled data files: next to the script, or inside the PyInstaller bundle when packaged."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_icon():
    ic = QIcon()
    for name in ("aero.ico", "aero_icon_256.png"):
        p = resource_path("assets", name)
        if os.path.exists(p):
            ic.addFile(p)
    return ic


if __name__ == "__main__":
    if sys.platform == "win32":        # own taskbar identity so Windows shows the Aero icon, not Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Winserendipity.Aero")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_BUILD)
    app.setWindowIcon(app_icon())      # every window / dialog inherits it
    apply_theme(app)
    splash = None
    if not os.environ.get("AERO_NO_SPLASH"):
        splash = SplashScreen(APP_BUILD)
        splash.show()
        app.processEvents()
    w = Main()
    if splash:
        splash.run()
        splash.close()
    start = StartScreen(w)
    if start.exec() != QDialog.Accepted:
        sys.exit(0)
    start.perform()
    w.show()
    sys.exit(app.exec())
