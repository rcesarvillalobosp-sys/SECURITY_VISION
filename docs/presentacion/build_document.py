"""Genera el documento técnico de Security Vision en PDF (ReportLab).

Uso: python docs/presentacion/build_document.py docs/presentacion/Security-Vision.pdf
Requiere reportlab y las fuentes de Windows Segoe UI, Cambria y Consolas.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(sys.argv[1])
F = "C:/Windows/Fonts/"
pdfmetrics.registerFont(TTFont("Body", F + "segoeui.ttf"))
pdfmetrics.registerFont(TTFont("BodyB", F + "segoeuib.ttf"))
pdfmetrics.registerFont(TTFont("BodySB", F + "seguisb.ttf"))
pdfmetrics.registerFont(TTFont("Math", F + "cambria.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("Mono", F + "consola.ttf"))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyB", italic="Body", boldItalic="BodyB")

INK = colors.HexColor("#14202c")
MUTED = colors.HexColor("#5f6b78")
ACCENT = colors.HexColor("#0e9f9a")
NAVY = colors.HexColor("#0f2a43")
LIGHT = colors.HexColor("#f3f5f7")
GRID = colors.HexColor("#d7dde3")
OK = colors.HexColor("#1f9d63")
ALERT = colors.HexColor("#d63a3a")
BLUE = colors.HexColor("#2f6fb3")

ss = {
    "h1": ParagraphStyle("h1", fontName="BodyB", fontSize=19, leading=24, textColor=NAVY, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="BodySB", fontSize=13, leading=17, textColor=NAVY, spaceBefore=10, spaceAfter=4),
    "h3": ParagraphStyle("h3", fontName="BodySB", fontSize=10.5, leading=14, textColor=INK, spaceBefore=6, spaceAfter=2),
    "p": ParagraphStyle("p", fontName="Body", fontSize=9.6, leading=13.6, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Body", fontSize=8, leading=11, textColor=MUTED),
    "li": ParagraphStyle("li", fontName="Body", fontSize=9.6, leading=13.4, textColor=INK, leftIndent=12,
                         bulletIndent=2, spaceAfter=2),
    "eq": ParagraphStyle("eq", fontName="Math", fontSize=11, leading=16, textColor=INK, alignment=TA_CENTER,
                         spaceBefore=3, spaceAfter=5),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=7.4, leading=10.2, textColor=INK, backColor=LIGHT,
                           borderPadding=(5, 6, 5, 6), spaceBefore=4, spaceAfter=8, leftIndent=4),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=8.2, leading=10.8, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="BodySB", fontSize=8.2, leading=10.8, textColor=INK),
    "cellm": ParagraphStyle("cellm", fontName="Mono", fontSize=7.6, leading=10, textColor=INK),
    "quote": ParagraphStyle("quote", fontName="Body", fontSize=10, leading=14, textColor=NAVY, leftIndent=10,
                            borderPadding=(6, 8, 6, 8), backColor=colors.HexColor("#e6f5f4"), spaceBefore=4,
                            spaceAfter=8),
}


HEAD = ParagraphStyle("head", parent=ss["cellb"], textColor=colors.white)


def P(t, s="p"):
    return Paragraph(t, ss[s])


def B(items):
    return [Paragraph(i, ss["li"], bulletText="•") for i in items]


def EQ(t):
    return Paragraph(t, ss["eq"])


def CODE(t):
    return Paragraph(escape(t).replace("\n", "<br/>").replace("  ", "&nbsp;&nbsp;"), ss["code"])


def T(rows, widths, head=True, mono_cols=(), zebra=True):
    data = []
    for ri, row in enumerate(rows):
        cells = []
        for ci, c in enumerate(row):
            style = HEAD if (head and ri == 0) else ss["cellm" if ci in mono_cols else "cell"]
            cells.append(Paragraph(str(c), style))
        data.append(cells)
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5), ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRID)]
    if head:
        st += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("LINEBELOW", (0, 0), (-1, 0), 1, ACCENT)]
    if zebra:
        for r in range(1 if head else 0, len(rows)):
            if r % 2 == 0:
                st.append(("BACKGROUND", (0, r), (-1, r), LIGHT))
    t.setStyle(TableStyle(st))
    return t


W = A4[0] - 36 * mm


# ------------------------------------------------------------------ diagramas
def box(d, x, y, w, h, text, fill=colors.white, stroke=NAVY, fs=7.6, bold=False, tc=INK):
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=fill, strokeColor=stroke, strokeWidth=0.9))
    lines = text.split("\n")
    lh = fs + 2
    y0 = y + h / 2 + (len(lines) - 1) * lh / 2 - fs / 3
    for i, ln in enumerate(lines):
        d.add(String(x + w / 2, y0 - i * lh, ln, fontName="BodySB" if (bold and i == 0) else "Body", fontSize=fs,
                     fillColor=tc, textAnchor="middle"))


def arrow(d, x1, y1, x2, y2, c=MUTED):
    d.add(Line(x1, y1, x2, y2, strokeColor=c, strokeWidth=1))
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    s = 4.5
    d.add(Polygon([x2, y2, x2 - s * math.cos(a - 0.4), y2 - s * math.sin(a - 0.4),
                   x2 - s * math.cos(a + 0.4), y2 - s * math.sin(a + 0.4)], fillColor=c, strokeColor=c))


def diagram_pipeline():
    d = Drawing(W, 150)
    steps = [("Cámara\nRTSP / USB", LIGHT), ("Captura\nPyAV + FrameSlot", LIGHT), ("Detección\nRT-DETRv2 · ONNX", colors.HexColor("#dcf2f0")),
             ("Tracking\nByteTrack + Kalman", LIGHT), ("Asociación\nEPP → persona", LIGHT),
             ("Reglas\nventana temporal", colors.HexColor("#dcf2f0")), ("Incidente\n+ evidencia", colors.HexColor("#fde3e3"))]
    n = len(steps)
    bw, gap = (W - 6 * 8) / n, 8
    y = 82
    for i, (t, f) in enumerate(steps):
        x = i * (bw + gap)
        box(d, x, y, bw, 42, t, fill=f, bold=True, fs=7.1)
        if i < n - 1:
            arrow(d, x + bw, y + 21, x + bw + gap, y + 21)
    # ramas inferiores
    box(d, 0, 10, bw * 2 + gap, 34, "MediaMTX → WebRTC\nvídeo en directo al navegador", fill=colors.white, fs=7)
    arrow(d, (bw + gap) * 1 + bw / 2, y, (bw * 2 + gap) / 2 + 20, 44)
    box(d, 3 * (bw + gap), 10, bw * 2 + gap, 34, "WebSocket en vivo\ncajas + estado por persona", fs=7)
    arrow(d, 5 * (bw + gap) + bw / 2, y, 3 * (bw + gap) + bw + gap / 2 + 30, 44)
    box(d, 5 * (bw + gap) + 4, 10, bw * 2 + gap - 4, 34, "Outbox → alertas\nwebhook firmado · correo", fs=7)
    arrow(d, 6 * (bw + gap) + bw / 2, y, 6 * (bw + gap) + bw / 2 - 4, 44)
    d.add(String(0, 138, "Flujo por fotograma analizado (2 por segundo por cámara, configurable)", fontName="BodySB",
                 fontSize=8, fillColor=MUTED))
    return d


def diagram_hexagon():
    d = Drawing(W, 262)
    cx, cy = W / 2, 120
    # núcleo
    d.add(Rect(cx - 102, cy - 55, 204, 110, rx=10, ry=10, fillColor=colors.HexColor("#dcf2f0"), strokeColor=ACCENT,
               strokeWidth=1.4))
    d.add(String(cx, cy + 36, "NÚCLEO (core)", fontName="BodyB", fontSize=9, fillColor=NAVY, textAnchor="middle"))
    for i, t in enumerate(["Dominio: taxonomía EPP, geometría, cumplimiento",
                           "Puertos: VideoSource · InferenceEngine · DetectionModel",
                           "ObjectTracker · SecurityEvaluator · MessageBus",
                           "ObjectStorage · AlertSender · ReportRenderer", "Sin frameworks (import-linter lo impide)"]):
        d.add(String(cx, cy + 18 - i * 12, t, fontName="Body", fontSize=6.8, fillColor=INK, textAnchor="middle"))
    d.add(Rect(cx - 88, cy - 92, 176, 30, rx=6, ry=6, fillColor=LIGHT, strokeColor=GRID))
    d.add(String(cx, cy - 74, "Casos de uso (modules)", fontName="BodySB", fontSize=7.3, fillColor=INK,
                 textAnchor="middle"))
    d.add(String(cx, cy - 85, "cámaras · reglas · incidentes · alertas · reportes", fontName="Body", fontSize=6.8,
                 fillColor=INK, textAnchor="middle"))
    left = [("Entrada (composición)", "API FastAPI · Worker · Web React", 200), ("Vídeo", "PyAV/FFmpeg · patrón de prueba\n(GStreamer: puerto listo)", 140),
            ("Inferencia", "ONNX Runtime CUDA/TensorRT/CPU\nOpenVINO CPU/GPU", 80), ("Modelos", "RT-DETRv2 · RF-DETR\nregistro con sha256", 20)]
    right = [("Persistencia", "PostgreSQL 17 · SQLAlchemy 2\nAlembic · auditoría inmutable", 200), ("Mensajería", "LISTEN/NOTIFY + outbox\n(Valkey/NATS: adaptador)", 140),
             ("Medios", "MediaMTX: RTSP→WebRTC\nautorizado por la API", 80), ("Salidas", "Webhook HMAC · SMTP\nPDF/Excel · Prometheus · OTel", 20)]
    for (title, txt, y) in left:
        box(d, 0, y, 130, 40, title + "\n" + txt, bold=True, fs=6.8)
        arrow(d, 130, y + 20, cx - 102, cy + (y - 110) * 0.3, c=BLUE)
    for (title, txt, y) in right:
        box(d, W - 130, y, 130, 40, title + "\n" + txt, bold=True, fs=6.8)
        arrow(d, W - 130, y + 20, cx + 102, cy + (y - 110) * 0.3, c=BLUE)
    d.add(String(cx, 252, "Arquitectura hexagonal: los adaptadores dependen del núcleo, nunca al revés",
                 fontName="BodySB", fontSize=8, fillColor=MUTED, textAnchor="middle"))
    return d


def diagram_states():
    d = Drawing(W, 185)
    pos = {"NO_VERIFICABLE": (0, 120), "EN_REVISION": (165, 120), "CUMPLIMIENTO": (330, 120),
           "POSIBLE_INCUMPLIMIENTO": (165, 30), "INCUMPLIMIENTO_CONFIRMADO": (330, 30)}
    fills = {"NO_VERIFICABLE": colors.HexColor("#e9ecef"), "EN_REVISION": colors.HexColor("#fff4cc"),
             "CUMPLIMIENTO": colors.HexColor("#d9f5e6"), "POSIBLE_INCUMPLIMIENTO": colors.HexColor("#ffe6cc"),
             "INCUMPLIMIENTO_CONFIRMADO": colors.HexColor("#fbd5d5")}
    bw, bh = 150, 34
    for k, (x, y) in pos.items():
        box(d, x, y, bw, bh, k.replace("_", " "), fill=fills[k], bold=True, fs=7.2)
    arrow(d, 150, 137, 165, 137)
    arrow(d, 315, 137, 330, 137)
    arrow(d, 240, 120, 240, 64)
    arrow(d, 315, 47, 330, 47)
    arrow(d, 405, 64, 405, 120, c=OK)
    notes = [(152, 158, "evaluable"), (316, 158, "todo EPP presente"), (246, 92, "algún EPP ausente"),
             (316, 22, "≥5 s sostenido + ≥2 «no_*»"), (412, 92, "EPP visto ≥4 s (histéresis)")]
    for x, y, t in notes:
        d.add(String(x, y, t, fontName="Body", fontSize=6.6, fillColor=MUTED))
    d.add(String(0, 174, "Estado por persona (se evalúa cada EPP exigido por su zona / perfil)", fontName="BodySB",
                 fontSize=8, fillColor=MUTED))
    return d


def chart_load():
    d = Drawing(W, 175)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 40, 30, W - 170, 120
    ch.data = [[2.00, 4.00, 4.40, 4.01, 3.89], [2.00, 3.98, 5.56, 5.64, 5.96]]
    ch.categoryAxis.categoryNames = ["1 cámara", "2", "4", "6", "8"]
    ch.valueAxis.valueMin, ch.valueAxis.valueMax, ch.valueAxis.valueStep = 0, 7, 1
    ch.bars[0].fillColor = colors.HexColor("#9aa8b6")
    ch.bars[1].fillColor = ACCENT
    for b in (0, 1):
        ch.bars[b].strokeColor = None
    ch.valueAxis.labels.fontName = ch.categoryAxis.labels.fontName = "Body"
    ch.valueAxis.labels.fontSize = ch.categoryAxis.labels.fontSize = 7
    ch.barSpacing, ch.groupSpacing = 2, 10
    d.add(ch)
    lg = Legend()
    lg.x, lg.y = W - 120, 130
    lg.fontName, lg.fontSize = "Body", 7.5
    lg.colorNamePairs = [(colors.HexColor("#9aa8b6"), "Base (antes)"), (ACCENT, "Optimizado (Fase 9)")]
    d.add(lg)
    d.add(String(0, 160, "Análisis por segundo en total (objetivo: 2 por cámara) · GTX 1650 portátil, medido",
                 fontName="BodySB", fontSize=8, fillColor=MUTED))
    return d


def chart_ap():
    d = Drawing(W, 160)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 30, 34, W - 40, 105
    names = ["person", "helmet", "vest", "boot", "gloves", "goggles", "no_helmet", "no_vest", "no_gloves", "no_goggles"]
    vals = [0.954, 0.849, 0.917, 0.826, 0.853, 0.965, 0.620, 0.787, 0.676, 0.428]
    ch.data = [vals]
    ch.categoryAxis.categoryNames = names
    ch.valueAxis.valueMin, ch.valueAxis.valueMax, ch.valueAxis.valueStep = 0, 1, 0.2
    ch.bars[0].fillColor = BLUE
    ch.bars[0].strokeColor = None
    for i, v in enumerate(vals):
        if v < 0.8:
            ch.bars[(0, i)].fillColor = ACCENT
    ch.valueAxis.labels.fontName = ch.categoryAxis.labels.fontName = "Body"
    ch.valueAxis.labels.fontSize = 7
    ch.categoryAxis.labels.fontSize = 6.6
    ch.categoryAxis.labels.angle = 0
    d.add(ch)
    d.add(String(0, 150, "AP50 por clase en test (69 imágenes) · en verde azulado las clases «sin EPP», más difíciles",
                 fontName="BodySB", fontSize=8, fillColor=MUTED))
    return d


# ------------------------------------------------------------------ portada y pie
def cover(c, doc):
    c.saveState()
    w, h = A4
    c.setFillColor(NAVY)
    c.rect(0, h * 0.42, w, h * 0.58, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    stripe = 14
    for i in range(0, int(w) + 40, 28):
        c.saveState()
        p = c.beginPath()
        p.moveTo(i, h * 0.42)
        p.lineTo(i + stripe, h * 0.42)
        p.lineTo(i + stripe - 10, h * 0.42 - 10)
        p.lineTo(i - 10, h * 0.42 - 10)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.restoreState()
    c.setFillColor(colors.white)
    c.setFont("BodySB", 11)
    c.drawString(22 * mm, h - 40 * mm, "VISIÓN POR COMPUTADOR · VÍDEO EN RED · INTELIGENCIA ARTIFICIAL")
    c.setFont("BodyB", 38)
    c.drawString(22 * mm, h - 70 * mm, "Security Vision")
    c.setFont("Body", 15)
    c.setFillColor(colors.HexColor("#8fe0da"))
    c.drawString(22 * mm, h - 82 * mm, "Plataforma de videovigilancia con IA para supervisar")
    c.drawString(22 * mm, h - 89 * mm, "el uso de equipos de protección individual (EPP)")
    c.setFillColor(colors.HexColor("#c9d3dd"))
    c.setFont("Body", 10.5)
    y = h - 108 * mm
    for ln in ["Detección con transformers (RT-DETRv2) · tracking multiobjeto (ByteTrack + Kalman)",
               "Motor de reglas temporal con verificabilidad · incidentes con evidencia firmada",
               "Arquitectura hexagonal · FastAPI · PostgreSQL · React · WebRTC · ONNX Runtime / OpenVINO",
               "Procesamiento 100 % local · sin reconocimiento facial ni biometría"]:
        c.drawString(22 * mm, y, ln)
        y -= 6.5 * mm
    # cifras clave
    stats = [("156", "tests automáticos\n(unitarios + integración)"), ("0,787", "mAP50 del modelo\nEPP piloto (test)"),
             ("+53 %", "capacidad tras\noptimizar (8 cámaras)"), ("10/10", "fases completadas\ny verificadas")]
    x0, yb = 22 * mm, h * 0.42 - 52 * mm
    bw = (w - 44 * mm - 3 * 6 * mm) / 4
    for i, (n, t) in enumerate(stats):
        x = x0 + i * (bw + 6 * mm)
        c.setFillColor(LIGHT)
        c.roundRect(x, yb, bw, 34 * mm, 6, fill=1, stroke=0)
        c.setFillColor(ACCENT)
        c.rect(x, yb + 34 * mm - 2.2, bw, 2.2, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.setFont("BodyB", 22)
        c.drawString(x + 5 * mm, yb + 20 * mm, n)
        c.setFillColor(MUTED)
        c.setFont("Body", 8.5)
        for j, ln in enumerate(t.split("\n")):
            c.drawString(x + 5 * mm, yb + 12 * mm - j * 4.2 * mm, ln)
    c.setFillColor(INK)
    c.setFont("BodySB", 10)
    c.drawString(22 * mm, 42 * mm, "Autor: Ricardo César Villalobos Pérez")
    c.setFont("Body", 9)
    c.setFillColor(MUTED)
    c.drawString(22 * mm, 35 * mm, "Documento técnico · piloto funcional diseñado para escalar")
    c.drawString(22 * mm, 29 * mm, "Todas las cifras de este documento están medidas en el sistema real; ninguna es estimada.")
    c.restoreState()


def later(c, doc):
    c.saveState()
    w, h = A4
    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.2)
    c.line(18 * mm, h - 13 * mm, w - 18 * mm, h - 13 * mm)
    c.setFont("BodySB", 8)
    c.setFillColor(NAVY)
    c.drawString(18 * mm, h - 11 * mm, "SECURITY VISION")
    c.setFont("Body", 8)
    c.setFillColor(MUTED)
    c.drawRightString(w - 18 * mm, h - 11 * mm, "Plataforma de videovigilancia con IA")
    c.drawRightString(w - 18 * mm, 10 * mm, f"{doc.page}")
    c.restoreState()


# ------------------------------------------------------------------ contenido
s = []
s.append(PageBreak())

# Índice
s.append(P("Contenido", "h1"))
toc = [("1", "Resumen ejecutivo"), ("2", "Características del sistema"), ("3", "Arquitectura y flujo de datos"), ("", "3.1 Transporte del vídeo por la red"),
       ("4", "Modelo matemático"), ("", "4.1 Detección: RT-DETRv2 y su función de pérdida"),
       ("", "4.2 Métricas de evaluación (IoU, AP, mAP)"), ("", "4.3 Seguimiento: filtro de Kalman y ByteTrack"),
       ("", "4.4 Asociación EPP → persona (asignación húngara con capacidades)"),
       ("", "4.5 Motor de reglas: verificabilidad, ventana ponderada e histéresis"),
       ("", "4.6 Indicadores y modelo de capacidad"), ("5", "Tecnologías utilizadas"),
       ("6", "Repositorio y fuentes externas"), ("7", "Escalabilidad"),
       ("8", "Dónde cambiar librerías y procesadores para mejorar la calidad de servicio"),
       ("9", "Cómo se entrenan los modelos"), ("10", "Calidad, seguridad y resultados medidos"),
       ("11", "Limitaciones y próximos pasos")]
s.append(T([[a, b] for a, b in toc], [14 * mm, W - 14 * mm], head=False, zebra=False))
s.append(Spacer(1, 10))
s.append(P("<b>Cómo leer este documento.</b> Las secciones 1–3 explican qué hace el sistema y cómo está construido; "
           "la 4 recoge el modelo matemático tal y como está implementado (fórmulas y parámetros por defecto del código); "
           "las 7–9 responden a cómo escalarlo, ajustarlo y reentrenarlo. Cada afirmación cuantitativa procede de una "
           "medición o un test del propio proyecto.", "p"))

# 1 Resumen
s.append(PageBreak())
s.append(P("1. Resumen ejecutivo", "h1"))
s.append(P("<b>El problema.</b> En obras, plantas y almacenes, supervisar que cada persona lleve casco, chaleco, "
           "botas, guantes o gafas es una tarea continua y propensa a errores. Las soluciones comerciales suelen "
           "depender de la nube, enviar imágenes de personas a terceros y producir alertas a partir de un único "
           "fotograma, lo que genera muchos falsos positivos."))
s.append(P("<b>La solución.</b> <i>Security Vision</i> es una plataforma completa, que se ejecuta en local, capaz de "
           "conectarse a cámaras IP o USB, detectar personas y EPP con un transformer de detección en tiempo real, "
           "seguir a cada persona entre fotogramas, atribuir cada EPP a la persona correcta y decidir con un motor de "
           "reglas temporal si hay un incumplimiento. Un incumplimiento solo se confirma cuando la ausencia es "
           "<b>sostenida</b> y hay <b>evidencia explícita</b>; si la persona no se ve bien, el sistema responde "
           "«no verificable» en lugar de inventar un incumplimiento."))
s.append(P("«La ausencia de detección no es ausencia de EPP»: este principio guía todo el diseño del motor de reglas.",
           "quote"))
s.append(P("<b>Enfoque de piloto escalable.</b> El proyecto se desarrolló como un <b>piloto</b>: una instalación real, "
           "de pequeña escala, con una cámara y una GPU de portátil, que permite validar de punta a punta la detección, "
           "las reglas y la operación antes de invertir en una implantación mayor. Desde el principio se diseñó para "
           "<b>crecer sin reescribirse</b>: añadir cámaras, workers o GPUs; cambiar el motor de inferencia, el modelo o el "
           "bus de mensajes por configuración o plugins; e incorporar nuevos EPP, zonas y canales de alerta. La sección 7 "
           "detalla cómo, y la 8, qué ajustar para mejorar la calidad de servicio."))
s.append(P("<b>Resultado.</b> Un sistema desplegable con:"))
s += B(["Panel web en tiempo real (vídeo WebRTC con superposición de cajas y estados por persona).",
        "Incidentes con evidencias firmadas (contexto, fotograma, imagen anotada y recorte) y flujo de revisión humana.",
        "Administración completa: usuarios y roles, cámaras, editor de zonas sobre la imagen, perfiles de EPP, "
        "cambio de modelo en caliente y auditoría inmutable.",
        "Alertas por webhook firmado y correo, reportes PDF/Excel, métricas Prometheus y trazas OpenTelemetry.",
        "156 tests automáticos, CI local y una instalación limpia verificada siguiendo la guía."])
s.append(Spacer(1, 4))
s.append(T([["Indicador", "Valor medido", "Contexto"],
            ["Precisión del modelo EPP piloto", "mAP50 0,787 · mAP50:95 0,565", "Test de 69 imágenes, misma fuente que el entrenamiento"],
            ["Detección de personas (modelo base)", "AP50 0,961", "200 imágenes de validación"],
            ["Latencia del motor (GTX 1650)", "49 ms (GPU a pleno rendimiento)", "155 ms con la GPU limitada por energía (portátil)"],
            ["Capacidad optimizada", "≈ 6 análisis/s en total", "5 cámaras a 1 fps o 8 a 0,6 fps verificadas"],
            ["Optimización de rendimiento", "+53 % capacidad · −30 % CPU · −50 % RAM", "8 cámaras 1080p, antes vs. después"],
            ["Arranque del vídeo en el navegador", "0,8 – 2,6 s", "Dominado por el siguiente fotograma clave"]],
           [52 * mm, 50 * mm, W - 102 * mm]))

# 2 Características
s.append(PageBreak())
s.append(P("2. Características del sistema", "h1"))
feats = [
    ["Área", "Qué ofrece"],
    ["Captura de vídeo", "Cámaras RTSP/IP, USB (DirectShow / V4L2) y archivos; descubrimiento ONVIF y USB; reconexión con "
                         "backoff exponencial; prueba de conexión; buffer «el último gana» que nunca acumula retraso."],
    ["Detección", "RT-DETRv2 (transformer sin NMS) y RF-DETR; 11 clases canónicas (persona, 5 EPP y sus negativos "
                  "«sin EPP»); motores ONNX Runtime (CUDA, TensorRT, CPU) y OpenVINO; micro-batching entre cámaras."],
    ["Seguimiento", "ByteTrack propio con filtro de Kalman en tiempo continuo (robusto a 1–5 fps) y rescate por distancia."],
    ["Asociación EPP", "Regiones corporales con capacidad (1 casco, 2 guantes…), asignación húngara global y detección de "
                       "asignaciones ambiguas entre personas solapadas."],
    ["Motor de reglas", "Verificabilidad (tamaño, borde, oclusión, confianza), ventana temporal ponderada, histéresis, "
                        "enfriamiento, zonas con perfiles distintos y 5 estados por persona."],
    ["Incidentes", "Registro idempotente, 4 evidencias con sha256, detecciones persistidas, revisión PENDIENTE → "
                   "EN REVISIÓN → CONFIRMADO/DESCARTADO → RESUELTO, comentarios, retención automática."],
    ["Web", "React + TypeScript: panel con KPI, monitoreo multicámara WebRTC con superposición en canvas, incidentes, "
            "administración, editor de polígonos, reportes; diseño adaptable a móvil."],
    ["Alertas y reportes", "Webhook HMAC-SHA256 y correo SMTP con la imagen anotada; cola persistente con reintentos; "
                           "reportes diario/semanal/mensual en pantalla, PDF y Excel."],
    ["Seguridad", "Argon2id, JWT de 15 min + refresh rotatorio en cookie httpOnly, RBAC (4 roles, 14 permisos), "
                  "auditoría de solo inserción (trigger SQL), credenciales cifradas AES-GCM, URLs firmadas, "
                  "vídeo en directo autorizado por la API, protección SSRF."],
    ["Operación", "Métricas Prometheus (tiempos por etapa, CPU por hilo, estado de la GPU), trazas OpenTelemetry, "
                  "<font name='Mono'>svctl doctor</font>, copias de seguridad verificables, despliegue nativo, Docker o systemd."],
    ["Privacidad", "Todo en local; sin reconocimiento facial ni biometría; accesos a vídeo y evidencias auditados."],
]
s.append(T(feats, [32 * mm, W - 32 * mm]))

# 3 Arquitectura
s.append(PageBreak())
s.append(P("3. Arquitectura y flujo de datos", "h1"))
s.append(P("El sistema sigue una <b>arquitectura hexagonal</b> (puertos y adaptadores). El núcleo contiene el dominio "
           "(taxonomía de EPP, geometría, reglas de cumplimiento) y las <b>interfaces</b> que necesita del exterior: "
           "fuente de vídeo, motor de inferencia, modelo de detección, tracker, bus de mensajes, almacenamiento, "
           "envío de alertas o generación de reportes. Cada tecnología concreta es un <b>adaptador</b> intercambiable. "
           "La regla se comprueba automáticamente en el CI con <i>import-linter</i> (6 contratos): el núcleo no puede "
           "importar FastAPI, SQLAlchemy, ONNX Runtime ni ninguna otra tecnología."))
s.append(diagram_hexagon())
s.append(Spacer(1, 6))
s.append(P("<b>Procesos.</b> Tres procesos independientes comparten PostgreSQL: la <b>API</b> (REST, WebSocket en vivo, "
           "web compilada, despacho de alertas y autorización del vídeo), el <b>worker</b> (captura, IA, reglas, "
           "evidencias) y <b>MediaMTX</b> (distribución del vídeo: RTSP para el worker y WebRTC para el navegador). "
           "El vídeo y los metadatos viajan por caminos separados: el navegador recibe el vídeo por WebRTC y las cajas "
           "por WebSocket, y los dibuja alineados en un canvas."))
s.append(diagram_pipeline())
s.append(P("<b>Fiabilidad de eventos.</b> Cada incidente y su evento se escriben en la <b>misma transacción</b> "
           "(patrón <i>outbox</i>); un relé los publica con <font name='Mono'>FOR UPDATE SKIP LOCKED</font> "
           "(al menos una vez, sin duplicados gracias a claves idempotentes). Las alertas externas usan una cola "
           "persistente propia con reintentos (30 s, 2 min, 8 min, 30 min, 2 h)."))

s.append(CondPageBreak(65 * mm))
s.append(P("3.1 Transporte del vídeo por la red", "h2"))
s.append(P("El sistema se diseñó como un servicio de vídeo en red, separando el <b>plano de medios</b> (el flujo de vídeo) "
           "del <b>plano de datos y control</b> (detecciones, estados, eventos y autorización):"))
s += B(["<b>Ingesta:</b> las cámaras IP entregan H.264 por RTSP/RTP. MediaMTX actúa como <i>relay</i>: mantiene "
        "<b>una sola sesión con cada cámara</b> y la reparte al worker y a cada navegador, así que el número de "
        "espectadores no multiplica el tráfico hacia la cámara ni su carga.",
        "<b>Entrega al navegador:</b> WebRTC (WHEP) transporta RTP cifrado (SRTP) sobre UDP con ICE, sin transcodificar. "
        "El arranque medido es de 0,8–2,6 s y lo domina la espera del siguiente fotograma clave, es decir, el intervalo "
        "GOP configurado en la cámara. Se midió <i>trickle ICE</i> y se descartó por ser más lento (1,79 s frente a 1,26 s).",
        "<b>Desacople de tasas:</b> la captura sigue la tasa nativa de la cámara (31 fps medidos con una cámara USB) y el "
        "análisis va a 1–2 fps sobre un búfer de un solo fotograma («el último gana»). La IA nunca frena la recepción "
        "y la red nunca acumula retraso en el análisis. Ante cortes, la reconexión usa <i>backoff</i> exponencial.",
        "<b>Seguridad en la red:</b> cada lectura de vídeo se autoriza con la sesión del usuario y queda auditada; los "
        "servicios escuchan solo en la interfaz local salvo que se publique la LAN de forma explícita, y los protocolos "
        "que no se usan (RTMP, HLS, SRT, MoQ) están desactivados."])

# 4 Modelo matemático
s.append(CondPageBreak(120 * mm))
s.append(P("4. Modelo matemático", "h1"))
s.append(P("La cadena de decisión tiene cinco capas, cada una con su modelo formal. Los valores numéricos son los "
           "<b>parámetros por defecto del código</b>; todos los umbrales del motor de reglas son configurables por perfil."))

s.append(P("4.1 Detección: RT-DETRv2", "h2"))
s.append(P("RT-DETRv2 es un <b>transformer de detección en tiempo real</b>: un backbone convolucional (ResNet-18 con "
           "variante «vd») extrae mapas de características a varias escalas; un codificador híbrido los fusiona y un "
           "decodificador transformer refina <b>Q = 300 consultas</b>. Cada consulta <i>q</i> produce un vector de "
           "puntuaciones por clase y una caja normalizada:"))
s.append(EQ("ŷ<sub>q</sub> = σ(z<sub>q</sub>) ∈ [0,1]<super>C</super>,  b̂<sub>q</sub> = (c<sub>x</sub>, c<sub>y</sub>, w, h) ∈ [0,1]<super>4</super>,  C = 11 clases"))
s.append(P("Al ser un problema de <b>predicción de conjuntos</b>, no necesita supresión de no máximos (NMS). En "
           "inferencia se seleccionan las <i>k</i> = 300 parejas (consulta, clase) de mayor puntuación y se conservan "
           "las que superan el umbral de su clase (0,4 en el modelo EPP):"))
s.append(EQ("D = { (q, c) ∈ top<sub>k</sub>(ŷ) :  ŷ<sub>q,c</sub> ≥ τ<sub>c</sub> },  caja xyxy = (c<sub>x</sub> − w/2, c<sub>y</sub> − h/2, c<sub>x</sub> + w/2, c<sub>y</sub> + h/2)"))
s.append(P("<b>Entrenamiento: emparejamiento húngaro.</b> Para comparar 300 predicciones con <i>N</i> objetos reales se "
           "busca la asignación uno a uno π de coste mínimo (algoritmo húngaro) con el coste de emparejamiento:"))
s.append(EQ("π* = argmin<sub>π</sub> Σ<sub>i</sub> [ λ<sub>cls</sub>·C<sub>cls</sub>(i, π(i)) + λ<sub>L1</sub>·‖b<sub>i</sub> − b̂<sub>π(i)</sub>‖<sub>1</sub> − λ<sub>giou</sub>·GIoU(b<sub>i</sub>, b̂<sub>π(i)</sub>) ],   λ<sub>cls</sub>=2, λ<sub>L1</sub>=5, λ<sub>giou</sub>=2"))
s.append(P("Sobre esa asignación se calcula la pérdida, con <i>Varifocal Loss</i> para la clasificación (pondera cada "
           "positivo por la calidad IoU de su caja, α = 0,75, γ = 2):"))
s.append(EQ("ℒ = 1·ℒ<sub>VFL</sub> + 5·ℒ<sub>L1</sub> + 2·ℒ<sub>GIoU</sub>,    GIoU(A,B) = IoU(A,B) − |E \\ (A ∪ B)| / |E|"))
s.append(P("donde <i>E</i> es la menor caja que contiene a <i>A</i> y <i>B</i>. La pérdida se aplica a la salida de cada "
           "capa del decodificador (supervisión profunda) y, en RT-DETRv2, a las consultas de «desruido»."))

s.append(P("4.2 Métricas de evaluación", "h2"))
s.append(EQ("IoU(A,B) = |A ∩ B| / |A ∪ B|,      P = TP / (TP + FP),      R = TP / (TP + FN)"))
s.append(P("Una detección es verdadero positivo si su IoU con una caja real de la misma clase supera el umbral y esa "
           "caja no estaba ya emparejada. La <b>precisión media</b> es el área bajo la curva precisión-recall "
           "(interpolada en 101 puntos, criterio COCO, implementación propia con tests):"))
s.append(EQ("AP<sub>c</sub> = (1/101) Σ<sub>r ∈ {0, 0.01, …, 1}</sub> max<sub>r' ≥ r</sub> P(r')"))
s.append(EQ("mAP50 = media<sub>c</sub> AP<sub>c</sub>(IoU ≥ 0.5),     mAP50:95 = media sobre IoU ∈ {0.50, 0.55, …, 0.95}"))

s.append(CondPageBreak(60 * mm))
s.append(P("4.3 Seguimiento: filtro de Kalman y ByteTrack", "h2"))
s.append(P("Cada persona es un <b>track</b> con estado x = (c<sub>x</sub>, c<sub>y</sub>, a, h, v<sub>x</sub>, v<sub>y</sub>, v<sub>a</sub>, v<sub>h</sub>) "
           "(centro, relación de aspecto, alto y sus velocidades) y modelo de <b>velocidad constante</b>. Como el "
           "análisis va a 1–5 fps y no a 30, la predicción usa el tiempo real transcurrido Δt expresado en "
           "«fotogramas de referencia» s = 30·Δt; así los parámetros originales siguen siendo válidos:"))
s.append(EQ("x̂<sub>t|t−1</sub> = F<sub>s</sub> x<sub>t−1</sub>,   F<sub>s</sub> = [ I<sub>4</sub>  s·I<sub>4</sub> ; 0  I<sub>4</sub> ],   P<sub>t|t−1</sub> = F<sub>s</sub> P F<sub>s</sub><super>T</super> + s·Q(h)"))
s.append(EQ("K = P H<super>T</super>(H P H<super>T</super> + R)<super>−1</super>,   x<sub>t</sub> = x̂ + K(z − H x̂),   P<sub>t</sub> = (I − K H) P"))
s.append(P("El ruido es proporcional a la altura <i>h</i> (σ<sub>pos</sub> = h/20, σ<sub>vel</sub> = h/160): una persona "
           "lejana y pequeña tiene menos incertidumbre absoluta. <b>ByteTrack</b> asocia en dos rondas: primero las "
           "detecciones de alta confianza (≥ 0,5) con coste 1 − IoU·score y IoU ≥ 0,2; después, las de baja confianza "
           "(0,1–0,5) con IoU ≥ 0,5, recuperando personas parcialmente ocultas. Ambas rondas usan el algoritmo húngaro. "
           "Añadí un <b>rescate por distancia</b> (centros a menos de una altura de persona y tamaño compatible ×1,5) "
           "porque a baja frecuencia una persona puede moverse tanto que su IoU sea 0. Un track se confirma con 2 "
           "apariciones y se elimina tras 3 s sin verse."))

s.append(P("4.4 Asociación EPP → persona", "h2"))
s.append(P("Cada clase de EPP pertenece a una <b>región corporal</b> relativa a la caja de la persona (por ejemplo, "
           "cabeza = [−0,15·w, −0,15·h] a [1,15·w, 0,35·h]) con una <b>capacidad</b> (cabeza 1, manos 2, pies 2). "
           "La plausibilidad de que el objeto <i>i</i> pertenezca a la persona <i>j</i> es:"))
s.append(EQ("s<sub>ij</sub> = 0.6 · |b<sub>i</sub> ∩ R<sub>j</sub>| / |b<sub>i</sub>|  +  0.4 · (1 − min(1, |c<sub>x,i</sub> − eje<sub>j</sub>| / w<sub>j</sub>))"))
s.append(P("con s<sub>ij</sub> = 0 si el centro del objeto cae fuera de la región, si el solape es menor que el mínimo "
           "(0,5; 0,6 en el torso) o si el objeto es más de 1,6 veces más ancho que la persona. Cada persona se "
           "<b>replica tantas veces como su capacidad</b> y se resuelve un único problema de asignación global:"))
s.append(EQ("min<sub>π</sub> Σ<sub>i</sub> c<sub>i,π(i)</sub>,   c<sub>ij</sub> = 1 − s<sub>ij</sub> si s<sub>ij</sub> &gt; 0, ∞ en otro caso"))
s.append(P("Así dos personas solapadas no se «roban» ni duplican un casco. Si otra persona tenía una plausibilidad "
           "casi igual (margen &lt; 0,15), la asignación se marca <b>ambigua</b> y el motor de reglas no la usa como prueba."))

s.append(CondPageBreak(70 * mm))
s.append(P("4.5 Motor de reglas", "h2"))
s.append(P("<b>(a) Verificabilidad primero.</b> Antes de mirar ninguna detección, cada EPP de cada persona se clasifica "
           "como <b>no verificable</b> si: la persona mide menos de 80 px de alto, su confianza es &lt; 0,4, la región "
           "corporal mide &lt; 12 px, la región está cortada por el borde de la imagen, o la tapa otra persona más cercana "
           "a la cámara (IoA ≥ 0,35). Esta regla se adelantó tras encontrar en pruebas reales un falso incidente sobre "
           "una figura de 35 px."))
s.append(P("<b>(b) Observación por fotograma</b> o<sub>t</sub> <font name='Math'>∈</font> {presente, ausente explícito («no_*»), ausente "
           "implícito (no se ve), no verificable}. <b>(c) Ventana deslizante</b> de 6 s con pesos: una ausencia "
           "implícita pesa w<sub>imp</sub> = 0,5 frente a 1 de una explícita (0,25 en manos, que pueden quedar fuera "
           "del encuadre):"))
s.append(EQ("A = n<sub>expl</sub> + w<sub>imp</sub>·n<sub>impl</sub>,   p<sub>pres</sub> = n<sub>pres</sub> / (n<sub>pres</sub> + A),   p<sub>aus</sub> = A / (n<sub>pres</sub> + A)"))
s.append(T([["Condición en la ventana", "Estado del EPP"],
            ["n<sub>verif</sub> &lt; 4  o  n<sub>verif</sub> / n &lt; 0,5", "NO VERIFICABLE"],
            ["p<sub>pres</sub> ≥ 0,6", "DETECTADO"],
            ["p<sub>aus</sub> ≥ 0,7", "AUSENTE (posible incumplimiento)"],
            ["en otro caso", "INCIERTO (en revisión)"]], [W * 0.55, W * 0.45]))
s.append(Spacer(1, 4))
s.append(P("<b>(d) Confirmación con histéresis.</b> Un incumplimiento solo se <b>confirma</b> si el EPP lleva AUSENTE "
           "al menos 5 s seguidos, hay ≥ 4 ausencias verificables y <b>al menos 2 detecciones explícitas «no_*»</b> en "
           "la ventana (nunca con un solo fotograma ni solo por «no verlo»). Se cierra cuando el EPP vuelve a verse de "
           "forma sostenida durante 4 s, y no se re-confirma para la misma persona y EPP antes de 60 s. La confianza "
           "del incidente es p<sub>aus</sub>. <b>(e) Zonas:</b> la persona está en una zona si su <i>punto de apoyo</i> "
           "(centro del borde inferior de la caja) cae en el polígono; con varias zonas se exige la unión de sus EPP."))
s.append(diagram_states())

s.append(P("4.6 Indicadores y modelo de capacidad", "h2"))
s.append(P("El <b>cumplimiento</b> se calcula sobre fotogramas-persona evaluables; lo no verificable y lo que está en "
           "revisión no cuenta ni a favor ni en contra, y su proporción se informa aparte:"))
s.append(EQ("Cumplimiento = conformes / (conformes + posibles + confirmados)"))
s.append(P("<b>Capacidad.</b> Con un modelo compartido y micro-batching voraz, la capacidad total es aproximadamente "
           "el número de imágenes que la GPU procesa por segundo con el tamaño de lote medio <i>B</i>; el sistema "
           "cumple mientras la demanda no la supere:"))
s.append(EQ("C ≈ B / t<sub>inf</sub>(B),      Σ<sub>cámaras</sub> fps<sub>análisis</sub> ≤ C"))
s.append(P("Medido en una GTX 1650 de portátil limitada por energía: t<sub>inf</sub>(1) = 155 ms y t<sub>inf</sub>(4)/4 = "
           "140 ms, con una capacidad observada de ≈ 5,5–6 análisis/s. Cuando la demanda supera C, la cola crece "
           "(métrica <font name='Mono'>detect_wait</font>), por eso la frecuencia de análisis por cámara es configurable."))

# 5 Tecnologías
s.append(CondPageBreak(110 * mm))
s.append(P("5. Tecnologías utilizadas", "h1"))
tech = [["Capa", "Tecnología", "Por qué"],
        ["Lenguaje y entorno", "Python 3.12 · uv (lockfile reproducible) · TypeScript", "Ecosistema de IA + tipado en la web"],
        ["API", "FastAPI · Pydantic v2 · Uvicorn · WebSocket", "Asíncrona, validación estricta, OpenAPI automático"],
        ["Datos", "PostgreSQL 17 · SQLAlchemy 2 (async) · Alembic · asyncpg", "Transacciones, LISTEN/NOTIFY, migraciones versionadas"],
        ["Vídeo", "PyAV (FFmpeg) · MediaMTX · WebRTC (WHEP)", "Decodificación eficiente y vídeo de baja latencia al navegador"],
        ["IA: inferencia", "ONNX Runtime GPU (CUDA, TensorRT, CPU) · OpenVINO", "Mismo modelo en NVIDIA, Intel CPU/GPU, intercambiable"],
        ["IA: modelos", "RT-DETRv2-r18 (Hugging Face) · RF-DETR Nano", "Detectores transformer sin NMS, licencia Apache-2.0"],
        ["IA: entrenamiento", "PyTorch 2 · Transformers · AMP · ONNX (opset 17)", "Ajuste fino en GPU de 4 GB y exportación verificada"],
        ["Algoritmos", "NumPy · SciPy (algoritmo húngaro) · ByteTrack propio · Kalman", "Control total y tests sobre secuencias anotadas"],
        ["Web", "React 19 · Vite · Tailwind CSS · TanStack Query · ECharts", "SPA rápida, datos en vivo, gráficas"],
        ["Seguridad", "Argon2id · PyJWT · cryptography (AES-GCM) · HMAC", "Prácticas actuales de contraseñas, tokens y cifrado"],
        ["Reportes y alertas", "ReportLab · openpyxl · httpx · SMTP", "PDF/Excel nativos, webhooks firmados"],
        ["Observabilidad", "Prometheus · OpenTelemetry · NVML · Grafana", "Métricas por etapa, trazas, estado de la GPU"],
        ["Calidad", "pytest · ruff · import-linter · vitest · tsc", "156 + 7 tests, reglas de arquitectura en CI"],
        ["Despliegue", "Docker Compose · systemd · Caddy (HTTPS)", "Nativo Windows, contenedores o Linux con GPU"],
        ["Datos de entrenamiento", "Ultralytics Construction-PPE (CC BY 4.0) · CVAT", "Fuente con licencia verificada y herramienta de anotación"]]
s.append(T(tech, [30 * mm, 72 * mm, W - 102 * mm]))
s.append(Spacer(1, 6))
s.append(P("Todas las dependencias tienen licencia verificada automáticamente (inventario generado en el CI). Se evitaron "
           "deliberadamente componentes con licencias restrictivas para un producto: Redis ≥ 7.4 (RSAL/SSPL), "
           "codificadores GPL (x264) y modelos YOLO con licencia AGPL.", "small"))

# 6 Repositorio
s.append(CondPageBreak(120 * mm))
s.append(P("6. Repositorio y fuentes externas", "h1"))
s.append(P("El código vive en un único repositorio Git (monorepo), organizado por capas de la arquitectura:"))
s.append(CODE("""security-vision/
├── src/security_vision/
│   ├── core/            dominio, puertos, eventos, configuración (sin frameworks)
│   ├── modules/         casos de uso: cámaras, reglas, incidentes, alertas, reportes
│   ├── infrastructure/  adaptadores: PostgreSQL, MediaMTX, almacenamiento, seguridad
│   └── plugins/         vídeo (PyAV), inferencia (ONNX Runtime, OpenVINO), modelos, ByteTrack
├── src/security_vision_ml/   auditoría y normalización de datasets (CLI svds)
├── apps/api/                 API FastAPI y svctl (migrate, bootstrap, doctor, purge)
├── apps/processing-worker/   worker de captura e IA
├── apps/web/                 frontend React + TypeScript
├── ml/model_registry/        modelos registrados (model.yaml: sha256, licencias, métricas)
├── ml/training|export|evaluation/   entrenamiento, exportación ONNX, benchmarks
├── scripts/                  CI local, PostgreSQL/MediaMTX locales, copias, carga
├── docker/, deploy/          Docker Compose, systemd, proxy HTTPS
└── docs/                     arquitectura, 34 ADR, instalación, operación, informes"""))
s.append(T([["Fuente externa", "Uso", "Licencia"],
            ["Hugging Face · PekingU/rtdetr_v2_r18vd (commit fijado)", "Pesos base del detector", "Apache-2.0"],
            ["github.com/lyuwenyu/RT-DETR", "Arquitectura de referencia (artículo RT-DETRv2)", "Apache-2.0"],
            ["github.com/roboflow/rf-detr", "Detector alternativo (variante Nano)", "Apache-2.0"],
            ["github.com/ifzhang/ByteTrack", "Algoritmo de referencia (implementación propia)", "MIT"],
            ["github.com/bluenviron/mediamtx", "Servidor de vídeo RTSP/WebRTC", "MIT"],
            ["Ultralytics Construction-PPE", "Dataset de entrenamiento del piloto", "CC BY 4.0 (atribución)"],
            ["github.com/microsoft/onnxruntime · openvinotoolkit", "Motores de inferencia", "MIT · Apache-2.0"]],
           [70 * mm, 62 * mm, W - 132 * mm]))

# 7 Escalabilidad
s.append(CondPageBreak(110 * mm))
s.append(P("7. Escalabilidad", "h1"))
s.append(P("La escalabilidad está diseñada en tres planos: <b>técnico</b> (más cámaras y más carga), <b>tecnológico</b> "
           "(cambiar piezas sin reescribir) y <b>funcional</b> (nuevos EPP, reglas o canales)."))
s.append(P("7.1 Puertos y adaptadores: cambiar piezas sin tocar el núcleo", "h2"))
s += B(["Cada tecnología se registra en un <b>ProviderRegistry</b> y puede añadirse como <b>plugin</b> por "
        "<i>entry points</i> de Python (<font name='Mono'>security_vision.video_sources</font>, motores, modelos, trackers) "
        "sin modificar el código existente.",
        "El bus de eventos es un puerto (<font name='Mono'>MessageBus</font>): hoy PostgreSQL LISTEN/NOTIFY; para "
        "muchos nodos, un adaptador de Valkey Streams o NATS.",
        "El almacenamiento de evidencias es un puerto (<font name='Mono'>ObjectStorage</font>): hoy disco local con URLs "
        "firmadas; mañana S3 compatible (SeaweedFS) sin cambiar los casos de uso.",
        "La taxonomía de clases es canónica: un modelo nuevo solo declara en su <font name='Mono'>model.yaml</font> cómo "
        "se mapean sus etiquetas, y el resto del sistema no cambia."])
s.append(P("7.2 Escalado de carga", "h2"))
s += B(["<b>Vertical, medido:</b> micro-batching entre cámaras, preproceso en paralelo, conversión de color perezosa y "
        "decodificador de un hilo: +53 % de capacidad, −30 % de CPU y −50 % de memoria con 8 cámaras.",
        "<b>Horizontal:</b> la API no guarda estado (JWT + PostgreSQL), así que admite varias réplicas detrás de un "
        "balanceador; los procesos de fondo se reparten trabajo con <font name='Mono'>SKIP LOCKED</font> y "
        "concesiones temporales, por lo que pueden convivir varias instancias sin duplicar alertas.",
        "<b>Por nodos de cámaras:</b> el worker es independiente por diseño; la siguiente etapa es asignar grupos de "
        "cámaras a varios workers (tabla de nodos + concesión), sin cambiar interfaces.",
        "<b>Por hardware:</b> el mismo modelo ONNX corre en CPU, GPU NVIDIA (CUDA/TensorRT) o Intel (OpenVINO): se "
        "elige por configuración según el equipo disponible."])
s.append(chart_load())
s.append(P("7.3 Escalado funcional", "h2"))
s += B(["Nuevos EPP: añadir la clase y su negativo a la taxonomía, su región corporal y su regla; el motor es genérico.",
        "Nuevos canales de alerta: implementar <font name='Mono'>AlertSender</font> (por ejemplo Telegram o Teams).",
        "Nuevas reglas por sitio: perfiles versionados con 19 umbrales y zonas dibujadas sobre la imagen."])

# 8 QoS
s.append(CondPageBreak(110 * mm))
s.append(P("8. Dónde cambiar librerías y procesadores para mejorar la calidad de servicio", "h1"))
s.append(P("Todo se cambia por <b>configuración</b> (variables <font name='Mono'>SV_*</font> en <font name='Mono'>.env</font>), "
           "desde la <b>interfaz web</b> o con un <b>plugin</b>; ninguno de estos cambios requiere modificar el núcleo."))
qos = [["Qué mejorar", "Dónde se cambia", "Efecto"],
       ["Procesador de inferencia", "<font name='Mono'>SV_INFERENCE_DEVICES=[\"tensorrt\",\"cuda\",\"cpu\"]</font>", "Orden de preferencia con respaldo explícito (nunca finge usar la GPU)"],
       ["Motor de inferencia", "<font name='Mono'>SV_INFERENCE_ENGINE=onnxruntime | openvino</font>", "NVIDIA → ONNX Runtime; Intel CPU/iGPU → OpenVINO"],
       ["Modelo (precisión vs. velocidad)", "Web › Modelos › Activar (o <font name='Mono'>SV_DETECTION_MODEL</font>)", "Cambio en caliente en ≈ 2 s sin parar cámaras"],
       ["Rendimiento con muchas cámaras", "<font name='Mono'>SV_DETECTION_MAX_BATCH</font>, <font name='Mono'>SV_DETECTION_MAX_WAIT_MS</font>", "Lotes más grandes = más imágenes/s"],
       ["Arranque y ancho de banda del vídeo", "Configuración de la cámara: intervalo GOP, bitrate, subflujo (URL RTSP)", "GOP corto = arranque más rápido; un subflujo de menor resolución reduce red y decodificación"],
       ["Carga por cámara", "Web › Cámaras › «Análisis (fotogramas/s)»", "Menos fps = más cámaras por GPU (0,6–1 fps suele bastar)"],
       ["Decodificación de vídeo", "Opción <font name='Mono'>decode_threads</font> de la cámara; <font name='Mono'>SV_VIDEO_PROVIDER</font>", "1 hilo (eficiente) o automático para 4K; otro adaptador de captura"],
       ["Falsos positivos / sensibilidad", "Web › Perfiles EPP (19 umbrales)", "Tiempo de confirmación, «no_*» mínimos, tamaño mínimo de persona…"],
       ["Precisión por clase", "<font name='Mono'>class_thresholds</font> en <font name='Mono'>model.yaml</font>", "Umbral distinto para cada clase"],
       ["Seguimiento", "<font name='Mono'>SV_TRACKER</font>, <font name='Mono'>SV_TRACKER_MAX_LOST_SECONDS</font>", "Otro tracker por plugin; tolerancia a oclusiones"],
       ["Retención y disco", "<font name='Mono'>SV_RETENTION_EVIDENCES_DAYS</font>", "Equilibrio entre trazabilidad y espacio"],
       ["Energía de la GPU (portátiles)", "Windows «Máximo rendimiento» + panel NVIDIA", "155 → ≈ 49 ms por inferencia (medido)"],
       ["Diagnóstico", "Métricas <font name='Mono'>sv_stage_ms</font>, <font name='Mono'>sv_gpu_pstate</font>; <font name='Mono'>svctl doctor</font>", "Saber qué etapa limita antes de cambiar nada"]]
s.append(T(qos, [38 * mm, 70 * mm, W - 108 * mm]))
s.append(Spacer(1, 6))
s.append(P("<b>Ejemplo de decisión basada en datos.</b> En la Fase 9 la GPU estaba solo al 60 % con 8 cámaras. El desglose "
           "por etapas mostró que el preproceso (CPU) se hacía dentro del turno de la GPU; moverlo fuera y agrupar "
           "inferencias subió la GPU al 82 % y la capacidad un 53 %. También se probaron y <b>descartaron con datos</b> "
           "dos ideas: convertir el modelo a FP16 (230 ms frente a 155 ms en esta GPU sin Tensor Cores) y <i>trickle ICE</i> "
           "en WebRTC (mediana 1,79 s frente a 1,26 s)."))

# 9 Entrenamiento
s.append(CondPageBreak(110 * mm))
s.append(P("9. Cómo se entrenan los modelos", "h1"))
s.append(P("El entrenamiento sigue un proceso auditable de seis pasos. El principio rector es no inventar resultados: "
           "cada dataset tiene su licencia verificada, cada partición está libre de fugas y cada modelo exportado se "
           "compara numéricamente con el original."))
steps = [["Paso", "Qué se hace", "Herramienta"],
         ["1. Fuentes y licencias", "Registro de cada dataset con su licencia verificada en la fuente; solo se descargan los autorizados; originales inmutables con sha256", "<font name='Mono'>svds sources / acquire</font>"],
         ["2. Normalización", "Mapeo de las etiquetas de cada fuente a 11 clases canónicas; «bota de trabajo visible» no se equipara a calzado de seguridad", "<font name='Mono'>svds audit</font>"],
         ["3. Auditoría de calidad", "Revisión visual de muestras por clase; cajas inválidas; duplicados por pHash; correcciones en CVAT", "<font name='Mono'>svds review-export</font> · CVAT"],
         ["4. Partición sin fugas", "train/val/test agrupando imágenes casi idénticas (pHash) para que nunca caigan en particiones distintas", "<font name='Mono'>svds split</font>"],
         ["5. Entrenamiento", "Ajuste fino de RT-DETRv2-r18 preentrenado en COCO", "<font name='Mono'>ml/training/train_rtdetr.py</font>"],
         ["6. Exportación y registro", "ONNX opset 17; verificación de detecciones ONNX vs. PyTorch; <font name='Mono'>model.yaml</font> con sha256, licencias y métricas medidas", "<font name='Mono'>ml/export/export_rtdetr_hf.py</font>"]]
s.append(T(steps, [32 * mm, W - 32 * mm - 56 * mm, 56 * mm]))
s.append(P("Configuración del entrenamiento del piloto", "h2"))
s += B(["<b>Hardware:</b> GTX 1650 de 4 GB → precisión mixta (AMP) y lote 4 con acumulación de gradiente ×2 (lote efectivo 8).",
        "<b>Optimizador:</b> AdamW (weight decay 10<super>−4</super>) con tasas distintas: 10<super>−5</super> para el backbone "
        "preentrenado y 10<super>−4</super> para el resto; programa OneCycle con 10 % de calentamiento.",
        "<b>Aumentos:</b> volteo horizontal (no cambia la semántica del EPP) y variación fotométrica suave de brillo y contraste.",
        "<b>Robustez del proceso:</b> punto de control completo por época (modelo, optimizador, programador) con reanudación "
        "exacta, y una <b>protección térmica</b> que pausa el entrenamiento si la GPU supera 87 °C (añadida tras un "
        "apagado por temperatura en mitad del entrenamiento).",
        "<b>Selección:</b> la mejor época por mAP de validación; el conjunto de test se evalúa <b>una sola vez</b>."])
s.append(CODE(r"""# reproducir el proceso (comandos reales del repositorio)
uv sync --extra train
# 1) partición sin fugas y exportación al formato de entrenamiento
uv run svds split --name ppe_v1 --sources ultralytics_construction_ppe
uv run svds export --split ppe_v1
# 2) ajuste fino (--resume para reanudar desde el último punto de control)
uv run python ml/training/train_rtdetr.py --data <split exportado> \
    --out ml/training/runs/ppe-v1 --epochs 30 --batch 4 --accum 2 \
    --lr 1e-4 --lr-backbone 1e-5
