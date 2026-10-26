"""Printable report for an Express calculation, as HTML.

Kept to the HTML subset Qt's rich-text engine renders (tables, inline styles,
images), so the same document previews in the app, prints to PDF through Qt,
and opens in a browser. Plot images are referenced by name; the caller
supplies them (Qt resources for preview and PDF, data URIs for a file).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime

from proflow import __version__
from proflow.model.express import (
    COMPUTE_LABELS,
    METHOD_STATUS,
    Calculation,
    ChannelInputs,
)

SECTION_IMAGE = "section.png"
RATING_IMAGE = "rating.png"

ACCENT = "#1f5fbf"
WARN = "#b45309"
INK = "#1f2933"
MUTED = "#52606d"
RULE = "#d9e2ec"


@dataclass(frozen=True)
class Row:
    label: str
    value: str
    unit: str = ""


def _f(v: float, places: int = 3) -> str:
    return f"{v:,.{places}f}"


def channel_input_rows(x: ChannelInputs) -> list[Row]:
    rows = [Row("Section", x.section.capitalize())]
    if x.section != "triangular":
        rows.append(Row("Bottom width", _f(x.bottom_width, 2), "ft"))
    if x.section != "rectangular":
        rows.append(
            Row("Side slopes (z:1)", f"{x.left_slope:g}, {x.right_slope:g}", "H:V")
        )
    rows += [
        Row("Total depth", _f(x.total_depth, 2), "ft"),
        Row("Invert elevation", _f(x.invert_elevation, 2), "ft"),
        Row("Slope", _f(x.slope_percent, 3), "%"),
        Row("Manning's n", f"{x.n:.3f}", ""),
        Row("Compute by", COMPUTE_LABELS[x.compute_by]),
    ]
    if x.compute_by == "known_q":
        rows.append(Row("Known Q", _f(x.known_q, 2), "cfs"))
    elif x.compute_by == "known_depth":
        rows.append(Row("Known depth", _f(x.known_depth, 3), "ft"))
    else:
        rows.append(Row("Increments", str(x.increments)))
    return rows


RESULT_FIELDS = (
    ("Depth", "depth", "ft"),
    ("Q", "flow", "cfs"),
    ("Area", "area", "ft²"),
    ("Velocity", "velocity", "ft/s"),
    ("Wetted perimeter", "wetted_perimeter", "ft"),
    ("Critical depth, Yc", "critical_depth", "ft"),
    ("Top width", "top_width", "ft"),
    ("EGL (depth + V²/2g)", "egl", "ft"),
    ("Froude number", "froude", ""),
)


def result_rows(calc: Calculation) -> list[Row]:
    s = calc.state
    if s is None:
        return []
    rows = [
        Row(label, _f(getattr(s, key)), unit)
        for label, key, unit in RESULT_FIELDS
        if hasattr(s, key)
    ]
    if hasattr(s, "regime"):
        rows.append(Row("Flow regime", s.regime))
    return rows


def _table(rows: list[Row]) -> str:
    cells = "".join(
        f"<tr><td style='padding:3px 10px 3px 0;color:{MUTED}'>{html.escape(r.label)}</td>"
        f"<td align='right' style='padding:3px 6px;color:{INK}'><b>{html.escape(r.value)}</b></td>"
        f"<td style='padding:3px 0;color:{MUTED}'>{html.escape(r.unit)}</td></tr>"
        for r in rows
    )
    return f"<table cellspacing='0' cellpadding='0'>{cells}</table>"


def _rating_table(calc: Calculation) -> str:
    head = "".join(
        f"<th align='right' style='padding:4px 8px;border-bottom:1px solid {RULE}'>{html.escape(label)}"
        f"<br><span style='color:{MUTED};font-weight:normal'>{unit or '&nbsp;'}</span></th>"
        for label, _, unit in RESULT_FIELDS
    )
    body = ""
    for i, s in enumerate(calc.rows):
        shade = "background-color:#eef4fc;" if i == calc.highlighted else ""
        body += (
            "<tr>"
            + "".join(
                f"<td align='right' style='padding:3px 8px;{shade}'>{_f(getattr(s, key))}</td>"
                for _, key, _ in RESULT_FIELDS
            )
            + "</tr>"
        )
    return f"<table cellspacing='0' cellpadding='0' width='100%'><tr>{head}</tr>{body}</table>"


def report_html(
    calc: Calculation,
    images: dict[str, str] | None = None,
    when: datetime | None = None,
) -> str:
    """The full report. images maps SECTION_IMAGE / RATING_IMAGE to img src values."""
    images = images or {}
    x = calc.inputs
    title = html.escape(x.title or ("Channel" if calc.kind == "channel" else "Weir"))
    kind = "Channel report" if calc.kind == "channel" else "Weir report"
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")
    parts = [
        f"<div style='font-family:Segoe UI, Arial, sans-serif;color:{INK}'>",
        f"<p style='margin:0;color:{MUTED}'>Pro-Flow {__version__} &middot; {kind} &middot; {stamp}</p>",
        f"<h1 style='margin:2px 0 6px 0;font-size:18pt'>{title}</h1>",
        f"<p style='margin:0 0 4px 0;color:{WARN}'><b>{html.escape(METHOD_STATUS)}</b></p>",
        f"<p style='margin:0;color:{MUTED}'>Method <code>{html.escape(calc.method or '-')}</code>"
        f" &middot; Depths: {html.escape(calc.depth_reporting)}</p>",
        f"<hr style='border:0;border-top:1px solid {RULE}'>",
        "<table width='100%' cellspacing='0' cellpadding='0'><tr>",
        f"<td valign='top' width='48%'><h3 style='color:{ACCENT}'>Inputs</h3>",
    ]
    rows = channel_input_rows(x) if calc.kind == "channel" else []
    parts.append(_table(rows))
    parts.append(
        f"</td><td width='4%'></td><td valign='top' width='48%'><h3 style='color:{ACCENT}'>Results</h3>"
    )
    if calc.ok:
        parts.append(_table(result_rows(calc)))
    else:
        parts.append(
            f"<p style='color:{WARN}'><b>{html.escape(str(calc.status))}</b>: "
            f"{html.escape(calc.message)}</p>"
        )
    parts.append("</td></tr></table>")
    for heading, items, color in (
        ("Warnings", calc.warnings, WARN),
        ("Notes", calc.notes, MUTED),
    ):
        if items:
            lis = "".join(f"<li>{html.escape(w)}</li>" for w in items)
            parts.append(
                f"<h3 style='color:{color}'>{heading}</h3><ul style='margin-top:0'>{lis}</ul>"
            )
    if not calc.warnings:
        parts.append(f"<p style='color:{MUTED}'>Warnings: none.</p>")
    if SECTION_IMAGE in images:
        parts.append(
            f"<h3 style='color:{ACCENT}'>Cross-section</h3><p><img src='{images[SECTION_IMAGE]}' width='640'></p>"
        )
    if RATING_IMAGE in images:
        parts.append(
            f"<h3 style='color:{ACCENT}'>Rating curve</h3><p><img src='{images[RATING_IMAGE]}' width='640'></p>"
        )
    if calc.ok and len(calc.rows) > 1:
        parts.append(
            f"<h3 style='color:{ACCENT}'>Q vs. depth</h3>{_rating_table(calc)}"
        )
    parts.append(
        f"<p style='margin-top:14px;color:{MUTED};font-size:8pt'>Manning's equation with k = 1.486 "
        "(published Express reports reproduce with 1.486; the Express manual prints 1.49). "
        "US customary units.</p></div>"
    )
    return "".join(parts)
