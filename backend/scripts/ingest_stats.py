"""Print ingestion statistics for a tenant (default: configured default tenant)."""
import sys
from app import db, vectorstore
from app.config import get_settings

t = sys.argv[1] if len(sys.argv) > 1 else get_settings().default_tenant_id
res = db.rows("SELECT * FROM resources WHERE tenant_id=? ORDER BY type DESC, id", (t,))
pdfs = [r for r in res if r["type"] == "pdf"]; vids = [r for r in res if r["type"] == "video"]
import pymupdf
pages = sum(pymupdf.open(r["file_path"]).page_count for r in pdfs)
seg = db.row("SELECT COUNT(*) n, SUM(verification='unverified') u FROM video_segments WHERE tenant_id=?", (t,))
col = vectorstore._collection()
def n(**w):
    conds = [{"tenant_id": t}] + [{k: v} for k, v in w.items()]
    return len(col.get(where=conds[0] if len(conds) == 1 else {"$and": conds}, include=[])["ids"])
print(f"tenant={t}\nPDFs={len(pdfs)} pages={pages} pdf_chunks={sum(r['chunk_count'] for r in pdfs)}")
print(f"videos={len(vids)} caption_chunks={sum(r['chunk_count'] for r in vids)} segments={seg['n']} (unverified={seg['u']})")
print(f"vectors total={n()} | pdf={n(source_type='pdf')} video_caption={n(source_type='video', kind='chunk')} video_segment={n(source_type='video', kind='segment')} resolution={n(source_type='resolution')}")
for r in res: print(f"  {r['status']:10} {r['type']:5} {r['id']:48} chunks={r['chunk_count']:<3} {r['filename'] or r['youtube_id'] or ''} | {r['status_detail'][:90]}")
print("placeholder/sample/fixture resources:", [r["id"] for r in res if r["origin"] in ("sample", "fixture")] or "none")
