"""Fetch real YouTube captions for the videos in seed/os_dataset.json into the git-ignored seed/transcripts/ folder
and verify each video id via oEmbed. Captions are third-party content, so they are not committed."""
import json
from pathlib import Path

import httpx
from youtube_transcript_api import YouTubeTranscriptApi

SEED = Path(__file__).resolve().parent.parent / "seed"
(SEED / "transcripts").mkdir(exist_ok=True)
api = YouTubeTranscriptApi()
for v in json.loads((SEED / "os_dataset.json").read_text())["videos"]:
    vid = v["youtube_id"]
    meta = httpx.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}, timeout=20)
    title = meta.json().get("title") if meta.status_code == 200 else None
    try:
        t = api.fetch(vid, languages=["en"])
        segs = [{"start": round(s.start, 2), "end": round(s.start + s.duration, 2), "text": s.text.replace("\n", " ").strip()} for s in t.snippets]
        (SEED / "transcripts" / f"{vid}.json").write_text(json.dumps(segs, ensure_ascii=False))
        cap = f"captions saved ({len(segs)} lines, last caption ends {segs[-1]['end']:.0f}s)"
    except Exception as e:
        cap = f"NO captions ({type(e).__name__})"
    print(f"{vid} oembed={meta.status_code} title_match={title == v['title'] or (title or '')[:20] == v['title'][:20]} duration_supplied={v.get('duration_s')} | {cap}")
