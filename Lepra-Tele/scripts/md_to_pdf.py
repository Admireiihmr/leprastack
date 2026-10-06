"""Lightweight Markdown -> PDF renderer (ReportLab only).

Handles the subset of Markdown used in this repo's docs: ATX headings,
paragraphs, bullet/numbered lists, pipe tables, fenced code blocks, blockquotes,
horizontal rules, and inline **bold** / `code`. Unicode box-drawing and arrow
glyphs are transliterated to ASCII so they render in the base fonts.

Usage:  python scripts/md_to_pdf.py <input.md> <output.pdf>
"""
import re
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle,
)

MARGIN = 16 * mm
CONTENT_W = A4[0] - 2 * MARGIN

BRAND = colors.HexColor("#2563eb")
INK = colors.HexColor("#0f1d36")
MUTED = colors.HexColor("#6a7896")
CODE_BG = colors.HexColor("#f3f6fc")
BORDER = colors.HexColor("#d3deef")
HEAD_BG = colors.HexColor("#eaf1ff")

_TRANS = {
    "│": "|", "─": "-", "┌": "+", "┐": "+", "└": "+", "┘": "+",
    "├": "+", "┤": "+", "┬": "+", "┴": "+", "┼": "+",
    "▶": ">", "◀": "<", "▼": "v", "▲": "^", "►": ">", "◁": "<",
    "→": "->", "←": "<-", "▸": ">",
}
_TRANS_TABLE = str.maketrans(_TRANS)


def translit(s: str) -> str:
    return s.translate(_TRANS_TABLE)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(s: str) -> str:
    s = esc(translit(s))
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r'<font face="Courier" size="9" color="#1d4ed8">\1</font>', s)
    return s


def styles():
    ss = getSampleStyleSheet()
    base = ss["BodyText"]
    base.fontName = "Helvetica"
    base.fontSize = 10
    base.leading = 14.5
    base.textColor = INK
    base.spaceAfter = 6
    return {
        "body": base,
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=BRAND, spaceBefore=8, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=14.5, leading=19, textColor=INK, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=BRAND, spaceBefore=10, spaceAfter=4),
        "li": ParagraphStyle("li", parent=base, leftIndent=14, spaceAfter=3),
        "li2": ParagraphStyle("li2", parent=base, leftIndent=30, spaceAfter=2, textColor=colors.HexColor("#3b4b6b")),
        "quote": ParagraphStyle("quote", parent=base, leftIndent=12, borderPadding=8, backColor=colors.HexColor("#fff8e6"), textColor=colors.HexColor("#7a5b00")),
        "code": ParagraphStyle("code", parent=base, fontName="Courier", fontSize=8, leading=10.5, textColor=colors.HexColor("#14306b"), backColor=CODE_BG, borderPadding=8, borderWidth=0.5, borderColor=BORDER),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9, leading=12, spaceAfter=0),
        "cellhead": ParagraphStyle("cellhead", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=INK, spaceAfter=0),
    }


def build(md: str, out_path: str):
    S = styles()
    flow = []
    lines = md.replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    para_buf = []

    def flush_para():
        nonlocal para_buf
        if para_buf:
            flow.append(Paragraph(inline(" ".join(para_buf)), S["body"]))
            para_buf = []

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            flush_para()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(translit(esc(lines[i])))
                i += 1
            i += 1  # closing fence
            flow.append(Preformatted("\n".join(buf), S["code"]))
            flow.append(Spacer(1, 6))
            continue

        # Pipe table
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush_para()
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1

            def cells(r):
                return [c.strip() for c in r.strip().strip("|").split("|")]

            header = cells(rows[0])
            data = [cells(r) for r in rows[2:]]  # skip separator
            ncols = len(header)
            colw = [CONTENT_W / ncols] * ncols
            table_data = [[Paragraph(inline(h), S["cellhead"]) for h in header]]
            for r in data:
                r = (r + [""] * ncols)[:ncols]
                table_data.append([Paragraph(inline(c), S["cell"]) for c in r])
            t = Table(table_data, colWidths=colw, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7faff")]),
            ]))
            flow.append(t)
            flow.append(Spacer(1, 8))
            continue

        # Horizontal rule
        if stripped == "---":
            flush_para()
            flow.append(Spacer(1, 4))
            flow.append(HRFlowable(width="100%", thickness=0.7, color=BORDER, spaceBefore=2, spaceAfter=8))
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            key = "h1" if level == 1 else "h2" if level == 2 else "h3"
            flow.append(Paragraph(inline(m.group(2)), S[key]))
            i += 1
            continue

        # Blockquote
        if stripped.startswith("> "):
            flush_para()
            flow.append(Paragraph(inline(stripped[2:]), S["quote"]))
            flow.append(Spacer(1, 4))
            i += 1
            continue

        # List items (bullet or numbered), indent-aware
        indent = len(line) - len(line.lstrip(" "))
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if bullet:
            flush_para()
            sty = S["li2"] if indent >= 2 else S["li"]
            flow.append(Paragraph("&bull;&nbsp;&nbsp;" + inline(bullet.group(1)), sty))
            i += 1
            continue
        if numbered:
            flush_para()
            sty = S["li2"] if indent >= 3 else S["li"]
            flow.append(Paragraph(f"<b>{numbered.group(1)}.</b>&nbsp;&nbsp;" + inline(numbered.group(2)), sty))
            i += 1
            continue

        # Blank line ends a paragraph
        if not stripped:
            flush_para()
            i += 1
            continue

        para_buf.append(stripped)
        i += 1

    flush_para()

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=16 * mm,
        title="Tele-Leprosy Triage Console — Workflow",
    )

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 10 * mm, "Tele-Leprosy Triage Console — Workflow")
        canvas.drawRightString(A4[0] - MARGIN, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(flow, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "WORKFLOW.md"
    out = sys.argv[2] if len(sys.argv) > 2 else "WORKFLOW.pdf"
    with open(src, "r", encoding="utf-8") as f:
        build(f.read(), out)
    print(f"Wrote {out}")
