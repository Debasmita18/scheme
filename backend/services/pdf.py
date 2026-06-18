"""
HTML -> PDF conversion (pure-Python, no system libraries).

Uses xhtml2pdf (ReportLab under the hood) so it works identically on
Windows dev and on free Linux PaaS without cairo/pango/wkhtmltopdf.
"""

from __future__ import annotations

import io
from typing import Optional

from loguru import logger

# Map Unicode characters the built-in PDF fonts can't render (which show as
# black "tofu" boxes) to safe ASCII equivalents.
_REPLACEMENTS = {
    "₹": "Rs ",   # ₹ rupee sign
    "–": "-",      # – en dash
    "—": "-",      # — em dash
    "‒": "-",      # ‒ figure dash
    "‑": "-",      # ‑ non-breaking hyphen
    "−": "-",      # − minus sign
    "‘": "'", "’": "'",   # ‘ ’ curly single quotes
    "“": '"', "”": '"',   # “ ” curly double quotes
    "…": "...",   # … ellipsis
    "•": "-",      # • bullet
    "≈": "~",      # ≈ approx
    "→": "->",     # → arrow
    " ": " ", " ": " ", " ": " ", "​": "",  # spaces
}


def sanitize(text: str) -> str:
    """Replace non-Latin-1 glyphs with ASCII so no 'tofu' boxes appear."""
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    # Drop any remaining characters outside Latin-1 to be safe.
    return text.encode("latin-1", "ignore").decode("latin-1")


def html_to_pdf(html: str) -> Optional[bytes]:
    """Render an HTML document to PDF bytes. Returns None on failure."""
    try:
        from xhtml2pdf import pisa
    except Exception as exc:  # pragma: no cover
        logger.error("xhtml2pdf not installed: {}", exc)
        return None

    html = sanitize(html)
    buf = io.BytesIO()
    try:
        result = pisa.CreatePDF(src=html, dest=buf, encoding="utf-8")
    except Exception as exc:
        logger.error("PDF render error: {}", exc)
        return None
    if result.err:
        logger.warning("PDF render reported {} error(s)", result.err)
    data = buf.getvalue()
    return data if data[:5] == b"%PDF-" else None
