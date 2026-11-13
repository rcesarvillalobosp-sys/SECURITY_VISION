"""Reporte en PDF con ReportLab (licencia BSD): resumen, gráficas, tablas y listado de incidentes."""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from security_vision.core.domain.reports import ReportData
from security_vision.core.interfaces.alerts import ReportRenderer

from .common import END_REASON_LABEL, METHODOLOGY, STATUS_LABEL, fmt_dt, pct, period_text, vlabel

INK = colors.HexColor("#1d2733")
MUTED = colors.HexColor("#6b7785")
ACCENT = colors.HexColor("#d98a00")
OK = colors.HexColor("#1f9d63")
ALERT = colors.HexColor("#d63a3a")
GRID = colors.HexColor("#d5dbe2")
HEAD_BG = colors.HexColor("#eef1f4")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=17, leading=21, alignment=TA_LEFT,
                                textColor=INK, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9, textColor=MUTED, leading=12),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=11.5, textColor=INK, spaceBefore=10,
                             spaceAfter=5),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=8.5, leading=11, textColor=INK),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=7.5, leading=10, textColor=MUTED),
        "kpi_v": ParagraphStyle("kv", parent=base["Normal"], fontSize=15, leading=18, textColor=INK),
        "kpi_l": ParagraphStyle("kl", parent=base["Normal"], fontSize=7, leading=9, textColor=MUTED),
    }


