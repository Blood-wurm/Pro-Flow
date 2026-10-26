"""Paint a PlotSpec with QPainter: on screen (PlotWidget) and into report images."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from proflow.graph.express import PlotSpec
from proflow.gui import style


def nice_ticks(low: float, high: float, target: int = 6) -> list[float]:
    if high <= low:
        high = low + 1
    raw = (high - low) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.floor(low / step + 1e-9)
    last = math.ceil(high / step - 1e-9)  # the axis always covers the data
    return [round(k * step, 10) for k in range(first, last + 1)]


def _fmt(v: float) -> str:
    return f"{v:g}" if abs(v) >= 1e-9 else "0"


def _pen(style_name: str) -> QPen:
    pens = {
        "outline": QPen(style.GROUND, 2.2),
        "line": QPen(style.WATER_LINE, 1.8),
        "dash": QPen(style.EGL, 1.6, Qt.DashLine),
        "dot": QPen(style.CRITICAL, 1.6, Qt.DotLine),
        "marker": QPen(style.WATER_LINE, 1.6),
        "water": QPen(Qt.NoPen),
    }
    pen = pens[style_name]
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def paint_plot(p: QPainter, rect: QRectF, spec: PlotSpec) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.fillRect(rect, QColor(style.CARD))
    base = QFont(style.FONT_FAMILY)
    base.setPointSizeF(8.5)
    p.setFont(base)
    fm = p.fontMetrics()

    points = [pt for s in spec.series for pt in s.points]
    if not points:
        p.restore()
        return
    xs, ys = [x for x, _ in points], [y for _, y in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    xpad, ypad = (x1 - x0 or 1) * 0.04, (y1 - y0 or 1) * 0.12
    xt = nice_ticks(x0 if x0 == 0 else x0 - xpad, x1 + xpad)
    # Axes whose data starts at zero (depth, flow) start at zero.
    y_low = y0 if y0 == 0 else y0 - ypad * 0.3
    yt = nice_ticks(y_low, y1 + ypad)
    x0, x1, y0, y1 = xt[0], xt[-1], yt[0], yt[-1]

    title_h = fm.height() * 2 + 10
    legend_h = fm.height() + 10
    left = max(fm.horizontalAdvance(_fmt(v)) for v in yt) + fm.height() + 16
    area = QRectF(
        rect.left() + left,
        rect.top() + title_h,
        rect.width() - left - 16,
        rect.height() - title_h - legend_h - fm.height() * 2 - 8,
    )

    def px(x: float) -> float:
        return area.left() + (x - x0) / (x1 - x0) * area.width()

    def py(y: float) -> float:
        return area.bottom() - (y - y0) / (y1 - y0) * area.height()

    # title
    bold = QFont(base)
    bold.setWeight(QFont.DemiBold)
    bold.setPointSizeF(9.5)
    p.setFont(bold)
    p.setPen(QColor(style.INK))
    p.drawText(
        QRectF(rect.left() + 12, rect.top() + 4, rect.width(), title_h), spec.title
    )
    p.setFont(base)

    # grid and ticks
    p.setPen(QPen(QColor(style.RULE), 1))
    for v in xt:
        p.drawLine(QPointF(px(v), area.top()), QPointF(px(v), area.bottom()))
    for v in yt:
        p.drawLine(QPointF(area.left(), py(v)), QPointF(area.right(), py(v)))
    p.setPen(QColor(style.MUTED))
    for v in xt:
        r = QRectF(px(v) - 40, area.bottom() + 4, 80, fm.height())
        p.drawText(r, Qt.AlignHCenter | Qt.AlignTop, _fmt(v))
    for v in yt:
        r = QRectF(area.left() - left, py(v) - fm.height() / 2, left - 8, fm.height())
        p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, _fmt(v))
    p.drawText(
        QRectF(area.left(), area.bottom() + fm.height() + 6, area.width(), fm.height()),
        Qt.AlignHCenter,
        spec.x_label,
    )
    p.save()
    p.translate(rect.left() + 4, area.center().y())
    p.rotate(-90)
    p.drawText(
        QRectF(-area.height() / 2, 0, area.height(), fm.height()),
        Qt.AlignHCenter,
        spec.y_label,
    )
    p.restore()

    # series, in order: fills first as given by the spec
    p.setClipRect(area.adjusted(-2, -2, 2, 2))
    for s in spec.series:
        pts = [QPointF(px(x), py(y)) for x, y in s.points]
        if s.style == "water":
            path = QPainterPath()
            path.addPolygon(QPolygonF(pts))
            path.closeSubpath()
            p.fillPath(path, QBrush(style.WATER))
        elif s.style == "marker":
            p.setPen(_pen("marker"))
            p.setBrush(QColor(style.CARD))
            for pt in pts:
                p.drawEllipse(pt, 4.5, 4.5)
        else:
            p.setPen(_pen(s.style))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(pts))
    p.setClipping(False)

    # legend
    x = area.left()
    y = rect.bottom() - legend_h + 4
    for s in (s for s in spec.series if s.name):
        if s.style == "water":
            p.fillRect(QRectF(x, y + 3, 18, fm.height() - 6), QBrush(style.WATER))
        elif s.style == "marker":
            p.setPen(_pen("marker"))
            p.setBrush(QColor(style.CARD))
            p.drawEllipse(QPointF(x + 9, y + fm.height() / 2), 4, 4)
        else:
            p.setPen(_pen(s.style))
            p.drawLine(
                QPointF(x, y + fm.height() / 2), QPointF(x + 18, y + fm.height() / 2)
            )
        p.setPen(QColor(style.MUTED))
        p.drawText(QPointF(x + 24, y + fm.ascent()), s.name)
        x += 24 + fm.horizontalAdvance(s.name) + 18
    if spec.note:
        p.drawText(
            QRectF(rect.left(), y, rect.width() - 12, fm.height()),
            Qt.AlignRight,
            spec.note,
        )
    p.restore()


def render_image(
    spec: PlotSpec, size: QSize = QSize(800, 400), scale: float = 2.0
) -> QImage:
    image = QImage(size * scale, QImage.Format_ARGB32)
    image.setDevicePixelRatio(scale)
    image.fill(QColor(style.CARD))
    painter = QPainter(image)
    paint_plot(painter, QRectF(0, 0, size.width(), size.height()), spec)
    painter.end()
    return image


class PlotWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec: PlotSpec | None = None
        self.empty_text = "No result to plot."
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_spec(self, spec: PlotSpec | None) -> None:
        self._spec = spec
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(style.CARD))
        if self._spec is not None:
            paint_plot(painter, QRectF(self.rect()).adjusted(4, 4, -4, -4), self._spec)
        else:
            painter.setPen(QColor(style.FAINT))
            painter.drawText(self.rect(), Qt.AlignCenter, self.empty_text)
        painter.end()
