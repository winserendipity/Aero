"""
Aero (beta) - a seamless carousel editor for Instagram / Facebook albums, for desktop.
Run:  pip install PySide6 numpy   then   python aeroeditor.py
Optional: pip install rembg (AI background removal), pillow pillow-heif (iPhone HEIC photos).
"""
import os, sys, json, base64, uuid, math, random, hashlib
from pathlib import Path

from PySide6.QtGui import QCursor
from PySide6.QtCore import QPoint, Qt, QRectF, QPointF, QSizeF, QUrl, QBuffer, QIODevice, QSettings, QSize, QTimer, QVariantAnimation, QEasingCurve, QStandardPaths
from PySide6.QtGui import (QColor, QPainter, QPen, QPixmap, QImage, QKeySequence,
                           QAction, QFont, QPolygonF, QLinearGradient, QBrush, QImageReader, QTransform, QIcon,
                           QPainterPath, QPalette, QTextCursor, QTextBlockFormat, QTextCharFormat, QRadialGradient, QPainterPathStroker, QFontMetricsF)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QGraphicsTextItem, QToolBar, QFileDialog, QColorDialog, QFontDialog, QSpinBox,
    QGraphicsItem, QInputDialog, QProgressDialog, QDialog, QTabWidget, QGridLayout, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QDialogButtonBox, QFormLayout, QComboBox, QLabel, QSlider, QWidget, QVBoxLayout, QDockWidget, QMessageBox, QScrollArea, QToolButton, QMenu,
    QStyleOptionGraphicsItem, QCheckBox, QGraphicsDropShadowEffect, QHBoxLayout, QLineEdit, QRadioButton, QStackedWidget, QFrame,
)

try:
    import numpy as np
except ImportError:
    np = None

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    HAS_VIDEO = True
except ImportError:
    HAS_VIDEO = False

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


if HAS_VIDEO:
    class VideoItem(QGraphicsVideoItem):
        """Muted, looping video layer (preview in editor)."""
        def __init__(self, path, size=None, fit_w=864):
            super().__init__()
            self.path, self.fit_w = path, (fit_w if size is None else None)
            self.audio = QAudioOutput()
            self.audio.setMuted(True)
            self.player = QMediaPlayer()
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self)
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
            self.setSize(size or QSizeF(640, 360))
            self.nativeSizeChanged.connect(self._native)
            self.player.errorOccurred.connect(self._err)
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.play()

        def _err(self, err, msg):
            sc = self.scene()
            if sc and sc.on_error:
                sc.on_error(f"{Path(self.path).name}: {msg}")

        def _native(self, sz):
            if self.fit_w and sz.width() > 0:
                self.setSize(QSizeF(self.fit_w, self.fit_w * sz.height() / sz.width()))
                self.fit_w = None
                self.setTransformOriginPoint(self.boundingRect().center())
                if self.scene() and self.scene().on_change:
                    self.scene().on_change()

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


