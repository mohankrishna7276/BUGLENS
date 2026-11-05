"""PDF report generation with ReportLab (free, open source)."""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=_styles["Heading1"], textColor=colors.HexColor("#0B5394"), fontSize=18)
H2 = ParagraphStyle("H2", parent=_styles["Heading2"], textColor=colors.HexColor("#1F4E79"), fontSize=13,
                    spaceBefore=10)
BODY = ParagraphStyle("Body", parent=_styles["BodyText"], fontSize=10, leading=14)
CODE = ParagraphStyle("Code", fontName="Courier", fontSize=8, leading=10, backColor=colors.HexColor("#F2F2F2"),
                      borderPadding=4, leftIndent=2)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8, leading=10)


def _clean(text):
    """ReportLab's built-in fonts are Latin-1 only; replace other characters safely."""
    return str(text if text is not None else "").encode("latin-1", "replace").decode("latin-1")


def _p(text, style=BODY):
    return Paragraph(escape(_clean(text)).replace("\n", "<br/>"), style)


def _code(text):
    lines = _clean(text).replace("\t", "    ").splitlines() or [""]
    wrapped = []
    for l in lines:  # hard-wrap very long lines so they stay on the page
        wrapped += [l[i:i + 95] for i in range(0, len(l), 95)] or [""]
    return Preformatted("\n".join(wrapped), CODE)


def _bullets(items):
    return [_p(f"- {i}") for i in items] or [_p("None.")]


def generate_pdf(record):
    """Build a PDF (bytes) from a debugging record dict."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm, title="BugLens AI Debugging Report")
    s = []
    s.append(Paragraph("BugLens AI - Debugging Report", H1))
    s.append(_p(f"Language: {record.get('language', '')}    |    Generated: "
                f"{record.get('timestamp') or datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    s.append(Spacer(1, 6))

    s.append(Paragraph("1. Submitted Code", H2))
    s.append(_code(record.get("code", "")))

    s.append(Paragraph("2. Detected Errors (static analysis)", H2))
    findings = record.get("static_findings")
    if findings is None:
        s.append(_p("Static analysis was not run."))
    elif not findings:
        s.append(_p("No errors were detected by static analysis."))
    else:
        rows = [["Line", "Severity", "Method", "Message"]] + [
            [str(f["line"] or "-"), f["severity"], f["method"], _p(f["message"], CELL)] for f in findings]
        t = Table(rows, colWidths=[1.2 * cm, 2 * cm, 2.4 * cm, 11.4 * cm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 8),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        s.append(t)

    ai = record.get("ai")
    s.append(Paragraph("3. AI Analysis", H2))
    if not ai:
        s.append(_p(record.get("ai_error") or "AI debugging was not run for this submission."))
    else:
        s.append(_p("Summary: " + ai.get("summary", "")))
        s.append(Paragraph("AI-identified errors", H2))
        s += _bullets([f"Line {e.get('line') or '?'} ({e.get('type', '')}): {e.get('description', '')}"
                       for e in ai.get("errors", [])])
        s.append(Paragraph("Possible bugs (AI-suggested, not verified)", H2))
        s += _bullets([f"Line {e.get('line') or '?'}: {e.get('description', '')}" for e in ai.get("possible_bugs", [])])
        s.append(Paragraph("Root cause", H2))
        s.append(_p(ai.get("root_cause", "")))
        if ai.get("affected_section"):
            s.append(_p("Affected section: " + ai["affected_section"]))
        s.append(Paragraph("4. Corrected Code", H2))
        s.append(_code(ai.get("corrected_code", "")))
        s.append(Paragraph("Explanation of the correction", H2))
        s.append(_p(ai.get("explanation", "")))
        s.append(Paragraph("Prevention tips", H2))
        s += _bullets(ai.get("prevention_tips", []))

    s.append(Paragraph("5. Optimization Suggestions", H2))
    opt = record.get("optimization")
    if not opt:
        s.append(_p("Not generated for this submission."))
    else:
        s.append(_p(f"Time complexity: {opt['time_complexity'].get('estimate', '')} - "
                    f"{opt['time_complexity'].get('reasoning', '')}"))
        s.append(_p(f"Space complexity: {opt['space_complexity'].get('estimate', '')} - "
                    f"{opt['space_complexity'].get('reasoning', '')}"))
        s.append(Paragraph("Readability", H2)); s += _bullets(opt.get("readability", []))
        s.append(Paragraph("Best practices", H2)); s += _bullets(opt.get("best_practices", []))
        if opt.get("optimized_code"):
            s.append(Paragraph("Optimized code", H2)); s.append(_code(opt["optimized_code"]))

    s.append(Paragraph("6. Generated Test Cases", H2))
    tests = record.get("tests")
    if not tests:
        s.append(_p("Not generated for this submission."))
    else:
        rows = [["Type", "Input", "Expected output", "Note"]]
        for kind in ("normal", "edge", "boundary"):
            for t in tests.get(kind, []):
                rows.append([kind.capitalize(), _p(t.get("input", ""), CELL),
                             _p(t.get("expected_output", ""), CELL), _p(t.get("note", ""), CELL)])
        if len(rows) == 1:
            s.append(_p("The model returned no test cases."))
        else:
            t = Table(rows, colWidths=[1.8 * cm, 4.8 * cm, 4.2 * cm, 6.2 * cm], repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                                   ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                   ("FONTSIZE", (0, 0), (-1, -1), 8),
                                   ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            s.append(t)

    s.append(Spacer(1, 12))
    s.append(_p("AI-generated content may contain mistakes. Always verify suggestions by running your code.",
                ParagraphStyle("Foot", parent=BODY, fontSize=8, textColor=colors.grey)))
    doc.build(s)
    return buf.getvalue()
