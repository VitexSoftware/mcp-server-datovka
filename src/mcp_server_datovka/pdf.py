"""Render plain text to a PDF for sending as an ISDS message attachment.

ISDS messages carry documents, not body text (see ``send_message``), so
composing a "plain text message" means rendering the text to a document
first. PDF is the standard, universally-accepted format for this. A
Unicode TTF font is required to render Czech diacritics correctly; this
uses the system's DejaVu Sans font (``fonts-dejavu-core``) rather than
bundling one.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

_DEJAVU_SANS = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
_DEJAVU_SANS_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def text_to_pdf(subject: str, body: str) -> bytes:
    """Render a subject heading and body text to a single-page-or-more PDF."""
    if not _DEJAVU_SANS.is_file():
        raise RuntimeError(
            "DejaVu Sans font not found at "
            f"{_DEJAVU_SANS} -- install the fonts-dejavu-core package."
        )

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(_DEJAVU_SANS))
    if _DEJAVU_SANS_BOLD.is_file():
        pdf.add_font("DejaVu", "B", str(_DEJAVU_SANS_BOLD))

    pdf.set_font("DejaVu", "B" if _DEJAVU_SANS_BOLD.is_file() else "", size=16)
    pdf.multi_cell(0, 10, subject)
    pdf.ln(4)

    pdf.set_font("DejaVu", size=12)
    pdf.multi_cell(0, 7, body)

    return bytes(pdf.output())
