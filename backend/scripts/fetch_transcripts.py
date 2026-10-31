"""One-off: discover/verify seed videos via yt-dlp + oEmbed and save real YouTube captions as seed transcripts."""
import json, sys
from pathlib import Path
import httpx
from youtube_transcript_api import YouTubeTranscriptApi

SEED = Path(__file__).resolve().parent.parent / "seed"
VIDEOS = [  # (topic_id, youtube_id)
    ("os-process-management", "2dJdHMpCLIg"),
    ("os-cpu-scheduling", "WYo1SpUh9FI"),
    ("os-cpu-scheduling", sys.argv[1] if len(sys.argv) > 1 else None),
    ("os-deadlocks", "rWFH6PLOIEI"),
    ("os-memory-management", "6c-mOFZwP_8"),
]
api, out = YouTubeTranscriptApi(), []
for topic, vid in VIDEOS:
    if not vid:
        continue
    meta = httpx.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}, timeout=20)
    meta.raise_for_status()
    m = meta.json()
    t = api.fetch(vid, languages=["en"])
    segs = [{"start": round(s.start, 2), "end": round(s.start + s.duration, 2), "text": s.text.replace("\n", " ").strip()} for s in t.snippets]
    (SEED / "transcripts" / f"{vid}.json").write_text(json.dumps(segs, ensure_ascii=False))
    out.append({"topic_id": topic, "youtube_id": vid, "title": m["title"], "channel": m["author_name"], "segments": len(segs), "duration_s": segs[-1]["end"]})
    print(out[-1])
(SEED / "videos.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
