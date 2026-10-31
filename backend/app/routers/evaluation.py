from fastapi import APIRouter

from ..evaluation import runner

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])


@router.post("/run", summary="Run the evaluation suite against the live agent (background)")
def run():
    return {"started": runner.start_background(), **runner.status()}


@router.get("/status")
def status():
    return runner.status()


@router.get("/latest", summary="Most recent real evaluation run (null if never run)")
def latest():
    return runner.latest()


@router.get("/dataset")
def dataset():
    return runner.dataset()
