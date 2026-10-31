from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import content, db
from ..deps import tenant
from ..ingestion.base import IngestError
from ..ingestion.pipeline import attach_transcript, index_resource
from ..ingestion.transcript import fetch_youtube_captions, parse_transcript

router = APIRouter(prefix="/api/v1", tags=["content"])


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class TopicIn(BaseModel):
    subject_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    sample_questions: list[str] = Field(default_factory=list, max_length=10)


class VideoIn(BaseModel):
    subject_id: str
    topic_id: str
    url: str
    title: str | None = Field(default=None, max_length=200)
    duration_s: float | None = Field(default=None, gt=0)


class SegmentIn(BaseModel):
    title: str
    start: float
    end: float
    explanation: str
    topic: str = ""
    subtopic: str = ""
    keywords: list[str] = []
    questions: list[str] = []
    transcript_text: str = ""
    verification_status: str = "unverified"


class TranscriptIn(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    origin: str = "manual"


def _wrap(fn, *a, **k):
    try:
        return fn(*a, **k)
    except IngestError as e:
        raise HTTPException(422, str(e))


def _own(tenant_id: str, rid: str) -> dict:
    r = db.row("SELECT * FROM resources WHERE id=? AND tenant_id=?", (rid, tenant_id))
    if not r:
        raise HTTPException(404, "Resource not found.")
    return r


@router.get("/catalog")
def catalog(t: str = Depends(tenant)):
    return content.catalog(t)


@router.post("/subjects")
def add_subject(body: SubjectIn, t: str = Depends(tenant)):
    return content.create_subject(t, body.name, body.description)


@router.post("/topics")
def add_topic(body: TopicIn, t: str = Depends(tenant)):
    return _wrap(content.create_topic, t, body.subject_id, body.name, body.description, body.sample_questions)


@router.get("/resources")
def resources(topic_id: str | None = None, t: str = Depends(tenant)):
    return content.list_resources(t, topic_id)


@router.post("/resources/pdf")
async def upload_pdf(bg: BackgroundTasks, file: UploadFile = File(...), subject_id: str = Form(...), topic_id: str = Form(...),
                     title: str = Form(""), t: str = Depends(tenant)):
    data = await file.read()
    r = _wrap(content.create_pdf_resource, t, subject_id, topic_id, title.strip() or file.filename or "Untitled PDF", data, file.filename or "")
    bg.add_task(index_resource, r["id"])
    return content.public_resource(r)


@router.post("/resources/video")
def add_video(body: VideoIn, t: str = Depends(tenant)):
    return content.public_resource(_wrap(content.create_video_resource, t, body.subject_id, body.topic_id, body.url, body.title, duration_s=body.duration_s))


@router.post("/resources/{rid}/transcript")
def set_transcript(rid: str, body: TranscriptIn, bg: BackgroundTasks, t: str = Depends(tenant)):
    _own(t, rid)
    segs = _wrap(parse_transcript, body.text)
    return content.public_resource(_wrap(attach_transcript, rid, segs, "manual" if body.origin != "uploaded" else "uploaded"))


@router.post("/resources/{rid}/transcript/file")
async def upload_transcript(rid: str, file: UploadFile = File(...), t: str = Depends(tenant)):
    _own(t, rid)
    raw = (await file.read()).decode("utf-8", errors="replace")
    return content.public_resource(_wrap(attach_transcript, rid, _wrap(parse_transcript, raw), "uploaded"))


@router.post("/resources/{rid}/transcript/fetch")
def fetch_transcript(rid: str, t: str = Depends(tenant)):
    r = _own(t, rid)
    if r["type"] != "video":
        raise HTTPException(422, "Only videos have transcripts.")
    try:
        segs = fetch_youtube_captions(r["youtube_id"])
    except IngestError as e:  # honest failure: nothing is marked as extracted
        db.execute("UPDATE resources SET status='no_transcript', status_detail=? WHERE id=?", (str(e), rid))
        return content.public_resource(_own(t, rid))
    return content.public_resource(_wrap(attach_transcript, rid, segs, "extracted"))


@router.post("/resources/{rid}/reindex")
def reindex(rid: str, t: str = Depends(tenant)):
    _own(t, rid)
    return content.public_resource(_wrap(index_resource, rid, True))


@router.get("/resources/{rid}/file")
def pdf_file(rid: str, t: str = Depends(tenant)):
    r = _own(t, rid)
    if r["type"] != "pdf":
        raise HTTPException(404, "No file for this resource.")
    return FileResponse(r["file_path"], media_type="application/pdf", filename=None, headers={"Content-Disposition": "inline"})


@router.post("/resources/{rid}/segments", summary="Import timestamped segment metadata (idempotent upsert; re-import never duplicates)")
def import_segs(rid: str, body: list[SegmentIn], t: str = Depends(tenant)):
    from ..ingestion.segments import import_segments
    _own(t, rid)
    return _wrap(import_segments, t, rid, [s.model_dump() for s in body])


@router.get("/resources/{rid}/segments")
def list_segs(rid: str, t: str = Depends(tenant)):
    _own(t, rid)
    return [dict(s, keywords=db.loads(s["keywords"], []), questions=db.loads(s["questions"], [])) for s in
            db.rows("SELECT id,title,topic,subtopic,start_s,end_s,explanation,keywords,questions,verification FROM video_segments WHERE resource_id=? AND tenant_id=? ORDER BY start_s", (rid, t))]
