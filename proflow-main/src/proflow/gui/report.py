"""Turn an Express calculation into a previewable, printable, exportable report."""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from proflow.graph.express import rating_plot, section_plot
from proflow.gui.plots import render_image
from proflow.model.express import Calculation
from proflow.reports.express import RATING_IMAGE, SECTION_IMAGE, report_html


def report_images(calc: Calculation) -> dict[str, QImage]:
    images = {SECTION_IMAGE: render_image(section_plot(calc))}
    rating = rating_plot(calc)
    if rating is not None:
        images[RATING_IMAGE] = render_image(rating)
    return images


def report_document(
    calc: Calculation, document: QTextDocument | None = None
) -> QTextDocument:
    doc = document or QTextDocument()
    images = report_images(calc)
    for name, image in images.items():
        doc.addResource(QTextDocument.ImageResource, QUrl(name), image)
    doc.setHtml(report_html(calc, {name: name for name in images}))
    return doc


def export_pdf(calc: Calculation, path: Path) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.Letter))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    writer.setResolution(150)
    writer.setTitle(calc.inputs.title or "Pro-Flow report")
    writer.setCreator("Pro-Flow")
    doc = report_document(calc)
    doc.setPageSize(
        writer.pageLayout().paintRectPixels(writer.resolution()).size().toSizeF()
    )
    doc.print_(writer)


def _png_data_uri(image: QImage) -> str:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")


def export_html(calc: Calculation, path: Path) -> None:
    """A self-contained HTML file (plots embedded as PNG data URIs)."""
    uris = {name: _png_data_uri(image) for name, image in report_images(calc).items()}
    body = report_html(calc, uris)
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{calc.inputs.title or 'Pro-Flow report'}</title></head>"
        f"<body style='max-width:820px;margin:24px auto'>{body}</body></html>"
    )
    Path(path).write_text(page, encoding="utf-8")
