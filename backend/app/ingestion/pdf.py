import re
import statistics
from pathlib import Path

import pymupdf  # PyMuPDF

from ..config import get_settings
from .base import IngestError, Segment

_BULLETS = "•●▪◦○o•"


def validate_pdf_bytes(data: bytes, filename: str) -> None:
    if not filename.lower().endswith(".pdf"):
        raise IngestError("Only .pdf files are accepted.")
    if len(data) == 0:
        raise IngestError("The uploaded file is empty.")
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise IngestError(f"File exceeds the {get_settings().max_upload_mb} MB limit.")
    if not data.startswith(b"%PDF"):
        raise IngestError("File content is not a valid PDF (missing %PDF header).")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as d:
            if d.page_count == 0:
                raise IngestError("The PDF has no pages.")
    except IngestError:
        raise
    except Exception as e:
        raise IngestError(f"The PDF could not be opened: {e}") from e


def pdf_stats(path: str) -> dict:
    with pymupdf.open(path) as d:
        return {"pages": d.page_count, "images": sum(len(p.get_images()) for p in d)}


def _norm(line: str) -> str:
    return re.sub(r"\d+", "#", line.lower()).strip()


class PdfConnector:
    """Extracts text per page with section headings and tables, preserving page numbers.
    Repeated running headers/footers are dropped; embedded images are NOT text-extracted (no OCR)."""

    def extract(self, resource: dict) -> list[Segment]:
        path = resource.get("file_path")
        if not path or not Path(path).exists():
            raise IngestError("PDF file is missing on disk.")
        try:
            with pymupdf.open(path) as doc:
                pages = [self._page_items(p) for p in doc]
        except Exception as e:
            raise IngestError(f"PDF text extraction failed: {e}") from e
        # drop running headers/footers: short lines whose digit-normalised form repeats on many pages
        counts: dict[str, int] = {}
        for items in pages:
            for key in {_norm(t) for _, t, _, _k in items}:
                counts[key] = counts.get(key, 0) + 1
        threshold = max(3, int(0.4 * len(pages)))
        boiler = {k for k, n in counts.items() if n >= threshold}
        segs: list[Segment] = []
        heading: str | None = None
        for pno, items in enumerate(pages, 1):
            body: list[str] = []
            sec_heading = heading

            def flush():
                text = "\n".join(body).strip()
                if len(text) > 20:
                    segs.append(Segment(text=text, page=pno, heading=sec_heading))
                body.clear()

            for _, text, is_heading, kind in items:
                if len(text) < 90 and _norm(text) in boiler:
                    continue
                if is_heading and kind == "line":
                    if body and len("\n".join(body)) > 40:  # close the previous section on this page
                        flush()
                    heading = sec_heading = text
                body.append(text)
            flush()
        if not segs:
            raise IngestError("No extractable text found (the PDF may be scanned images; OCR is not supported).")
        return segs

    @staticmethod
    def _page_items(page) -> list[tuple[float, str, bool, str]]:
        try:
            tables = page.find_tables().tables
        except Exception:
            tables = []
        tboxes = [pymupdf.Rect(t.bbox) for t in tables]
        d = page.get_text("dict")
        sizes = [s["size"] for b in d["blocks"] if b["type"] == 0 for l in b["lines"] for s in l["spans"] for _ in s["text"].strip()]
        body_size = statistics.median(sizes) if sizes else 10
        items: list[tuple[float, str, bool, str]] = []
        for b in d["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                r = pymupdf.Rect(l["bbox"])
                if r.get_area() and any((r & tb).get_area() > 0.5 * r.get_area() for tb in tboxes):
                    continue  # rendered as a table row below
                spans = [s for s in l["spans"] if s["text"].strip()]
                text = re.sub(r"\s{2,}", " ", "".join(s["text"] for s in l["spans"])).strip().lstrip(_BULLETS + " ").strip()
                if not spans or not text:
                    continue
                bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                big = max(s["size"] for s in spans) > body_size * 1.15
                is_heading = (bold or big) and len(text) <= 90 and not text.endswith((",", ";")) and len(text) > 2
                items.append((l["bbox"][1], text, is_heading, "line"))
        for t in tables:
            for row in t.rows:
                cells = [re.sub(r"\s+", " ", page.get_text("text", clip=pymupdf.Rect(c))).strip() for c in row.cells if c]
                cells = [c for c in cells if c]
                if cells:
                    items.append((row.bbox[1], " | ".join(cells), False, "table"))
        items.sort(key=lambda x: x[0])
        return items
