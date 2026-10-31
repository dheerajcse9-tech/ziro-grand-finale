"""Timestamped transcript connectors: stored-file reader, text/SRT/VTT/JSON parser, YouTube caption fetcher."""
import json
import re
from pathlib import Path

from .base import IngestError, Segment

_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"


def _secs(h, m, s, ms=None) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + (int(ms.ljust(3, "0")) / 1000 if ms else 0)


def parse_transcript(raw: str) -> list[dict]:
    """Accepts JSON [{start,end|duration,text}], SRT/VTT cues, or lines like '[01:25] text' / '01:25 text'."""
    raw = raw.strip().lstrip("﻿")
    if not raw:
        raise IngestError("Transcript is empty.")
    if raw[0] in "[{":
        try:
            data = json.loads(raw)
            data = data.get("segments", data) if isinstance(data, dict) else data
            segs = []
            for d in data:
                start = float(d["start"])
                end = float(d["end"]) if "end" in d else start + float(d.get("duration", 0))
                segs.append({"start": start, "end": end, "text": str(d["text"]).strip()})
            return _finish(segs)
        except (ValueError, KeyError, TypeError):
            pass  # fall through to text parsing
    segs: list[dict] = []
    cue = re.compile(rf"^{_TS}\s*-->\s*{_TS}", re.M)
    if cue.search(raw):  # SRT / VTT
        for block in re.split(r"\n\s*\n", raw):
            lines = [l for l in block.strip().splitlines() if l.strip()]
            for i, l in enumerate(lines):
                m = cue.match(l)
                if m:
                    g = m.groups()
                    text = " ".join(x for x in lines[i + 1:] if not x.strip().isdigit()).strip()
                    if text:
                        segs.append({"start": _secs(*g[:4]), "end": _secs(*g[4:]), "text": text})
                    break
        return _finish(segs)
    line_re = re.compile(rf"^\[?{_TS}\]?\s*[-–:]?\s*(.+)$")
    for l in raw.splitlines():
        m = line_re.match(l.strip())
        if m:
            g = m.groups()
            segs.append({"start": _secs(*g[:4]), "end": None, "text": g[4].strip()})
    for a, b in zip(segs, segs[1:]):
        a["end"] = b["start"]
    if segs:
        segs[-1]["end"] = segs[-1]["start"] + 10
    return _finish(segs)


def _finish(segs: list[dict]) -> list[dict]:
    segs = [s for s in segs if s["text"]]
    if not segs:
        raise IngestError("No timestamped lines recognised. Use JSON, SRT/VTT, or lines like '[01:25] text'.")
    segs.sort(key=lambda s: s["start"])
    return segs


class StoredTranscriptConnector:
    """Reads the transcript JSON saved for a video resource (file_path)."""
    def extract(self, resource: dict) -> list[Segment]:
        path = resource.get("file_path")
        if not path or not Path(path).exists():
            raise IngestError("No transcript has been attached to this video yet.")
        segs = json.loads(Path(path).read_text())
        return [Segment(text=s["text"], start=s["start"], end=s["end"]) for s in segs]


def fetch_youtube_captions(video_id: str) -> list[dict]:
    """Fetch real captions only if YouTube exposes them; raise IngestError otherwise (never fabricate)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        t = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
        return [{"start": round(s.start, 2), "end": round(s.start + s.duration, 2), "text": s.text.replace("\n", " ").strip()} for s in t.snippets]
    except Exception as e:
        raise IngestError(f"Transcript extraction unavailable for this video ({type(e).__name__}). Upload or paste a timestamped transcript instead.") from e