# 3) exportación ONNX verificada contra PyTorch y registro
uv run python ml/export/export_rtdetr_hf.py --repo <mejor época> \
    --name rtdetr-v2-r18-ppe --version 2 --class-map-identity --verify-images <imágenes>
# 4) evaluación única en test
uv run python ml/evaluation/benchmark_inference.py --model rtdetr-v2-r18-ppe@2 \
    --eval-split test"""))
s.append(chart_ap())
s.append(P("<b>Datos:</b> 547 / 69 / 69 imágenes (train/val/test), 0 fugas. <b>Resultado en test:</b> mAP50 0,787, "
           "mAP50:95 0,565. <b>Exportación:</b> diferencia máxima ONNX vs. PyTorch de 3,7·10<super>−5</super> sobre 67 "
           "detecciones. Las clases «sin EPP» son más difíciles (AP50 0,43–0,79): por eso el motor de reglas las usa "
           "como evidencia acumulada en el tiempo y nunca como prueba única."))

# 10 Calidad
s.append(CondPageBreak(110 * mm))
s.append(P("10. Calidad, seguridad y resultados medidos", "h1"))
s.append(P("El proyecto se construyó en 10 fases; cada una terminó con tests, pruebas reales con servicios reales "
           "(base de datos, servidor de vídeo, modelo en GPU, navegador) y un informe con lo que funcionó y lo que no."))
s.append(T([["Práctica", "Detalle"],
            ["Tests", "156 tests Python (unitarios + integración contra PostgreSQL real) y 7 de la web; instalación limpia verificada con 155/155"],
            ["CI local", "ruff, import-linter (6 contratos de arquitectura), alembic check, licencias, documentación de API al día, tsc, vitest"],
            ["Decisiones", "34 ADR (registros de decisiones de arquitectura) con contexto, decisión y consecuencias"],
            ["Errores encontrados por pruebas reales", "Falso incidente por persona diminuta, sesión revocada con dos pestañas, compose inválido, dependencia no declarada, descubrimiento USB roto… todos corregidos con test de regresión"],
            ["Seguridad", "Auditoría inmutable, RBAC, rotación de tokens con detección de reutilización, SSRF, HMAC, AES-GCM, vídeo autorizado, métricas restringidas"],
            ["Privacidad", "Procesamiento local, sin biometría, accesos a vídeo y evidencias auditados"]],
           [44 * mm, W - 44 * mm]))
s.append(Spacer(1, 6))
s.append(T([["Prueba de carga (cámaras H.264 1080p)", "Análisis/s", "Latencia p95", "Resultado"],
            ["2 cámaras × 2 fps", "3,98", "0,32 s", "cumple"],
            ["5 cámaras × 1 fps", "4,99", "0,83 s", "cumple"],
            ["8 cámaras × 0,6 fps", "4,80", "1,08 s", "cumple"],
            ["8 cámaras × 2 fps", "5,86", "1,66 s", "saturado (0,73 fps por cámara)"]],
           [62 * mm, 28 * mm, 30 * mm, W - 120 * mm]))

# 11 Limitaciones
s.append(CondPageBreak(70 * mm))
s.append(P("11. Limitaciones y próximos pasos", "h1"))
s.append(P("Un buen sistema de IA se presenta con sus límites. Estos son los del estado actual:"))
s += B(["<b>Validación en el sitio real:</b> el modelo piloto se evaluó con imágenes de la misma fuente que el "
        "entrenamiento (construcción, parte sintéticas). Con cámaras reales la precisión será previsiblemente menor; "
        "el siguiente paso es un conjunto de evaluación propio y reentrenar con imágenes del despliegue.",
        "<b>Clases:</b> «sin botas» no tiene ejemplos de entrenamiento todavía (corrección de datos pendiente en CVAT).",
        "<b>Hardware:</b> las cifras de capacidad son de una GPU de portátil limitada por energía; TensorRT está "
        "soportado pero sin medir.",
        "<b>Despliegue:</b> Docker y Linux están escritos y validados de forma estática, pero no ejecutados en el equipo "
        "de desarrollo (sin virtualización)."])
s.append(Spacer(1, 6))
s.append(P("Aspectos destacados", "h2"))
s += B(["Diseño de sistemas de visión por computador de extremo a extremo, desde los datos hasta la interfaz.",
        "Modelado matemático aplicado: detección por conjuntos, filtrado de Kalman, asignación óptima y lógica temporal robusta.",
        "Transporte de vídeo en tiempo real por la red: RTSP/RTP, WebRTC, latencia y desacople entre red y procesamiento.",
        "Desarrollo con prácticas profesionales: arquitectura hexagonal verificada, tests, CI, ADR, seguridad y observabilidad.",
        "Optimización guiada por medición y honestidad técnica: cada cifra es medida y cada límite está documentado."])

doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm,
                        bottomMargin=16 * mm, title="Security Vision — documento técnico",
                        author="Ricardo César Villalobos Pérez", subject="Plataforma de videovigilancia con IA para EPP")
doc.build(s, onFirstPage=cover, onLaterPages=later)
print(OUT, OUT.stat().st_size // 1024, "KB")
