from __future__ import annotations

from pathlib import Path
from textwrap import shorten

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject, TextStringObject
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "Elara_Portfolio_Case_Study.pdf"
TEMP_OUTPUT = ROOT / ".Elara_Portfolio_Case_Study.build.pdf"
SCREENSHOTS = ROOT / "screenshots"
DIAGRAMS = ROOT / "diagrams"

PAGE_W = 960
PAGE_H = 540
MARGIN = 52

INK = HexColor("#10251F")
FOREST = HexColor("#1F5B50")
TEAL = HexColor("#4F8C84")
MINT = HexColor("#DDEFE7")
PALE_MINT = HexColor("#EEF7F2")
GOLD = HexColor("#D7B500")
PALE_GOLD = HexColor("#F5EDB8")
RUST = HexColor("#B85F43")
PALE_RUST = HexColor("#F5DED5")
CREAM = HexColor("#F7F4EC")
PAPER = HexColor("#FFFDF8")
MUTED = HexColor("#60716B")
LINE = HexColor("#D5D6CE")
SLATE = HexColor("#2D423B")


def register_fonts() -> None:
    font_dir = Path("C:/Windows/Fonts")
    pdfmetrics.registerFont(TTFont("ElaraBody", str(font_dir / "arial.ttf")))
    pdfmetrics.registerFont(TTFont("ElaraBodyBold", str(font_dir / "arialbd.ttf")))
    pdfmetrics.registerFont(TTFont("ElaraBodyItalic", str(font_dir / "ariali.ttf")))
    pdfmetrics.registerFont(TTFont("ElaraDisplay", str(font_dir / "georgia.ttf")))
    pdfmetrics.registerFont(TTFont("ElaraDisplayBold", str(font_dir / "georgiab.ttf")))


def mix(color: Color, amount: float = 0.15) -> Color:
    return Color(
        color.red + (1 - color.red) * amount,
        color.green + (1 - color.green) * amount,
        color.blue + (1 - color.blue) * amount,
    )


