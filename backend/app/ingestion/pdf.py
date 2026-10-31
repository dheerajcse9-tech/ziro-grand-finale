from pathlib import Path

import fitz  # PyMuPDF

from ..config import get_settings
from .base import IngestError, Segment


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
        with fitz.open(stream=data, filetype="pdf") as d:
            if d.page_count == 0:
                raise IngestError("The PDF has no pages.")
    except IngestError:
        raise
    except Exception as e:
        raise IngestError(f"The PDF could not be opened: {e}") from e


class PdfConnector:
    def extract(self, resource: dict) -> list[Segment]:
        path = resource.get("file_path")
        if not path or not Path(path).exists():
            raise IngestError("PDF file is missing on disk.")
        try:
            with fitz.open(path) as doc:
                segs = [Segment(text=p.get_text("text").strip(), page=i + 1) for i, p in enumerate(doc)]
        except Exception as e:
            raise IngestError(f"PDF text extraction failed: {e}") from e
        segs = [s for s in segs if len(s.text) > 20]
        if not segs:
            raise IngestError("No extractable text found (the PDF may be scanned images; OCR is not supported).")
        return segs