def _table(rows: list[list[object]], widths: list[float], *, numeric_from: int = 1) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, MUTED),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, GRID),
        ("ALIGN", (numeric_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def _bar_incidents(r: ReportData, width: float) -> Drawing:
    d = Drawing(width, 120)
    d.add(String(0, 110, "Incidentes por día", fontName="Helvetica-Bold", fontSize=8, fillColor=INK))
    data = [x.incidents for x in r.days]
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 24, 18, width - 34, 82
    ch.data = [data or [0]]
    ch.bars[0].fillColor = ACCENT
    ch.bars[0].strokeColor = None
    ch.valueAxis.valueMin = 0
    top = max(data or [0])
    ch.valueAxis.valueMax = max(1, top + max(1, top // 5))
    ch.valueAxis.valueStep = max(1, (top + 4) // 5)
    ch.valueAxis.labels.fontSize = 6.5
    ch.categoryAxis.categoryNames = _day_labels(r)
    ch.categoryAxis.labels.fontSize = 6.5
    ch.categoryAxis.labels.angle = 0 if len(data) <= 10 else 90
    ch.categoryAxis.labels.dy = -2 if len(data) <= 10 else -8
    d.add(ch)
    return d


def _line_compliance(r: ReportData, width: float) -> Drawing | None:
    vals = [x.compliance_pct for x in r.days]
    if not any(v is not None for v in vals):
        return None
    d = Drawing(width, 120)
    d.add(String(0, 110, "Cumplimiento diario (%)", fontName="Helvetica-Bold", fontSize=8, fillColor=INK))
    ch = HorizontalLineChart()
    ch.x, ch.y, ch.width, ch.height = 24, 18, width - 34, 82
    # Los días sin datos se dejan en blanco (None), no se dibujan como 0 %
    ch.data = [vals]
    ch.lines[0].strokeColor = OK
    ch.lines[0].strokeWidth = 1.6
    ch.joinedLines = 1
    ch.valueAxis.valueMin, ch.valueAxis.valueMax, ch.valueAxis.valueStep = 0, 100, 20
    ch.valueAxis.labels.fontSize = 6.5
    ch.categoryAxis.categoryNames = _day_labels(r)
    ch.categoryAxis.labels.fontSize = 6.5
    ch.categoryAxis.labels.angle = 0 if len(vals) <= 10 else 90
    ch.categoryAxis.labels.dy = -2 if len(vals) <= 10 else -8
    from reportlab.graphics.widgets.markers import makeMarker

    ch.lines[0].symbol = makeMarker("FilledCircle", size=2.5)
    d.add(ch)
    return d


def _day_labels(r: ReportData) -> list[str]:
    return [f"{x.day:%d/%m}" for x in r.days]


class PdfReportRenderer(ReportRenderer):
    format = "pdf"
    content_type = "application/pdf"

    def render(self, report: ReportData) -> bytes:
        r = report
        st = _styles()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm,
                                bottomMargin=16 * mm, title=r.title, author="Security Vision",
                                subject=f"Reporte {r.period}")
        W = doc.width
        story: list[object] = [
            Paragraph(escape(r.title), st["title"]),
            Paragraph(escape(f"Periodo: {period_text(r)}  ·  Cámaras: "
                             f"{', '.join(r.cameras_filter) if r.cameras_filter else 'todas'}"), st["sub"]),
            Paragraph(escape(f"Generado {fmt_dt(r, r.generated_at)} por {r.generated_by}"
                             + (f"  ·  Modelos: {', '.join(r.model_ids)}" if r.model_ids else "")), st["sub"]),
            Spacer(1, 8),
        ]
        kpis = [
            ("Incidentes", str(r.totals.get("incidents", 0))),
            ("Confirmados en revisión", str(r.totals.get("confirmed_by_review", 0))),
            ("Descartados (falsos positivos)", str(r.totals.get("discarded", 0))),
            ("Pendientes de revisión", str(r.totals.get("pending", 0))),
            ("Cumplimiento", pct(r.compliance_pct)),
            ("No verificable", pct(r.unverifiable_share_pct)),
        ]
        cells = [[Paragraph(escape(v), st["kpi_v"]) for _, v in kpis],
                 [Paragraph(escape(k), st["kpi_l"]) for k, _ in kpis]]
        kt = Table(cells, colWidths=[W / 6] * 6)
        kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
                                ("LINEABOVE", (0, 0), (-1, 0), 2, ACCENT), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story += [kt, Spacer(1, 10)]

        charts = [_bar_incidents(r, W / 2 - 6)]
        line = _line_compliance(r, W / 2 - 6)
        if line is not None:
            charts.append(line)
        else:
            charts.append(Paragraph("Sin datos de análisis en el periodo: no se puede calcular el cumplimiento.",
                                    st["small"]))
        story.append(Table([charts], colWidths=[W / 2, W / 2]))

        story.append(Paragraph("Incidentes por tipo", st["h2"]))
        if r.by_type:
            total = max(1, sum(r.by_type.values()))
            rows = [["Tipo", "Incidentes", "%"]] + [[vlabel(k), v, f"{100 * v / total:.1f}"]
                                                     for k, v in r.by_type.items()]
            story.append(_table(rows, [W * 0.5, W * 0.25, W * 0.25]))
        else:
            story.append(Paragraph("Sin incidentes en el periodo.", st["body"]))

        story.append(Paragraph("Por cámara", st["h2"]))
        if r.cameras:
            rows = [["Cámara", "Incidentes", "Confirm.", "Descart.", "Cumplimiento", "No verif.", "Máx. pers."]]
            for c in r.cameras:
                tot = c.compliant + c.possible + c.confirmed + c.unverifiable
                rows.append([Paragraph(escape(c.camera_name), st["body"]), c.incidents, c.confirmed_by_review,
                             c.discarded, pct(c.compliance_pct),
                             pct(round(100 * c.unverifiable / tot, 1) if tot else None), c.max_persons])
            story.append(_table(rows, [W * 0.3] + [W * 0.7 / 6] * 6))
        else:
            story.append(Paragraph("Sin datos de cámaras en el periodo.", st["body"]))

        story.append(Paragraph("Por día", st["h2"]))
        rows = [["Día", "Incidentes", "Conformes", "Posibles", "Confirmados", "No verif.", "Cumplimiento"]]
        rows += [[f"{d.day:%Y-%m-%d}", d.incidents, d.compliant, d.possible, d.confirmed, d.unverifiable,
                  pct(d.compliance_pct)] for d in r.days]
        story.append(_table(rows, [W * 0.22] + [W * 0.13] * 6))
        story.append(Paragraph("Conformes, posibles, confirmados y no verificables cuentan fotogramas-persona "
                               "analizados.", st["small"]))

        story.append(Paragraph("Listado de incidentes", st["h2"]))
        if r.incidents:
            rows = [["Confirmado", "Cámara", "Tipo", "Estado", "Conf.", "Cierre"]]
            for i in r.incidents:
                close = END_REASON_LABEL.get(i.end_reason or "", i.end_reason or "") if i.ended_at else "abierto"
                rows.append([fmt_dt(r, i.confirmed_at), Paragraph(escape(i.camera_name), st["body"]),
                             vlabel(i.violation_type), STATUS_LABEL.get(i.status, i.status), f"{i.confidence:.2f}",
                             close])
            story.append(_table(rows, [W * 0.2, W * 0.24, W * 0.14, W * 0.13, W * 0.09, W * 0.2], numeric_from=4))
            if r.incidents_truncated:
                story.append(Paragraph(f"Listado limitado a los primeros {len(r.incidents)} incidentes; el "
                                       "archivo Excel contiene el mismo límite. Use filtros por cámara o un periodo "
                                       "más corto para el detalle completo.", st["small"]))
        else:
            story.append(Paragraph("Sin incidentes en el periodo.", st["body"]))

        story.append(KeepTogether([Paragraph("Metodología", st["h2"]), Paragraph(escape(METHODOLOGY), st["small"])]))

        def footer(canvas, doc_) -> None:
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(MUTED)
            canvas.drawString(16 * mm, 9 * mm, f"Security Vision · {r.title}")
            canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Página {doc_.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return buf.getvalue()