def wrap_lines(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_text(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "ElaraBody",
    size: float = 10,
    leading: float | None = None,
    color: Color = INK,
    max_lines: int | None = None,
) -> float:
    leading = leading or size * 1.35
    lines = wrap_lines(text, font, size, width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = shorten(lines[-1], width=max(8, len(lines[-1]) - 1), placeholder="...")
    c.setFont(font, size)
    c.setFillColor(color)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_bullets(
    c: canvas.Canvas,
    items: list[str],
    x: float,
    y: float,
    width: float,
    *,
    size: float = 9.5,
    leading: float = 13,
    bullet_color: Color = TEAL,
    text_color: Color = INK,
    gap: float = 5,
) -> float:
    for item in items:
        c.setFillColor(bullet_color)
        c.circle(x + 4, y + 3, 2.2, stroke=0, fill=1)
        lines = wrap_lines(item, "ElaraBody", size, width - 18)
        c.setFillColor(text_color)
        c.setFont("ElaraBody", size)
        for line in lines:
            c.drawString(x + 16, y, line)
            y -= leading
        y -= gap
    return y


def rounded_card(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: Color = PAPER,
    stroke: Color = LINE,
    radius: float = 12,
    shadow: bool = True,
) -> None:
    if shadow:
        c.setFillColor(Color(0, 0, 0, alpha=0.07))
        c.roundRect(x + 3, y - 3, w, h, radius, stroke=0, fill=1)
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.8)
    c.roundRect(x, y, w, h, radius, stroke=1, fill=1)


def pill(c: canvas.Canvas, text: str, x: float, y: float, *, fill: Color = MINT, color: Color = FOREST) -> float:
    size = 8.2
    w = pdfmetrics.stringWidth(text.upper(), "ElaraBodyBold", size) + 22
    c.setFillColor(fill)
    c.roundRect(x, y, w, 21, 10.5, stroke=0, fill=1)
    c.setFillColor(color)
    c.setFont("ElaraBodyBold", size)
    c.drawString(x + 11, y + 6.6, text.upper())
    return w


def section_header(c: canvas.Canvas, title: str, kicker: str, page_num: int, *, dark: bool = False) -> None:
    bg = INK if dark else CREAM
    fg = white if dark else INK
    c.setFillColor(bg)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(mix(TEAL, 0.25) if dark else FOREST)
    c.setFont("ElaraBodyBold", 8)
    c.drawString(MARGIN, PAGE_H - 28, f"ELARA.AI  /  {kicker.upper()}")
    c.setStrokeColor(Color(1, 1, 1, alpha=0.18) if dark else LINE)
    c.line(MARGIN, PAGE_H - 37, PAGE_W - MARGIN, PAGE_H - 37)
    c.setFillColor(fg)
    c.setFont("ElaraDisplayBold", 29)
    c.drawString(MARGIN, PAGE_H - 82, title)
    c.setFillColor(GOLD)
    c.roundRect(MARGIN, PAGE_H - 98, 96, 4, 2, stroke=0, fill=1)
    c.setFillColor(Color(1, 1, 1, alpha=0.55) if dark else MUTED)
    c.setFont("ElaraBody", 8)
    c.drawRightString(PAGE_W - MARGIN, 20, f"{page_num:02d}")
    c.bookmarkPage(f"page-{page_num}")
    c.addOutlineEntry(title, f"page-{page_num}", level=0, closed=False)


def image_fit(c: canvas.Canvas, path: Path, x: float, y: float, w: float, h: float, *, pad: float = 0) -> None:
    rounded_card(c, x, y, w, h, fill=PAPER, stroke=LINE, radius=12, shadow=True)
    ix, iy, iw, ih = x + pad, y + pad, w - 2 * pad, h - 2 * pad
    with Image.open(path) as image:
        src_w, src_h = image.size
    scale = min(iw / src_w, ih / src_h)
    draw_w, draw_h = src_w * scale, src_h * scale
    c.drawImage(
        ImageReader(str(path)),
        ix + (iw - draw_w) / 2,
        iy + (ih - draw_h) / 2,
        width=draw_w,
        height=draw_h,
        preserveAspectRatio=True,
        mask="auto",
    )


def metric(c: canvas.Canvas, x: float, y: float, w: float, value: str, label: str, *, accent: Color = FOREST) -> None:
    rounded_card(c, x, y, w, 72, fill=PAPER, stroke=LINE, radius=10, shadow=False)
    c.setFillColor(accent)
    c.setFont("ElaraDisplayBold", 22)
    c.drawString(x + 15, y + 35, value)
    draw_text(c, label, x + 15, y + 22, w - 30, font="ElaraBody", size=7.8, leading=9.5, color=MUTED, max_lines=2)


def label_value(c: canvas.Canvas, x: float, y: float, label: str, value: str, width: float) -> float:
    c.setFillColor(GOLD)
    c.setFont("ElaraBodyBold", 7.5)
    c.drawString(x, y, label.upper())
    return draw_text(c, value, x, y - 16, width, font="ElaraBodyBold", size=10, leading=13, color=white)


def page_cover(c: canvas.Canvas) -> None:
    c.setFillColor(INK)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(TEAL)
    c.rect(0, 0, 16, PAGE_H, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.circle(68, PAGE_H - 66, 7, stroke=0, fill=1)
    pill(c, "Portfolio case study / August 2026", 52, PAGE_H - 122, fill=Color(1, 1, 1, alpha=0.09), color=GOLD)
    c.setFillColor(white)
    c.setFont("ElaraDisplayBold", 52)
    c.drawString(52, PAGE_H - 196, "Elara.ai")
    draw_text(
        c,
        "Evidence-first automated verification with reproducible citations, deterministic scoring, and auditable AI workflows.",
        52,
        PAGE_H - 235,
        465,
        font="ElaraBody",
        size=17,
        leading=23,
        color=mix(TEAL, 0.55),
    )
    pill(c, "Agentic hybrid RAG", 568, 396, fill=Color(1, 1, 1, alpha=0.09), color=GOLD)
    stages = [
        ("01", "Web discovery", "Brave search + controlled retrieval"),
        ("02", "Hybrid passage retrieval", "Lexical + vector + metadata + provenance"),
        ("03", "Evidence-grounded generation", "Approved passages + deterministic scores"),
    ]
    y_stage = 324
    for number, title, body in stages:
        rounded_card(
            c,
            568,
            y_stage,
            340,
            58,
            fill=Color(1, 1, 1, alpha=0.055),
            stroke=Color(1, 1, 1, alpha=0.15),
            radius=12,
            shadow=False,
        )
        c.setFillColor(GOLD)
        c.setFont("ElaraDisplayBold", 16)
        c.drawString(586, y_stage + 22, number)
        c.setFillColor(white)
        c.setFont("ElaraBodyBold", 10)
        c.drawString(632, y_stage + 31, title)
        c.setFillColor(mix(TEAL, 0.62))
        c.setFont("ElaraBody", 8)
        c.drawString(632, y_stage + 15, body)
        y_stage -= 72
    rounded_card(
        c,
        596,
        91,
        284,
        38,
        fill=MINT,
        stroke=MINT,
        radius=19,
        shadow=False,
    )
    c.setFillColor(FOREST)
    c.setFont("ElaraBodyBold", 8.5)
    c.drawCentredString(738, 106, "DETERMINISTIC SCORING + CITATION GATE")
    y = 145
    y = label_value(c, 52, y, "Contribution", "Sole contributor", 450) - 9
    y = label_value(c, 52, y, "Timeline", "June 2026 - August 2026", 450) - 9
    label_value(c, 52, y, "Status", "Feature-complete and owner-validated for the hosted-demo scope", 450)
    c.bookmarkPage("page-1")
    c.addOutlineEntry("Elara.ai portfolio case study", "page-1", level=0, closed=False)


def page_glance(c: canvas.Canvas) -> None:
    section_header(c, "Evidence first, by design.", "Project at a glance", 2)
    draw_text(
        c,
        "Elara evaluates one submitted item against timestamped evidence. It preserves the exact sources, passages, snapshots, calculations, versions, and provenance required to reproduce a report.",
        MARGIN,
        420,
        560,
        font="ElaraBody",
        size=12.5,
        leading=18,
    )
    pill(c, "Not a lie detector", MARGIN, 350, fill=PALE_RUST, color=RUST)
    pill(c, "No permanent credibility scores", MARGIN + 132, 350, fill=PALE_GOLD, color=INK)
    pill(c, "Evidence bounded", MARGIN + 360, 350, fill=MINT, color=FOREST)

    values = [("13", "controlled workflow stages"), ("462", "named tests"), ("263", "application and evaluation source files"), ("76", "development commits")]
    for i, (value, label) in enumerate(values):
        metric(c, MARGIN + i * 140, 248, 126, value, label, accent=FOREST if i != 1 else TEAL)

    rounded_card(c, 650, 302, 258, 142, fill=INK, stroke=INK, radius=14)
    c.setFillColor(GOLD)
    c.setFont("ElaraBodyBold", 8)
    c.drawString(670, 416, "AGENTIC HYBRID RAG")
    draw_text(c, "Web discovery and hybrid passage ranking feed evidence-grounded generation inside deterministic scoring and citation gates.", 670, 389, 216, font="ElaraDisplayBold", size=12.5, leading=16.5, color=white)

    rounded_card(c, 650, 130, 258, 150, fill=PALE_MINT, stroke=mix(TEAL, 0.45), radius=14)
    c.setFillColor(FOREST)
    c.setFont("ElaraDisplayBold", 14)
    c.drawString(670, 252, "Who it serves")
    draw_bullets(c, ["Researchers and analysts", "Journalists and policy reviewers", "Technical evaluators who need inspectable evidence"], 670, 226, 216, size=8.7, leading=11.5, gap=5)

    c.setFillColor(MUTED)
    c.setFont("ElaraBody", 8.5)
    c.drawString(MARGIN, 205, "Deployment: Vercel frontend + owner-controlled AWS demo stack")
    c.drawString(MARGIN, 185, "Core rule: no durable citation audit = no completed report")


def page_problem(c: canvas.Canvas) -> None:
    section_header(c, "The product problem", "Audience and success criteria", 3)
    rounded_card(c, 52, 115, 402, 302, fill=PALE_RUST, stroke=mix(RUST, 0.65), radius=14)
    c.setFillColor(RUST)
    c.setFont("ElaraDisplayBold", 19)
    c.drawString(76, 382, "Fluency is not evidence")
    draw_bullets(
        c,
        [
            "A polished answer can conceal weak, missing, or circular evidence.",
            "Repeated reporting can look like independent confirmation.",
            "Quotes, numbers, attribution, and context need different checks.",
            "Public pages are untrusted inputs and can attack retrieval systems.",
            "Missing evidence must remain different from evidence of falsehood.",
        ],
        74,
        344,
        354,
        size=10,
        leading=13.5,
        gap=7,
        bullet_color=RUST,
    )

    rounded_card(c, 478, 115, 430, 302, fill=PALE_MINT, stroke=mix(TEAL, 0.55), radius=14)
    c.setFillColor(FOREST)
    c.setFont("ElaraDisplayBold", 19)
    c.drawString(502, 382, "Success is inspectable")
    draw_bullets(
        c,
        [
            "Every conclusion resolves to an atomic claim and accepted evidence.",
            "Every factual sentence resolves to an exact stored passage.",
            "Scoring and arithmetic are reproducible outside the model.",
            "Contradiction, limitations, and inaccessible sources stay visible.",
            "Incomplete citation coverage prevents publication.",
        ],
        500,
        344,
        382,
        size=10,
        leading=13.5,
        gap=7,
    )
    rounded_card(c, 126, 58, 708, 39, fill=INK, stroke=INK, radius=19, shadow=False)
    c.setFillColor(white)
    c.setFont("ElaraBodyBold", 10)
    c.drawCentredString(480, 73, "One item in. Timestamped evidence, explicit uncertainty, and a reproducible assessment out.")


def page_architecture(c: canvas.Canvas) -> None:
    section_header(c, "Architecture with a hard publication gate", "System design", 4)
    image_fit(c, DIAGRAMS / "01-system-architecture.png", 52, 104, 610, 320, pad=8)
    rounded_card(c, 686, 104, 222, 320, fill=INK, stroke=INK, radius=14)
    c.setFillColor(GOLD)
    c.setFont("ElaraBodyBold", 8)
    c.drawString(706, 393, "DESIGN DECISIONS")
    y = 365
    decisions = [
        ("FastAPI is privileged", "Auth, authorization, durable run creation, exports, and SSE."),
        ("PostgreSQL is truth", "Runs, passages, evidence, calculations, reports, and citations persist durably."),
        ("Redis is transient", "Queues, locks, rate limits, caches, and progress streams can expire."),
        ("The browser presents", "Final scores and report eligibility are never recomputed client-side."),
    ]
    for title, body in decisions:
        c.setFillColor(white)
        c.setFont("ElaraBodyBold", 10.2)
        c.drawString(706, y, title)
        y = draw_text(c, body, 706, y - 15, 180, font="ElaraBody", size=8.2, leading=10.5, color=mix(TEAL, 0.58)) - 13


def page_workflow(c: canvas.Canvas) -> None:
    section_header(c, "Language understanding, deterministic authority", "Controlled workflow", 5)
    image_fit(c, DIAGRAMS / "02-verification-workflow.png", 52, 165, 420, 250, pad=8)
    image_fit(c, DIAGRAMS / "03-model-deterministic-boundary.png", 488, 165, 420, 250, pad=8)
    c.setFillColor(MUTED)
    c.setFont("ElaraBodyBold", 8)
    c.drawString(64, 145, "13 TYPED STAGES")
    c.drawString(500, 145, "MODEL / DETERMINISTIC BOUNDARY")
    rounded_card(c, 92, 65, 776, 58, fill=INK, stroke=INK, radius=14, shadow=False)
    c.setFillColor(GOLD)
    c.setFont("ElaraDisplayBold", 14)
    c.drawCentredString(480, 93, "A fluent draft is never the completion signal.")
    c.setFillColor(white)
    c.setFont("ElaraBody", 9.5)
    c.drawCentredString(480, 76, "Durable artifacts, typed state, exact coverage, and citation audit decide what can be published.")


def page_walkthrough(c: canvas.Canvas) -> None:
    section_header(c, "One claim, traced end to end", "Representative walkthrough", 6)
    rounded_card(c, 52, 112, 386, 304, fill=PAPER, stroke=LINE, radius=14)
    pill(c, "Privacy-safe representative data", 70, 386, fill=PALE_GOLD, color=INK)
    draw_text(c, "A proposed transit budget increases funding, adds frequent weekend rail service, and relies primarily on sales-tax revenue.", 70, 355, 350, font="ElaraDisplayBold", size=13.5, leading=18)
    y = 290
    steps = [
        ("01", "Decompose", "Funding, service frequency, and revenue source become separate claims."),
        ("02", "Retrieve", "Budget pages 14 and 22 plus an independent board record are preserved."),
        ("03", "Compare", "The budget supports; the board record exposes pending approval."),
        ("04", "Calculate", "Stored weights and deterministic gates preserve the limitation."),
        ("05", "Audit", "Four factual sentences resolve to stored passages before completion."),
    ]
    for num, title, body in steps:
        c.setFillColor(FOREST)
        c.circle(83, y + 5, 13, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("ElaraBodyBold", 7)
        c.drawCentredString(83, y + 2.5, num)
        c.setFillColor(INK)
        c.setFont("ElaraBodyBold", 9.5)
        c.drawString(104, y + 6, title)
        draw_text(c, body, 104, y - 6, 308, font="ElaraBody", size=7.8, leading=9.5, color=MUTED, max_lines=2)
        y -= 39
    image_fit(c, SCREENSHOTS / "02-completed-report-overview.png", 462, 112, 446, 304, pad=6)
    c.setFillColor(MUTED)
    c.setFont("ElaraBodyItalic", 8)
    c.drawRightString(908, 92, "UI contract preview - placeholder domains, no private evidence")


def page_trace(c: canvas.Canvas) -> None:
    section_header(c, "The evidence stays inspectable", "Passages and citations", 7)
    image_fit(c, SCREENSHOTS / "04-evidence-comparison.png", 52, 178, 412, 238, pad=5)
    image_fit(c, SCREENSHOTS / "06-citation-source-drawer.png", 496, 178, 412, 238, pad=5)
    c.setFillColor(FOREST)
    c.setFont("ElaraBodyBold", 9)
    c.drawString(64, 154, "SUPPORT AND CONTRADICTION TOGETHER")
    c.drawString(508, 154, "REPORT SENTENCE TO EXACT PASSAGE")

    labels = ["Verdict", "Atomic claim", "Calculation", "Evidence item", "Exact passage", "Snapshot"]
    x = 52
    y = 82
    box_w = 126
    for i, label in enumerate(labels):
        fill = INK if i in (0, 5) else (MINT if i % 2 else PALE_GOLD)
        color = white if i in (0, 5) else INK
        c.setFillColor(fill)
        c.roundRect(x, y, box_w, 38, 10, stroke=0, fill=1)
        c.setFillColor(color)
        c.setFont("ElaraBodyBold", 8.5)
        c.drawCentredString(x + box_w / 2, y + 14, label)
        if i < len(labels) - 1:
            c.setStrokeColor(TEAL)
            c.setLineWidth(1.5)
            c.line(x + box_w + 5, y + 19, x + box_w + 20, y + 19)
            c.line(x + box_w + 16, y + 23, x + box_w + 20, y + 19)
            c.line(x + box_w + 16, y + 15, x + box_w + 20, y + 19)
        x += 147


def page_scoring(c: canvas.Canvas) -> None:
    section_header(c, "A worked score, outside the model", "Deterministic scoring", 8)
    rounded_card(c, 52, 126, 402, 290, fill=INK, stroke=INK, radius=14)
    pill(c, "Representative funding claim", 72, 384, fill=Color(1, 1, 1, alpha=0.1), color=GOLD)
    c.setFillColor(white)
    c.setFont("ElaraDisplayBold", 18)
    c.drawString(72, 346, "Supporting weight  P = 66")
    c.drawString(72, 316, "Contradicting weight  N = 34")
    c.setStrokeColor(Color(1, 1, 1, alpha=0.18))
    c.line(72, 295, 432, 295)
    c.setFont("ElaraBody", 10.5)
    c.drawString(72, 267, "evidence support = 100 x P / (P + N)")
    c.setFillColor(GOLD)
    c.setFont("ElaraDisplayBold", 39)
    c.drawString(72, 211, "66%")
    c.setFillColor(mix(TEAL, 0.62))
    c.setFont("ElaraBody", 9)
    c.drawString(172, 222, "direction of accepted evidence")
    c.setFillColor(white)
    c.setFont("ElaraBodyBold", 10)
    c.drawString(72, 174, "Final label: Supported with limitations")
    draw_text(c, "The pending approval record and context gates remain visible. A numeric direction never erases a material limitation.", 72, 154, 344, font="ElaraBody", size=8.5, leading=11, color=mix(TEAL, 0.62))

    image_fit(c, SCREENSHOTS / "05-deterministic-score-dashboard.png", 478, 126, 430, 290, pad=5)
    rounded_card(c, 128, 63, 704, 42, fill=PALE_MINT, stroke=mix(TEAL, 0.55), radius=12, shadow=False)
    c.setFillColor(FOREST)
    c.setFont("ElaraBodyBold", 9.5)
    c.drawCentredString(480, 81, "Dependency multipliers discount repeated reporting before evidence contributes to P or N.")


def horizontal_bar(c: canvas.Canvas, x: float, y: float, width: float, value: float, maximum: float, color: Color, label: str, value_label: str) -> None:
    c.setFillColor(LINE)
    c.roundRect(x, y, width, 13, 6.5, stroke=0, fill=1)
    c.setFillColor(color)
    c.roundRect(x, y, max(2, width * value / maximum), 13, 6.5, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("ElaraBodyBold", 8.5)
    c.drawString(x, y + 20, label)
    c.drawRightString(x + width, y + 20, value_label)


def page_outcomes(c: canvas.Canvas) -> None:
    section_header(c, "Baseline, implementation, and proof are separated", "Engineering outcomes", 9)

    cards = [
        (52, "MEASURED BASELINE", PALE_RUST, RUST),
        (342, "IMPLEMENTED REMEDIATION", PALE_MINT, FOREST),
        (632, "POST-FIX EVIDENCE", PALE_GOLD, GOLD),
    ]
    for x, label, fill, accent in cards:
        rounded_card(c, x, 224, 276, 190, fill=fill, stroke=mix(accent, 0.55), radius=14)
        pill(c, label, x + 18, 383, fill=PAPER, color=accent)

    c.setFillColor(INK)
    c.setFont("ElaraDisplayBold", 16)
    c.drawString(70, 350, "Where the time went")
    c.setFont("ElaraDisplayBold", 23)
    c.drawString(70, 312, "218.9 s")
    c.setFont("ElaraBodyBold", 8)
    c.drawString(174, 318, "classification")
    c.setFont("ElaraDisplayBold", 23)
    c.drawString(70, 274, "193.1 s")
    c.setFont("ElaraBodyBold", 8)
    c.drawString(174, 280, "citation audit")
    draw_text(c, "Scoring was 0.09 s; numerical audit was 0.06 s. The bottleneck was model-backed language work, not arithmetic.", 70, 250, 238, font="ElaraBody", size=7.9, leading=9.5, color=MUTED, max_lines=3)

    c.setFillColor(INK)
    c.setFont("ElaraDisplayBold", 16)
    c.drawString(360, 350, "Smaller failure domains")
    draw_bullets(
        c,
        [
            "Classification batch: 4 -> 2 -> 1 task",
            "Citation batch: 4 -> 2 pairs",
            "Concurrency capped at 2 model calls",
            "Schema attempts: 3 -> 2 per batch",
            "Exact merge coverage; no partial publish",
        ],
        358,
        319,
        242,
        size=8,
        leading=9.5,
        gap=3,
        bullet_color=FOREST,
    )

    c.setFillColor(INK)
    c.setFont("ElaraDisplayBold", 16)
    c.drawString(650, 350, "Target is not a result")
    c.setFillColor(FOREST)
    c.setFont("ElaraDisplayBold", 22)
    c.drawString(650, 310, "<90 s")
    c.setFont("ElaraBodyBold", 8)
    c.drawString(733, 316, "classification median")
    c.setFont("ElaraDisplayBold", 22)
    c.drawString(650, 274, "<60 s")
    c.setFont("ElaraBodyBold", 8)
    c.drawString(733, 280, "citation-audit median")
    pill(c, "NOT YET MEASURED", 650, 245, fill=PAPER, color=RUST)
    draw_text(c, "The repository has no completed three-run controlled-live median after the fix. These are acceptance targets, not claimed fixed times.", 650, 238, 238, font="ElaraBody", size=7.8, leading=9.3, color=MUTED, max_lines=2)

    rounded_card(c, 52, 70, 856, 128, fill=PAPER, stroke=LINE, radius=14)
    c.setFillColor(FOREST)
    c.setFont("ElaraDisplayBold", 15)
    c.drawString(70, 170, "Reliability and cost outcomes")
    outcomes = [
        ("STRUCTURED OUTPUT", "HTTP 200 + invalid schema now produces typed, privacy-safe failure data and bounded local recovery."),
        ("OBSERVABILITY", "Durable metadata records wall latency, requests, batches, repairs, tokens, model, and prompt version."),
        ("SEARCH ENVELOPE", "First-phase query targets changed 24/60/120 -> 8/18/36; mandatory coverage still opens phase two."),
    ]
    for i, (title, body) in enumerate(outcomes):
        x = 70 + i * 278
        c.setFillColor(GOLD if i == 2 else TEAL)
        c.setFont("ElaraBodyBold", 7.5)
        c.drawString(x, 143, title)
        draw_text(c, body, x, 125, 244, font="ElaraBody", size=7.8, leading=9.4, color=MUTED, max_lines=4)


def page_resolved_failures(c: canvas.Canvas) -> None:
    section_header(c, "Problems found, fixes applied, proof retained", "Engineering outcomes", 10)
    outcomes = [
        (
            "Transport tests failed too early",
            "Redis, Celery, and S3 security tests stopped at release-revision validation.",
            "Built a valid production baseline, then varied only the transport under test.",
            "Intended validators reached; release revision remains independently covered.",
            RUST,
        ),
        (
            "Migrations depended on CWD",
            "The schema gate could not find migrations when launched from the repository root.",
            "Resolved Alembic paths from apps/api/alembic.ini instead of process CWD.",
            "Single-head and upgrade checks pass from root and API contexts.",
            TEAL,
        ),
        (
            "Legal hold returned the wrong error",
            "A held report failed as storage unavailable instead of an explicit conflict.",
            "Normalized UTC-aware times and moved the hold check before mutation or cleanup.",
            "Active hold returns 409; records and export objects remain untouched.",
            GOLD,
        ),
        (
            "Legacy visibility looked permissive",
            "A stale test treated visibility=public as cross-user authorization.",
            "Kept access owner- or recipient-specific with scope, expiry, and revocation checks.",
            "Unshared, expired, revoked, or wrong-scope access returns non-disclosing 404.",
            FOREST,
        ),
        (
            "Local storage assumptions leaked",
            "MinIO defaults did not match private AWS S3 endpoint and addressing behavior.",
            "Separated endpoint, TLS, internal discovery, and path-style configuration.",
            "Regional AWS S3 uses secure transport with forced path style disabled.",
            TEAL,
        ),
        (
            "Retryable fetch escaped retry policy",
            "A source timeout crossed the generic worker boundary and stopped the run.",
            "Mapped only retryable FetchError values to the typed fetch failure boundary.",
            "Focused retrieval/task regression suite passed: 37 tests.",
            RUST,
        ),
    ]
    for i, (title, problem, fix, proof, accent) in enumerate(outcomes):
        col, row = i % 3, i // 3
        x = 52 + col * 292
        y = 244 if row == 0 else 67
        rounded_card(c, x, y, 274, 158, fill=PAPER, stroke=mix(accent, 0.55), radius=13)
        c.setFillColor(accent)
        c.roundRect(x, y + 146, 274, 12, 6, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("ElaraDisplayBold", 12.5)
        c.drawString(x + 16, y + 122, title)
        c.setFillColor(RUST)
        c.setFont("ElaraBodyBold", 6.8)
        c.drawString(x + 16, y + 103, "PROBLEM")
        draw_text(c, problem, x + 62, y + 103, 194, font="ElaraBody", size=7.1, leading=8.3, color=MUTED, max_lines=2)
        c.setFillColor(FOREST)
        c.setFont("ElaraBodyBold", 6.8)
        c.drawString(x + 16, y + 70, "FIX")
        draw_text(c, fix, x + 62, y + 70, 194, font="ElaraBody", size=7.1, leading=8.3, color=MUTED, max_lines=2)
        c.setFillColor(accent)
        c.setFont("ElaraBodyBold", 6.8)
        c.drawString(x + 16, y + 37, "PROOF")
        draw_text(c, proof, x + 62, y + 37, 194, font="ElaraBody", size=7.1, leading=8.3, color=INK, max_lines=2)


def page_security(c: canvas.Canvas) -> None:
    section_header(c, "Trust boundaries are product features", "Security and evidence integrity", 11)
    items = [
        ("Server-side secrets", "DeepSeek, Brave, Firebase Admin, database, Redis, S3, Sentry auth, and tracing credentials never enter the browser.", FOREST),
        ("Untrusted evidence", "Retrieved pages cannot alter workflow instructions, credentials, scoring formulas, or final verdict rules.", TEAL),
        ("Network safety", "HTTP(S) only; private, reserved, link-local, metadata, redirect, DNS, port, size, type, and time checks.", RUST),
        ("Authorization", "Runs, sources, snapshots, reports, exports, shares, saved items, and feedback are owner- or recipient-authorized.", FOREST),
        ("Durable truth", "PostgreSQL remains authoritative when Redis locks, queues, cache entries, or progress streams expire.", TEAL),
        ("Fail-closed reports", "Missing evidence, invalid structured output, rejected citations, or incomplete audit coverage cannot become complete.", GOLD),
    ]
    for i, (title, body, accent) in enumerate(items):
        col, row = i % 3, i // 3
        x = 52 + col * 292
        y = 257 if row == 0 else 89
        rounded_card(c, x, y, 274, 145, fill=PAPER, stroke=mix(accent, 0.55), radius=14)
        c.setFillColor(accent)
        c.roundRect(x, y + 132, 274, 13, 7, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("ElaraDisplayBold", 14)
        c.drawString(x + 18, y + 103, title)
        draw_text(c, body, x + 18, y + 80, 238, font="ElaraBody", size=8.5, leading=11, color=MUTED, max_lines=5)


def page_validation(c: canvas.Canvas) -> None:
    section_header(c, "Validation, with the evidence boundary visible", "Testing and demo readiness", 12)
    metrics = [("120", "API tests"), ("238", "worker tests"), ("97", "web tests"), ("6", "evaluation tests"), ("1", "full-stack acceptance")]
    for i, (value, label) in enumerate(metrics):
        metric(c, 52 + i * 172, 337, 154, value, label, accent=FOREST if i != 3 else GOLD)

    cards = [
        ("Repository gates", "Builds, migrations, security regressions, deterministic acceptance, and 462 named tests.", "REPRODUCIBLE", PALE_MINT, FOREST),
        ("Hosted demo", "The sole contributor confirmed sign-in, queueing, Celery execution, durable completion, citation-audited retrieval, and refresh.", "OWNER VALIDATED", PALE_GOLD, INK),
        ("Methodology evaluation", "Offline graders and draft splits exist, but annotations and thresholds remain pending human approval.", "NOT A BENCHMARK", PALE_RUST, RUST),
    ]
    for i, (title, body, tag, fill, accent) in enumerate(cards):
        x = 52 + i * 292
        rounded_card(c, x, 112, 274, 190, fill=fill, stroke=mix(accent, 0.55), radius=14)
        pill(c, tag, x + 18, 266, fill=PAPER, color=accent)
        c.setFillColor(INK)
        c.setFont("ElaraDisplayBold", 15)
        c.drawString(x + 18, 232, title)
        draw_text(c, body, x + 18, 207, 238, font="ElaraBody", size=9, leading=12, color=SLATE)
    c.setFillColor(MUTED)
    c.setFont("ElaraBodyItalic", 8)
    c.drawString(52, 82, "No third-party audit or public-production approval is claimed.")


def page_limits(c: canvas.Canvas) -> None:
    section_header(c, "Current limitations and deliberate non-goals", "Scope and tradeoffs", 13)
    rounded_card(c, 52, 93, 542, 319, fill=PAPER, stroke=LINE, radius=14)
    c.setFillColor(FOREST)
    c.setFont("ElaraDisplayBold", 17)
    c.drawString(74, 378, "What remains bounded")
    draw_bullets(
        c,
        [
            "Human-reviewed evaluation annotations and thresholds are still pending; no independent accuracy benchmark is claimed.",
            "The transit screenshots use privacy-safe placeholder data, not a live public-authority verification.",
            "Paywalls, robots restrictions, deleted pages, inaccessible PDFs, and unsupported formats can limit evidence coverage.",
            "Provider latency and availability vary; the personal demo has no latency or uptime service-level objective.",
            "Assessments are time-bounded and may change when sources, corrections, or evidence change.",
            "Security controls are tested, but the project is not independently audited or certified for public launch.",
        ],
        72,
        346,
        500,
        size=9.2,
        leading=12,
        gap=6,
    )

    rounded_card(c, 618, 242, 290, 170, fill=INK, stroke=INK, radius=14)
    c.setFillColor(GOLD)
    c.setFont("ElaraBodyBold", 8)
    c.drawString(638, 382, "INTENTIONAL DEMO POSTURE")
    draw_text(c, "One EC2 host, manual recovery, no high availability, no multi-AZ, no autoscaling, and no enterprise on-call.", 638, 350, 250, font="ElaraDisplayBold", size=14, leading=19, color=white)
    c.setFillColor(mix(TEAL, 0.58))
    c.setFont("ElaraBody", 8)
    c.drawString(638, 266, "Simplicity is a scope decision, not an availability claim.")

    rounded_card(c, 618, 93, 290, 125, fill=PALE_RUST, stroke=mix(RUST, 0.55), radius=14)
    c.setFillColor(RUST)
    c.setFont("ElaraDisplayBold", 15)
    c.drawString(638, 184, "Never a credibility score")
    draw_text(c, "Elara evaluates one submitted item against evidence available at a recorded time. It does not score the permanent honesty of a person, organization, or publication.", 638, 159, 248, font="ElaraBody", size=8.5, leading=11, color=INK)


def page_contribution(c: canvas.Canvas) -> None:
    section_header(c, "Built end to end by one contributor", "Contribution and decisions", 14)
    rounded_card(c, 52, 99, 420, 315, fill=INK, stroke=INK, radius=14)
    c.setFillColor(GOLD)
    c.setFont("ElaraBodyBold", 8)
    c.drawString(72, 384, "SOLE CONTRIBUTOR")
    draw_text(c, "I owned the entire path from product boundary to hosted demonstration.", 72, 350, 360, font="ElaraDisplayBold", size=19, leading=25, color=white)
    draw_bullets(
        c,
        [
            "Product strategy, UX, design system, and report language",
            "Next.js frontend, FastAPI API, PostgreSQL model, and migrations",
            "Celery/LangGraph workflow, DeepSeek and Brave integrations",
            "Retrieval security, provenance, deterministic scoring, and citation gates",
            "Tests, evaluation harness, CI, AWS/Vercel deployment, and documentation",
        ],
        72,
        278,
        360,
        size=9,
        leading=11.5,
        gap=5,
        bullet_color=GOLD,
        text_color=mix(TEAL, 0.68),
    )

    c.setFillColor(FOREST)
    c.setFont("ElaraDisplayBold", 17)
    c.drawString(500, 390, "Engineering lessons")
    lessons = [
        ("01", "Typed output", "HTTP success is not schema success; recovery must preserve exact coverage."),
        ("02", "Measured stages", "Instrumentation showed model calls, not arithmetic, owned the latency."),
        ("03", "Adaptive cost", "Mandatory primary and contradiction paths survive a smaller first-phase budget."),
        ("04", "Right failure boundary", "A fail-closed test matters only when it exercises the boundary named."),
    ]
    y = 346
    for num, title, body in lessons:
        rounded_card(c, 500, y - 48, 408, 62, fill=PAPER, stroke=LINE, radius=10, shadow=False)
        c.setFillColor(GOLD if num != "04" else RUST)
        c.setFont("ElaraDisplayBold", 17)
        c.drawString(516, y - 15, num)
        c.setFillColor(INK)
        c.setFont("ElaraBodyBold", 9.2)
        c.drawString(558, y - 6, title)
        draw_text(c, body, 558, y - 20, 330, font="ElaraBody", size=7.6, leading=9.2, color=MUTED, max_lines=2)
        y -= 72


def page_close(c: canvas.Canvas) -> None:
    section_header(c, "Evidence should survive the answer.", "Portfolio summary", 15, dark=True)
    draw_text(
        c,
        "Elara shows how language models can operate inside a controlled evidence system without becoming the final authority.",
        52,
        408,
        650,
        font="ElaraDisplayBold",
        size=25,
        leading=33,
        color=white,
    )
    rounded_card(c, 52, 173, 548, 146, fill=Color(1, 1, 1, alpha=0.06), stroke=Color(1, 1, 1, alpha=0.14), radius=14, shadow=False)
    draw_bullets(
        c,
        [
            "Model-assisted interpretation; deterministic final control",
            "Durable evidence, exact passages, calculations, and provenance",
            "Credible contradiction and explicit limitations",
            "Citation-gated completion and owner-controlled deployment",
        ],
        74,
        286,
        502,
        size=10,
        leading=13,
        gap=5,
        bullet_color=GOLD,
        text_color=mix(TEAL, 0.72),
    )
    rounded_card(c, 632, 173, 276, 214, fill=PAPER, stroke=PAPER, radius=14)
    c.setFillColor(FOREST)
    c.setFont("ElaraDisplayBold", 18)
    c.drawString(654, 348, "Explore the demo")
    url = "https://elara-ai-web.vercel.app/"
    draw_text(c, "Owner-controlled personal demonstration", 654, 321, 232, font="ElaraBody", size=9, leading=12, color=MUTED)
    c.setFillColor(INK)
    c.roundRect(654, 258, 232, 40, 12, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("ElaraBodyBold", 9)
    c.drawCentredString(770, 273, "OPEN ELARA.AI DEMO")
    c.linkURL(url, (654, 258, 886, 298), relative=0, thickness=0)
    c.setFillColor(MUTED)
    c.setFont("ElaraBody", 7.5)
    c.drawString(654, 232, "elara-ai-web.vercel.app")
    c.setFillColor(RUST)
    c.setFont("ElaraBodyBold", 8)
    c.drawString(654, 205, "SCOPE NOTE")
    draw_text(c, "Feature-complete and owner-validated for a low-traffic demo. Human-calibrated methodology evaluation remains future work.", 716, 205, 168, font="ElaraBody", size=7.5, leading=9.5, color=INK)
    c.setFillColor(mix(TEAL, 0.55))
    c.setFont("ElaraBody", 8)
    c.drawString(52, 124, "Built June-August 2026  /  Next.js + FastAPI + PostgreSQL + Celery + LangGraph + DeepSeek + Brave")


def add_language_metadata(path: Path) -> None:
    reader = PdfReader(str(path))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.root_object[NameObject("/Lang")] = TextStringObject("en-CA")
    writer.root_object[NameObject("/ViewerPreferences")] = DictionaryObject(
        {NameObject("/DisplayDocTitle"): BooleanObject(True)}
    )
    metadata = dict(reader.metadata or {})
    metadata.update(
        {
            "/Title": "Elara.ai Portfolio Case Study",
            "/Author": "Elara.ai project owner and sole contributor",
            "/Subject": "Evidence-first automated verification platform",
            "/Keywords": "Elara.ai, evidence management, verification, deterministic scoring, citations",
        }
    )
    writer.add_metadata(metadata)
    with OUTPUT.open("wb") as handle:
        writer.write(handle)
    path.unlink(missing_ok=True)


def build() -> None:
    register_fonts()
    c = canvas.Canvas(str(TEMP_OUTPUT), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle("Elara.ai Portfolio Case Study")
    c.setAuthor("Elara.ai project owner and sole contributor")
    c.setSubject("Evidence-first automated verification platform")
    pages = [
        page_cover,
        page_glance,
        page_problem,
        page_architecture,
        page_workflow,
        page_walkthrough,
        page_trace,
        page_scoring,
        page_outcomes,
        page_resolved_failures,
        page_security,
        page_validation,
        page_limits,
        page_contribution,
        page_close,
    ]
    for page in pages:
        page(c)
        c.showPage()
    c.save()
    add_language_metadata(TEMP_OUTPUT)
    print(f"Built {OUTPUT} ({len(pages)} pages)")


if __name__ == "__main__":
    build()