class View(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.on_delete = None
        self.on_nudge = None
        self.on_context = None
        self.on_key = None
        self.panning, self.pan_last = False, None
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)

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
    x = np.clip(x, 0, 1)
    x = (x - .5) * P["con"] + .5
    if P["gam"] != 1.0:
        x = np.clip(x, 0, 1) ** (1.0 / P["gam"])
    if not P["bw"]:
        L = lumv(x)
        x = L + (x - L) * P["sat"]
        x = x + np.array([P["temp"], P["tint"], -P["temp"]], np.float32)
    L = np.clip(lumv(x), 0, 1)
    tone = np.array(P["tone"], np.float32) if P["bw"] else 0
    x = x + np.array(P["sh"], np.float32) * (1 - L) ** 2 + np.array(P["hl"], np.float32) * L ** 2 + tone
    x = P["lift"] + np.clip(x, 0, 1) * (P["hi"] - P["lift"])
    if P["vig"] > 0:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
        x = x * (1 - P["vig"] * np.clip(r2 / 2, 0, 1))[..., None]
    if P["grain"] > 0:
        k = 2 if size > 1.2 else 1
        n = np.random.default_rng(3).standard_normal((-(-h // k), -(-w // k), 1)).astype(np.float32)
        if k > 1:
            n = block_up(n, k, h, w)
        Lm = np.clip(lumv(x), 0, 1)
        x = x + n * P["grain"] * .22 * (1 - np.abs(Lm - .5) * 1.2)
    return x


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
        sat = x.max(-1, keepdims=True) - x.min(-1, keepdims=True)
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


def adjust_rgb(x, a):
    g = lambda k: a.get(k, 0) / 100.0
    lum = lambda v: v @ np.array([0.299, 0.587, 0.114], np.float32)
    sstep = lambda lo, hi, v: np.clip((v - lo) / (hi - lo), 0, 1)
    x = x * (2 ** (g("exposure") * 1.5)) + g("brightness") * 0.3
    x = np.clip((x - 0.5) * (1 + g("contrast")) + 0.5, 0, 1)
    L = lum(x)[..., None]
    x = x + g("highlights") * 0.35 * sstep(0.5, 1, L) + g("shadows") * 0.35 * (1 - sstep(0, 0.5, L))
    x[..., 0] += g("temperature") * 0.12 + g("tint") * 0.04
    x[..., 2] -= g("temperature") * 0.12 - g("tint") * 0.04
    x[..., 1] -= g("tint") * 0.08
    x = np.clip(x, 0, 1)
    gray = lum(x)[..., None]
    sat = (x.max(-1, keepdims=True) - x.min(-1, keepdims=True))
    x = gray + (x - gray) * (1 + g("saturation") + g("vibrance") * (1 - sat))
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
        x = x + np.random.default_rng(1).normal(0, a["grain"] / 100 * 0.12, x.shape[:2] + (1,)).astype(np.float32)
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
        top.addWidget(QLabel("Category:"))
        self.cat = QComboBox()
        self.cat.addItems(["All"] + list(dict.fromkeys(t["cat"] for t in TEMPLATES)))
        self.cat.currentTextChanged.connect(self.fill)
        top.addWidget(self.cat)
        top.addStretch()
        lay.addLayout(top)
        self.lst = QListWidget()
        self.lst.setViewMode(QListWidget.IconMode)
        self.lst.setIconSize(QSize(430, 170))
        self.lst.setSpacing(10)
        self.lst.setMovement(QListWidget.Static)
        self.lst.setResizeMode(QListWidget.Adjust)
        self.lst.setWordWrap(True)
        self.lst.itemDoubleClicked.connect(lambda *_: self.use())
        lay.addWidget(self.lst, 1)
        lay.addWidget(QLabel("Grids are empty photo frames: select one, then Layer > Fill Grid Cells with Images..."))
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
            li.setSizeHint(QSize(450, 215))
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
        self.show_hint = True
        self.hint_timer = QTimer(self)
        self.hint_timer.setSingleShot(True)
        self.hint_timer.timeout.connect(self.hide_hint)
        self.hint_timer.start(3500)
        self.tick = QTimer(self)                 # keep videos moving
        self.tick.timeout.connect(self.update)
        if HAS_VIDEO and any(isinstance(i, VideoItem) for i in sc.items()):
            self.tick.start(40)

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
        self.tick.stop()
        self.sc.exporting = False
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
                pil.save(str(path), "WEBP", lossless=True, quality=100, method=6)
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


class ExportDialog(QDialog):
    """Export slides: format, resolution, folder. Quality first - nothing is compressed to save space."""
    def __init__(self, parent, auto_scale):
        super().__init__(parent)
        self.setWindowTitle("Export slides")
        self.setFixedWidth(460)
        self.fmt, self.scale, self.folder, self.auto = "png", 2, "", auto_scale
        self.sc = parent.scene
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Format"))
        self.f = QComboBox()
        for label, _ in EXPORT_FORMATS:
            self.f.addItem(label)
        lay.addWidget(self.f)
        lay.addWidget(QLabel("Resolution"))
        self.r = QComboBox()
        self.r.addItem(f"Best detail (automatic: {auto_scale}x)", 0)
        for k in (1, 2, 3, 4):
            self.r.addItem(f"{k}x", k)
        self.r.currentIndexChanged.connect(self.info)
        lay.addWidget(self.r)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.note)
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
        self.info()
        self.setFixedHeight(self.sizeHint().height())

    def info(self, *_):
        k = self.r.currentData() or self.auto
        self.note.setText(f"Each slide is saved at {int(self.sc.pw * k)} x {int(self.sc.ph * k)} px. Text and shapes are drawn "
                          f"sharp at that size and photos keep their full detail.")

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, "Export slides to folder", self.loc.text())
        if d:
            self.loc.setText(d)

    def go(self):
        self.fmt = EXPORT_FORMATS[self.f.currentIndex()][1]
        self.scale = self.r.currentData() or self.auto
        self.folder = self.loc.text().strip()
        try:
            Path(self.folder).mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            QMessageBox.warning(self, "Export", f"Cannot use that folder: {ex}")
            return
        self.accept()


# ---------------------------------------------------------------- settings / theme / system info
APP_BUILD = "Beta 0.0.1"
VERSION_LINES = ["Aero Beta version 0.0.1 - Beta in testing, not for general deployment. Expect bugs and issues. Currently in development.",
                 "Created by Winserendipity",
                 "All Rights Reserved. 2026"]
VERSION_TEXT = VERSION_LINES[0]
LANGUAGES = ["English", "Filipino", "Espa\u00f1ol", "Fran\u00e7ais", "Deutsch", "Portugu\u00eas", "Italiano",
             "\u65e5\u672c\u8a9e", "\ud55c\uad6d\uc5b4", "\u4e2d\u6587 (\u7b80\u4f53)"]
DEFAULT_ACCENT = "#c6f135"


def cfg():
    return QSettings("AeroPhotoEditor", "Editor")


THEMES = {
    "Dark": dict(bg="#08080a", panel="#101013", field="#17171b", border="#1e1e23", border2="#2b2b32", text="#ededf1",
                 muted="#8a8a96", hover="#1a1a1f", press="#24242b", canvas="#0c0c0f"),
    "Light": dict(bg="#eef0f4", panel="#ffffff", field="#f3f4f8", border="#e3e5ec", border2="#d2d5df", text="#16161a",
                  muted="#6c6e7b", hover="#eceef4", press="#dfe2ea", canvas="#e4e6ec"),
}
PASTEBOARD = QColor("#0c0c0f")          # area around the slides (follows the theme)


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
    t["accent_text"] = "#0d1103" if ac.lightnessF() > .55 else "#ffffff"
    t["accent_soft"] = f"rgba({ac.red()}, {ac.green()}, {ac.blue()}, 0.18)"
    t["accent_hover"] = ac.lighter(112).name()
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


QSS = """
* { font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif; }
QMainWindow, QDialog { background: @bg@; }
QDialog { background: @panel@; }
QWidget { color: @text@; font-size: 13px; }
QToolTip { background: @panel@; color: @text@; border: 1px solid @border2@; padding: 5px 8px; }
QMenuBar { background: @bg@; padding: 6px 10px 2px 10px; spacing: 2px; }
QMenuBar::item { background: transparent; color: @muted@; padding: 6px 12px; border-radius: 8px; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: @hover@; color: @text@; }
QMenu { background: @panel@; border: 1px solid @border2@; padding: 6px; }
QMenu::item { padding: 7px 26px 7px 14px; border-radius: 6px; color: @text@; }
QMenu::item:selected { background: @press@; }
QMenu::item:disabled { color: @muted@; }
QMenu::separator { height: 1px; background: @border@; margin: 6px 8px; }
QToolBar { background: @bg@; border: none; spacing: 4px; padding: 6px 10px 8px 10px; }
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
QDockWidget::title { background: @bg@; padding: 11px 14px 7px 14px; text-align: left; }
QMainWindow::separator { background: @bg@; width: 8px; height: 8px; }
QScrollArea { border: none; background: transparent; }
QGraphicsView { border: 1px solid @border@; background: @canvas@; }
QDockWidget > QWidget { border: 1px solid @border@; }
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
"""


def apply_theme(app, theme=None, accent=None):
    """Whole-application look: colour palette + one global stylesheet (dark or light, any accent colour)."""
    global PASTEBOARD
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
    for w in app.topLevelWidgets():
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


class SettingsDialog(QDialog):
    """File > Settings: General (language), Appearance (theme + accent), Version, About (system information)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(560, 430)
        c = cfg()
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        # General
        g = QWidget()
        gl = QVBoxLayout(g)
        gl.addWidget(QLabel("Language"))
        self.lang = QComboBox()
        self.lang.addItems(LANGUAGES)
        self.lang.setCurrentText(c.value("language", "English"))
        self.lang.currentTextChanged.connect(lambda v: cfg().setValue("language", v))
        gl.addWidget(self.lang)
        note = QLabel("Your choice is saved. Translated interface text is not part of this beta build yet, so the app still shows English.")
        note.setWordWrap(True)
        gl.addWidget(note)
        gl.addStretch()
        tabs.addTab(g, "General")
        # Appearance
        a = QWidget()
        al = QVBoxLayout(a)
        al.addWidget(QLabel("Theme"))
        self.theme_btns = {}
        for t in ("Dark", "Light"):
            r = QRadioButton(t)
            r.setChecked(c.value("theme", "Dark") == t)
            r.toggled.connect(lambda on, t=t: on and self.set_theme(t))
            self.theme_btns[t] = r
            al.addWidget(r)
        al.addSpacing(10)
        al.addWidget(QLabel("Accent"))
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
        tabs.currentChanged.connect(lambda i: i == 3 and self.fill_about())
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        bb.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        lay.addWidget(bb)

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
    """Fixed-size window: project name, save location, slide size, number of slides, Create."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.info = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(8)
        self.lay = lay
        lay.addWidget(self.head("Name of the project"))
        self.name = QLineEdit("Untitled")
        self.name.textChanged.connect(self.check)
        lay.addWidget(self.name)
        lay.addSpacing(6)
        lay.addWidget(self.head("Location"))
        row = QHBoxLayout()
        self.loc = QLineEdit(default_projects_dir())
        self.loc.textChanged.connect(self.check)
        row.addWidget(self.loc, 1)
        b = QPushButton("Choose...")
        b.clicked.connect(self.choose)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addSpacing(6)
        lay.addWidget(self.head("Size"))
        self.radios = []
        for i, (label, (w, h)) in enumerate(NEW_SIZES):
            r = QRadioButton(f"{label}      {w} x {h}")
            r.setChecked(i == 0)
            self.radios.append(r)
            lay.addWidget(r)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addWidget(self.head("Number of slides"))
        row.addStretch()
        self.n = QSpinBox()
        self.n.setRange(1, 20)
        self.n.setValue(3)
        row.addWidget(self.n)
        lay.addLayout(row)
        lay.addSpacing(8)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #ff6b6b;")
        self.msg.setWordWrap(True)
        self.msg.hide()
        lay.addWidget(self.msg)
        self.create = QPushButton("Create")
        self.create.setObjectName("primary")
        self.create.setDefault(True)
        self.create.clicked.connect(self.make)
        lay.addWidget(self.create)
        self.fit()

    def fit(self):
        """Exactly as tall as its content (no empty space); the message line only takes room when shown."""
        self.setFixedSize(480, self.lay.sizeHint().height())

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


class CardButton(QPushButton):
    """Big rounded action card: round icon, bold title, small description."""
    def __init__(self, kind, title, sub, hero=False):
        super().__init__()
        self.setObjectName("cardHero" if hero else "card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 14, 20, 14)
        row.setSpacing(16)
        ic = QLabel()
        ic.setFixedSize(44, 44)
        ic.setAlignment(Qt.AlignCenter)
        ic.setObjectName("cardIconHero" if hero else "cardIcon")
        ic.setPixmap(glyph_icon(kind, "#15161b" if hero else "#ffffff", 22))
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addStretch()
        t = QLabel(title)
        t.setObjectName("cardTitle")
        sb = QLabel(sub)
        sb.setObjectName("cardSub")
        col.addWidget(t)
        col.addWidget(sb)
        col.addStretch()
        row.addWidget(ic)
        row.addLayout(col, 1)
        for w in (ic, t, sb):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)


class StartScreen(QDialog):
    """Shown before the editor opens: New project, Open project, Templates and the Recent projects list."""
    @staticmethod
    def make_style():
        t = theme_tokens()
        hero_bg = "#ffffff" if t["dark"] else "#16161a"
        hero_fg = "#111114" if t["dark"] else "#ffffff"
        q = """
        * { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-weight: 700; }
        QDialog { background: @bg@; }
        QLabel#title { color: @text@; font-size: 38px; }
        QLabel#badge { color: @accent_text@; background: @accent@; border-radius: 9px; padding: 3px 10px; font-size: 11px; }
        QLabel#intro { color: @muted@; font-size: 14px; font-weight: 500; }
        QLabel#head { color: @text@; font-size: 18px; }
        QLabel#emptybox { color: @muted@; font-size: 14px; font-weight: 500; background: transparent; }
        QFrame#recentCard { background: @panel@; border: 1px solid @border@; border-radius: 18px; }
        QPushButton#card, QPushButton#cardHero { background: @panel@; border: 1px solid @border@; border-radius: 18px; text-align: left; padding: 0; }
        QPushButton#card:hover { background: @hover@; border-color: @border2@; }
        QPushButton#cardHero { background: @herobg@; border-color: @herobg@; }
        QPushButton#cardHero:hover { background: @herohover@; border-color: @herohover@; }
        QLabel#cardTitle { color: @text@; font-size: 16px; }
        QLabel#cardSub { color: @muted@; font-size: 12px; font-weight: 500; }
        QPushButton#cardHero QLabel#cardTitle { color: @herofg@; }
        QPushButton#cardHero QLabel#cardSub { color: #55555f; }
        QLabel#cardIcon { background: @press@; border-radius: 22px; }
        QLabel#cardIconHero { background: #e6e6ec; border-radius: 22px; }
        QPushButton#link { background: transparent; border: none; color: @muted@; padding: 4px; font-size: 12px; }
        QPushButton#link:hover { color: @text@; }
        QListWidget { background: transparent; border: none; font-size: 13px; }
        QListWidget::item { padding: 8px; border-radius: 10px; }
        """
        t = dict(t, herobg=hero_bg, herofg=hero_fg, herohover="#e4e4ea" if t["dark"] else "#2b2b31")
        for k, v in sorted(t.items(), key=lambda kv: -len(kv[0])):
            if isinstance(v, str):
                q = q.replace(f"@{k}@", v)
        return q

    def __init__(self, main):
        super().__init__(None)
        self.main, self.result_action = main, None
        self.setWindowTitle(APP_NAME)
        self.setStyleSheet(self.make_style())
        self.setFixedSize(1000, 660)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        root = QVBoxLayout(self)
        root.setContentsMargins(52, 44, 52, 30)
        root.setSpacing(0)
        row = QHBoxLayout()
        t = QLabel("Welcome to " + APP_NAME)
        t.setObjectName("title")
        bd = QLabel("BETA")
        bd.setObjectName("badge")
        row.addWidget(t)
        row.addSpacing(10)
        row.addWidget(bd, 0, Qt.AlignVCenter)
        row.addStretch()
        root.addLayout(row)
        intro = QLabel("Welcome to Aero, an editor built for Instagram, Threads, and Facebook Album creation. Content purpose-built social media design platform made specifically for creators.")
        intro.setObjectName("intro")
        intro.setWordWrap(True)
        root.addSpacing(10)
        root.addWidget(intro)
        root.addSpacing(26)
        cards = QHBoxLayout()
        cards.setSpacing(16)
        for kind, title, sub, fn, hero in (("plus", "New Project", "Pick a slide size and count", self.new, True),
                                           ("folder", "Open Project", "Continue a saved project", self.open, False),
                                           ("grid", "Start from a Template", "Ready-made carousel layouts", self.template, False)):
            c = CardButton(kind, title, sub, hero)
            c.clicked.connect(fn)
            cards.addWidget(c, 1)
        root.addLayout(cards)
        root.addSpacing(34)
        h = QLabel("Recent projects")
        h.setObjectName("head")
        root.addWidget(h)
        root.addSpacing(12)
        card = QFrame()
        card.setObjectName("recentCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 14, 14, 14)
        self.lst = QListWidget()
        self.lst.setIconSize(QSize(150, 84))
        self.lst.itemDoubleClicked.connect(self.open_recent)
        cl.addWidget(self.lst, 1)
        self.empty_icon = QLabel()
        self.empty_icon.setPixmap(glyph_icon("image", theme_tokens()["muted"], 40))
        self.empty_icon.setAlignment(Qt.AlignCenter)
        self.empty = QLabel("Your recent projects appear here.\nNew to this? Don't worry, this is designed and made to be easy")
        self.empty.setObjectName("emptybox")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        cl.addStretch()
        cl.addWidget(self.empty_icon)
        cl.addSpacing(8)
        cl.addWidget(self.empty)
        cl.addStretch()
        root.addWidget(card, 1)
        clr = QPushButton("Clear list")
        clr.setObjectName("link")
        clr.setCursor(Qt.PointingHandCursor)
        clr.clicked.connect(self.clear_recent)
        root.addWidget(clr, 0, Qt.AlignRight)
        self.refill()

    def refill(self):
        self.lst.clear()
        rec = recent_projects()
        for pth in rec:
            tp = thumb_path(pth)
            li = QListWidgetItem(QIcon(str(tp)) if tp.exists() else placeholder_icon(),
                                 f"{Path(pth).stem}\n{Path(pth).parent}")
            li.setSizeHint(QSize(0, 100))
            li.setData(Qt.UserRole, pth)
            self.lst.addItem(li)
        self.empty.setVisible(not rec)
        self.empty_icon.setVisible(not rec)
        self.lst.setVisible(bool(rec))

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

    def open_recent(self, li):
        self.finish(("open", li.data(Qt.UserRole)))

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


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1300, 800)
        self.setContentsMargins(10, 0, 10, 10)
        self.scene = Canvas()
        self.scene.on_change = self.commit
        self.scene.on_transform = lambda: self.sync_controls(False)
        self.scene.on_error = self.video_error
        self.view = View(self.scene)
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
        self._build_side_panel()
        self._build_layers_dock()
        self.crop_panel = CropPanel(self)                      # appears in the right panel only while cropping
        self.crop_dock = QDockWidget("Crop image", self)
        self.crop_dock.setWidget(self.crop_panel)
        self.crop_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.RightDockWidgetArea, self.crop_dock)
        self.tabifyDockWidget(self.side_dock, self.crop_dock)
        self.crop_dock.hide()
        self.scene.selectionChanged.connect(self.sync_controls)
        self.reset_history(DEFAULT)
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
        m = self.menuBar().addMenu("&File")
        self._act(m, "New", self.new_project, QKeySequence.New)
        self._act(m, "Open...", self.open_project, QKeySequence.Open)
        self.recent_menu = m.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self.fill_recent_menu)
        self._act(m, "Save", self.save, QKeySequence.Save)
        self._act(m, "Save As...", self.save_as, QKeySequence.SaveAs)
        self._act(m, "Close Project", self.close_project, "Ctrl+W")
        m.addSeparator()
        self._act(m, "Export Slides...", self.export)
        self._act(m, "Export Video (.mp4)...", self.export_video)
        m.addSeparator()
        self._act(m, "Settings...", lambda: SettingsDialog(self).exec())
        e = self.menuBar().addMenu("&Edit")
        self._act(e, "Undo", self.undo, QKeySequence.Undo)
        self._act(e, "Redo", self.redo, QKeySequence.Redo)
        e.addSeparator()
        self._act(e, "Copy", self.copy_layers, QKeySequence.Copy)
        self._act(e, "Paste", self.paste_layers, QKeySequence.Paste)
        m = self.menuBar().addMenu("&View")
        a = self._act(m, "Zoom In", lambda: self.zoom(1.2))
        a.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+="), QKeySequence("Ctrl+Shift+=")])
        a = self._act(m, "Zoom Out", lambda: self.zoom(1 / 1.2))
        a.setShortcuts([QKeySequence("Ctrl+-"), QKeySequence("Ctrl+_")])
        self._act(m, "Fit View", self.fit, "Ctrl+0")
        m.addSeparator()
        self._act(m, "Full Screen Preview (2 slides)", self.preview_fullscreen, "F11")
        self._act(m, "Toggle Guides", self.toggle_guides)
        m = self.menuBar().addMenu("&Insert")
        self._act(m, "Rectangle", lambda: self.add_shape("rect"))
        self._act(m, "Ellipse", lambda: self.add_shape("ellipse"))
        self._act(m, "Line", lambda: self.add_shape("line"))
        self._act(m, "Edit Shape... (opacity, corners, shadow, border)", self.shape_panel)
        self._act(m, "Grid Layouts...", self.add_grid)
        self._act(m, "Grid (plain 2 x 2)", self.add_grid_simple)
        self._act(m, "Overlay (tinted layer over all slides)", self.add_overlay)
        self._act(m, "Video...", self.add_video)
        self._act(m, "Play / Pause Videos", self.toggle_video)
        m = self.menuBar().addMenu("&Layer")
        self._act(m, "Duplicate", self.duplicate, "Ctrl+D")
        self._act(m, "Center in Slide", self.center_in_slide)
        self._act(m, "Crop Image...", self.crop_image)
        self._act(m, "Replace Image...", self.replace_image)
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
        m = self.menuBar().addMenu("&Image")
        self._act(m, "Edit Image...", self.edit_image)
        self._act(m, "Crop...", self.crop_image)
        self._act(m, "Crop to Frame (keep size)", lambda: self.crop_image(True))
        self._act(m, "Replace Image...", self.replace_image)
        self.fill_fit_menu(m.addMenu("Fit"))
        m = self.menuBar().addMenu("&Text")
        self.fill_text_menu(m)
        m = self.menuBar().addMenu("&Background Tools")
        self.fill_bg_menu(m)
        m = self.menuBar().addMenu("&Canvas")
        self._act(m, "Background (solid / gradient / texture)...", self.pick_bg)
        self._act(m, "Custom Slide Size...", self.custom_size)
        # one-click items right on the main ribbon
        self.menuBar().addAction("Templates", self.templates)
        a = self.menuBar().addAction("Edit Image", self.edit_image)
        a.setShortcut("Ctrl+E")

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction("Undo", self.undo)
        tb.addAction("Redo", self.redo)
        tb.addSeparator()
        tb.addAction("Add Image", self.add_image)
        tb.addAction("Add Text", self.add_text)
        tb.addAction("Crop", self.crop_image)
        tb.addAction("Replace Image", self.replace_image)
        tb.addAction("Grids", self.add_grid)
        tb.addAction("Full Screen", self.preview_fullscreen)
        tb.addSeparator()
        tb.addAction("Send to Front", lambda: self.arrange("forward"))
        tb.addAction("Send to Back", lambda: self.arrange("backward"))
        tb.addAction("Delete", self.delete_selected)
        tb.addSeparator()
        tb.addWidget(QLabel(" Panels: "))
        self.n_spin = QSpinBox()
        self.n_spin.setRange(1, 20)
        self.n_spin.valueChanged.connect(self.set_panels)
        tb.addWidget(self.n_spin)
        tb.addWidget(QLabel(" Rows: "))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 20)
        self.rows_spin.valueChanged.connect(self.set_rows)
        tb.addWidget(self.rows_spin)
        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.preset.currentTextChanged.connect(self.set_preset)
        tb.addWidget(self.preset)
        tb.addAction("Toggle Guides", self.toggle_guides)
        snap = tb.addAction("Snap")
        snap.setCheckable(True)
        snap.setChecked(True)
        snap.toggled.connect(lambda v: setattr(self.scene, "snap_enabled", v))
        tb.addSeparator()
        tb.addAction("Export Slides", self.export)
        tb.addAction("Export MP4", self.export_video)

    def _build_side_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.s_scale = self._slider(lay, "Scale (%)", 2, 1000, self.apply_scale)
        self.s_rot = self._slider(lay, "Rotation (deg)", -180, 180, self.apply_rot)
        self.s_op = self._slider(lay, "Opacity (%)", 5, 100, self.apply_opacity)
        grid = QGridLayout()
        self.pos_boxes = {}
        for i, (k, label, lo, hi) in enumerate((("x", "X (px)", -30000, 60000), ("y", "Y (px)", -30000, 60000),
                                                 ("w", "Width", 1, 30000), ("h", "Height", 1, 30000),
                                                 ("r", "Rotation", -180, 180))):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setKeyboardTracking(False)
            sb.valueChanged.connect(lambda v, k=k: self.apply_pos(k, v))
            self.pos_boxes[k] = sb
            grid.addWidget(QLabel(label), (i // 2) * 2, i % 2)
            grid.addWidget(sb, (i // 2) * 2 + 1, i % 2)
        lay.addLayout(grid)
        lay.addWidget(QLabel("Width/Height keep the aspect ratio (always locked)."))
        lay.addStretch()
        lay.addWidget(QLabel("Tips:\n- Mouse wheel = zoom view\n- Double-click text to edit\n"
                             "- Drag corner squares to resize\n- Drag round handle to rotate (Shift = 15 deg steps)\n- Moving, resizing and rotating snap to slides, other layers and 45-degree angles (hold Alt to bypass)\n- Right-click a layer: lock, duplicate, delete...\n- F11 = full screen preview (Esc leaves)\n- Del removes selection\n- Ctrl+Z / Ctrl+Y undo / redo\n"
                             "- Ctrl+S saves the project\n- Pink dashed lines = slide cuts"))
        self.side_dock = dock = QDockWidget("Selected layer", self)
        dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _slider(self, lay, label, lo, hi, fn):
        lay.addWidget(QLabel(label))
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.valueChanged.connect(fn)
        s.sliderReleased.connect(self.commit)
        lay.addWidget(s)
        return s

    # ---------- state snapshot / history ----------
    def content_items(self):
        return [i for i in self.scene.items() if isinstance(i, LAYERS)]

    def item_dict(self, it, z):
        d = {"x": round(it.x(), 2), "y": round(it.y(), 2), "scale": round(it.scale(), 4),
             "rot": round(it.rotation(), 2), "op": round(it.opacity(), 2), "z": z,
             "locked": bool(it.data(1)), "fx": bool(it.data(2)), "fy": bool(it.data(3))}
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
            d.update(type="video", path=it.path, w=round(it.size().width(), 1), h=round(it.size().height(), 1))
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
            it = VideoItem(d["path"], QSizeF(d["w"], d["h"]))
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

    def edit_image(self):
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
        self.layer_list.setIconSize(QSize(44, 44))
        self.layer_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layer_list.customContextMenuRequested.connect(self.layer_menu)
        self.layer_list.itemSelectionChanged.connect(self.list_select)
        self.layer_list.model().rowsMoved.connect(lambda *a: QTimer.singleShot(0, self.list_reordered))
        dock = QDockWidget("Layers (drag to reorder, right-click for options)", self)
        dock.setWidget(self.layer_list)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def layer_label(self, it):
        if isinstance(it, TextItem):
            name = "T  " + (it.toPlainText().strip().replace("\n", " ")[:28] or "Text")
        elif isinstance(it, ShapeItem):
            name = {"rect": "Rectangle", "ellipse": "Ellipse", "line": "Line"}[it.kind]
        elif isinstance(it, GridItem):
            name = f"Grid ({it.count()} cells)" if it.cells else f"Grid {it.rows}x{it.cols}"
        elif HAS_VIDEO and isinstance(it, VideoItem):
            name = "Video  " + Path(it.path).name
        else:
            name = "Image"
        return ("\U0001F512 " if it.data(1) else "") + name

    def refresh_layers(self):
        self.syncing = True
        self.layer_list.clear()
        self.layer_refs = sorted(self.content_items(), key=lambda i: -i.zValue())
        for k, it in enumerate(self.layer_refs):
            li = QListWidgetItem(QIcon(self.layer_icon(it)), self.layer_label(it))
            li.setData(Qt.UserRole, k)
            self.layer_list.addItem(li)
            li.setSelected(it.isSelected())
        self.syncing = False

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
        rows = {self.layer_list.row(i) for i in self.layer_list.selectedItems()}
        self.syncing = True
        self.scene.clearSelection()
        for r in rows:
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
            QMessageBox.warning(self, "Video", "QtMultimedia is not available in this PySide6 install.")
            return
        f, _ = QFileDialog.getOpenFileName(self, "Add video", "", "Video (" + VID_EXT + ")")
        if f:
            self.scene.add_item(VideoItem(f, None, int(self.scene.pw * 0.8)), self.view_center())
            self.commit()

    def toggle_video(self):
        if HAS_VIDEO:
            for it in self.content_items():
                if isinstance(it, VideoItem):
                    pl = it.player
                    pl.pause() if pl.playbackState() == QMediaPlayer.PlayingState else pl.play()

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

    def export_video(self):
        """One H.264 .mp4 per slide. Videos are decoded with OpenCV and composited into every frame;
        writing uses OpenCV's Windows Media Foundation encoder (falls back to mp4v)."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            QMessageBox.warning(self, "MP4 export", "MP4 export needs two extra packages:\n\npip install opencv-python numpy")
            return
        sc = self.scene
        vids = [i for i in self.content_items() if HAS_VIDEO and isinstance(i, VideoItem)]
        if not vids:
            QMessageBox.information(self, "MP4 export", "Add a video layer first (Insert > Video).\nFor photos only, use Export Slides.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Export MP4 slides to folder")
        if not folder:
            return
        fps, caps, writers, proxies, dlg = 30, [], [], [], None
        old_guides = sc.show_guides
        sc.clearSelection()
        sc.exporting, sc.show_guides = True, False
        for v in vids:
            v.player.pause()
            v.setVisible(False)
        try:
            for v in vids:
                cap = cv2.VideoCapture(v.path)
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                caps.append({"cap": cap, "n": n, "fps": cap.get(cv2.CAP_PROP_FPS) or 30.0, "last": -2})
                if not cap.isOpened() or n <= 0:
                    raise RuntimeError(f"Could not decode {Path(v.path).name}. HEVC may need the Microsoft 'HEVC Video Extensions'.")
            total = max(1, min(int(max(c["n"] / c["fps"] for c in caps) * fps), fps * 120))
            fourcc = cv2.VideoWriter_fourcc(*"H264")
            for k in range(sc.n * sc.rows):
                path = str(Path(folder) / f"slide_{k + 1:02d}.mp4")
                w = cv2.VideoWriter(path, cv2.CAP_MSMF, fourcc, fps, (sc.pw, sc.ph))
                if not w.isOpened():
                    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (sc.pw, sc.ph))
                if not w.isOpened():
                    raise RuntimeError("No MP4 encoder could be opened (try even slide sizes like 1080 x 1350).")
                writers.append(w)
            for v in vids:   # stand-in layers that carry the current decoded frame
                pr = QGraphicsPixmapItem()
                c = v.boundingRect().center()
                pr.setTransformOriginPoint(c)
                pr.setPos(v.pos())
                pr.setScale(v.scale())
                pr.setRotation(v.rotation())
                pr.setOpacity(v.opacity())
                pr.setZValue(v.zValue())
                sc.addItem(pr)
                proxies.append(pr)
            dlg = QProgressDialog("Rendering frames...", "Cancel", 0, total, self)
            dlg.setWindowModality(Qt.WindowModal)
            img = QImage(sc.pw, sc.ph, QImage.Format_RGB32)
            for fi in range(total):
                if dlg.wasCanceled():
                    break
                for v, c, pr in zip(vids, caps, proxies):
                    idx = int(fi / fps * c["fps"]) % c["n"]
                    if idx != c["last"]:
                        if idx != c["last"] + 1:
                            c["cap"].set(cv2.CAP_PROP_POS_FRAMES, idx)
                        ok, fr = c["cap"].read()
                        if ok:
                            rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
                            h_, w_ = rgb.shape[:2]
                            q = QImage(rgb.data, w_, h_, rgb.strides[0], QImage.Format_RGB888).copy()
                            pr.setPixmap(QPixmap.fromImage(q.scaled(int(v.size().width()), int(v.size().height()),
                                                                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation)))
                        c["last"] = idx
                for k, w in enumerate(writers):
                    img.fill(sc.bg)
                    p = QPainter(img)
                    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
                    sc.render(p, QRectF(0, 0, sc.pw, sc.ph),
                              QRectF((k % sc.n) * sc.pw, (k // sc.n) * sc.ph, sc.pw, sc.ph))
                    p.end()
                    a = np.frombuffer(img.constBits(), np.uint8).reshape(sc.ph, img.bytesPerLine() // 4, 4)[:, :sc.pw, :3]
                    w.write(np.ascontiguousarray(a))
                dlg.setValue(fi + 1)
                QApplication.processEvents()
            done = not dlg.wasCanceled()
        except Exception as ex:
            done = False
            QMessageBox.critical(self, "MP4 export failed", str(ex))
        finally:
            for w in writers:
                w.release()
            for c in caps:
                c["cap"].release()
            for pr in proxies:
                sc.removeItem(pr)
            for v in vids:
                v.setVisible(True)
                v.player.play()
            sc.exporting, sc.show_guides = False, old_guides
            sc.update()
            if dlg:
                dlg.close()
        if done:
            QMessageBox.information(self, "Done", f"Exported {len(writers)} MP4 slides to:\n{folder}\n\n(Video only - no audio.)")

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

    def export(self):
        d = ExportDialog(self, self.auto_export_scale())
        if not d.exec():
            return
        fmt, scale, folder = d.fmt, d.scale, d.folder
        if not folder:
            return
        sc = self.scene
        sc.clearSelection()
        sc.exporting = True
        sc.show_guides = False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        done, err = 0, None
        try:
            W, H = int(sc.pw * scale), int(sc.ph * scale)
            for i in range(sc.n * sc.rows):
                img = QImage(W, H, QImage.Format_RGB32)
                img.fill(sc.bg)
                p = QPainter(img)
                p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
                sc.render(p, QRectF(0, 0, W, H), QRectF((i % sc.n) * sc.pw, (i // sc.n) * sc.ph, sc.pw, sc.ph))
                p.end()
                err = save_image_hq(img, Path(folder) / f"slide_{i + 1:02d}", fmt)
                if err:
                    break
                done += 1
                QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()
            sc.exporting = False
            sc.show_guides = True
            sc.update()
        if err:
            QMessageBox.warning(self, "Export", err)
        if done:
            QMessageBox.information(self, "Done", f"Exported {done} slide(s) at {int(sc.pw * scale)} x {int(sc.ph * scale)} px "
                                                  f"({fmt}, no quality loss) to:\n{folder}")


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
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Winserendipity.Aero.Beta")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_BUILD)
    app.setWindowIcon(app_icon())      # every window / dialog inherits it
    apply_theme(app)
    w = Main()
    start = StartScreen(w)
    if start.exec() != QDialog.Accepted:
        sys.exit(0)
    start.perform()
    w.show()
    sys.exit(app.exec())
