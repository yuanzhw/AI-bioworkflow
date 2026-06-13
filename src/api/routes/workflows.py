"""Workflow API routes."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.models import (
    CompileWorkflowRequest,
    NaturalLanguageRunRequest,
    RunAcceptedResponse,
    WorkflowRunSnapshotResponse,
)
from src.services import run_service


router = APIRouter(prefix="/api", tags=["workflows"])


@router.post("/compile", response_model=RunAcceptedResponse, status_code=202)
def compile_workflow(
    request: CompileWorkflowRequest,
    background_tasks: BackgroundTasks,
) -> RunAcceptedResponse:
    accepted = run_service.create_structured_compile_run(request)
    background_tasks.add_task(run_service.execute_structured_compile_run, accepted.run_id, request)
    return accepted


@router.post("/runs", response_model=RunAcceptedResponse, status_code=202)
def create_workflow_run(
    request: NaturalLanguageRunRequest,
    background_tasks: BackgroundTasks,
) -> RunAcceptedResponse:
    accepted = run_service.create_natural_language_run(request)
    background_tasks.add_task(run_service.execute_natural_language_run, accepted.run_id, request)
    return accepted


@router.get("/runs/{run_id}", response_model=WorkflowRunSnapshotResponse)
def get_workflow_run(run_id: str) -> WorkflowRunSnapshotResponse:
    snapshot = run_service.get_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    return snapshot


@router.get("/runs/{run_id}/events")
def stream_workflow_run_events(
    run_id: str,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    try:
        events = run_service.iter_sse_events(run_id, after_sequence=after)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return StreamingResponse(events, media_type="text/event-stream")
