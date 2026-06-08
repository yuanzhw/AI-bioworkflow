"""Workflow API routes."""

from fastapi import APIRouter, HTTPException

from src.api.models import (
    CompilationResultResponse,
    CompileWorkflowRequest,
    NaturalLanguageRunRequest,
)
from src.nl_planner import DEFAULT_PLANNER_MODEL, NaturalLanguagePlanningError
from src.services.workflow_service import compile_structured_workflow, plan_and_compile_workflow


router = APIRouter(prefix="/api", tags=["workflows"])


@router.post("/compile", response_model=CompilationResultResponse)
def compile_workflow(request: CompileWorkflowRequest) -> CompilationResultResponse:
    result = compile_structured_workflow(request.payload, check=request.check)
    return CompilationResultResponse.from_service_result(result)


@router.post("/runs", response_model=CompilationResultResponse)
def create_workflow_run(request: NaturalLanguageRunRequest) -> CompilationResultResponse:
    try:
        result = plan_and_compile_workflow(
            request.request,
            model=request.planner_model or DEFAULT_PLANNER_MODEL,
            check=request.check,
        )
    except NaturalLanguagePlanningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CompilationResultResponse.from_service_result(result)
