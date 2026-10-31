import re

from .base import Segment

PDF_CHUNK = 900
PDF_OVERLAP = 150
VIDEO_WINDOW_S = 50
VIDEO_MAX_CHARS = 700


def chunk_pdf(segments: list[Segment]) -> list[Segment]:
    """Split each page into overlapping chunks at sentence boundaries; page numbers are preserved."""
    out: list[Segment] = []
    for seg in segments:
        sents = [s.strip() for s in re.split(r"(?<=[.!?:])\s+|\n{2,}", re.sub(r"[ \t]*\n(?!\n)", " ", seg.text)) if s.strip()]
        cur = ""
        for s in sents:
            if cur and len(cur) + len(s) + 1 > PDF_CHUNK:
                out.append(Segment(text=cur, page=seg.page, heading=seg.heading))
                cur = cur[-PDF_OVERLAP:].split(" ", 1)[-1] if PDF_OVERLAP else ""
            cur = f"{cur} {s}".strip()
        if cur:
            out.append(Segment(text=cur, page=seg.page, heading=seg.heading))
    return out


def chunk_transcript(segments: list[Segment]) -> list[Segment]:
    """Group caption lines into ~50s windows with one-line overlap; each chunk keeps start/end seconds."""
    out: list[Segment] = []
    buf: list[Segment] = []
    for s in segments:
        buf.append(s)
        span = buf[-1].end - buf[0].start
        if span >= VIDEO_WINDOW_S or sum(len(b.text) + 1 for b in buf) >= VIDEO_MAX_CHARS:
            out.append(Segment(text=" ".join(b.text for b in buf), start=buf[0].start, end=buf[-1].end))
            buf = buf[-1:]
    if len(buf) > 1 or (buf and not out):
        out.append(Segment(text=" ".join(b.text for b in buf), start=buf[0].start, end=buf[-1].end))
    return out
