import pytest

from app.config import BACKEND_DIR
from app.ingestion.chunking import chunk_pdf
from app.ingestion.pdf import PdfConnector

PM = BACKEND_DIR / "seed" / "pdfs" / "Process-Management.pdf"
pytestmark = pytest.mark.skipif(not PM.exists(), reason="local seed PDFs not present (they are git-ignored)")


def test_real_pdf_extraction_pages_headings_tables_no_running_header():
    segs = PdfConnector().extract({"file_path": str(PM)})
    assert {s.page for s in segs} == set(range(1, 13))
    assert not any("Operating System Handout" in s.text or "Kukre" in s.text for s in segs)  # running header/footer removed
    p2 = " ".join(s.text for s in segs if s.page == 2)
    assert "Start:" in p2 and "Terminated or Exit" in p2 and " | " in p2  # table rows kept, with spaces intact
    assert any(s.heading and "Process States" in s.heading for s in segs)
    chunks = chunk_pdf(segs)
    assert all(c.page and c.text for c in chunks) and len(chunks) >= 30
