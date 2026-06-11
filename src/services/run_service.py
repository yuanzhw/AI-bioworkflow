"""Run lifecycle service for persistent workflow API runs."""

from __future__ import annotations

import time
from typing import Iterator
from uuid import uuid4

from src.api.models import (
    CompileWorkflowRequest,
    DiagnosticReport,
    NaturalLanguageRunRequest,
    RunAcceptedResponse,
    RunEvent,
    RunEventType,
    RunStatus,
    WorkflowArtifacts,
    WorkflowRunSnapshotResponse,
)
from src.nl_planner import DEFAULT_PLANNER_MODEL, NaturalLanguagePlanningError, create_natural_language_plan
from src.services import workflow_service
from src.services.run_repository import RunRepository
from src.services.workflow_service import WorkflowCompilationResult


NATURAL_LANGUAGE_RUN_KIND = "natural_language"
STRUCTURED_COMPILE_RUN_KIND = "structured_compile"
DEFAULT_SSE_POLL_INTERVAL_SECONDS = 0.25


class RunService:
    """Create, execute, and read persistent workflow runs."""

    def __init__(self, repository: RunRepository | None = None):
        self.repository = repository or RunRepository()

    def create_natural_language_run(self, request: NaturalLanguageRunRequest) -> RunAcceptedResponse:
        run_id = _new_run_id()
        events_url = _events_url(run_id)
        self.repository.create_run(
            run_id=run_id,
            kind=NATURAL_LANGUAGE_RUN_KIND,
            request=request.request,
            check_performed=request.check,
            events_url=events_url,
            planner_model=request.planner_model or DEFAULT_PLANNER_MODEL,
        )
        self.repository.append_event(
            run_id=run_id,
            event_type=RunEventType.RUN_CREATED,
            summary="Natural-language workflow run created.",
            payload={"kind": NATURAL_LANGUAGE_RUN_KIND},
        )
        return RunAcceptedResponse(run_id=run_id, status=RunStatus.CREATED, events_url=events_url)

    def create_structured_compile_run(self, request: CompileWorkflowRequest) -> RunAcceptedResponse:
        run_id = _new_run_id()
        events_url = _events_url(run_id)
        self.repository.create_run(
            run_id=run_id,
            kind=STRUCTURED_COMPILE_RUN_KIND,
            request=request.payload,
            check_performed=request.check,
            events_url=events_url,
        )
        self.repository.append_event(
            run_id=run_id,
            event_type=RunEventType.RUN_CREATED,
            summary="Structured compile run created.",
            payload={"kind": STRUCTURED_COMPILE_RUN_KIND},
        )
        return RunAcceptedResponse(run_id=run_id, status=RunStatus.CREATED, events_url=events_url)

    def execute_natural_language_run(self, run_id: str, request: NaturalLanguageRunRequest) -> None:
        self.repository.update_status(run_id, RunStatus.RUNNING)
        planner_model = request.planner_model or DEFAULT_PLANNER_MODEL
        self.repository.append_event(
            run_id=run_id,
            event_type=RunEventType.NODE_STARTED,
            node="planner",
            summary="Natural-language planner started.",
            payload={"model": planner_model},
        )

        try:
            plan_result = create_natural_language_plan(request.request, model=planner_model)
        except NaturalLanguagePlanningError as exc:
            self.repository.append_event(
                run_id=run_id,
                event_type=RunEventType.NODE_FAILED,
                node="planner",
                summary="Natural-language planner failed.",
                payload={"error": str(exc)},
            )
            self._fail_run(run_id, str(exc), check_performed=request.check)
            return
        except Exception as exc:
            self.repository.append_event(
                run_id=run_id,
                event_type=RunEventType.NODE_FAILED,
                node="planner",
                summary="Natural-language planner failed unexpectedly.",
                payload={"error": str(exc)},
            )
            self._fail_run(run_id, str(exc), check_performed=request.check)
            return

        self.repository.append_event(
            run_id=run_id,
            event_type=RunEventType.NODE_COMPLETED,
            node="planner",
            summary="Natural-language planner completed.",
            payload={"model": planner_model},
        )
        self.repository.save_artifacts(
            run_id,
            WorkflowArtifacts(plan=plan_result.plan),
            planner_prompt=plan_result.planner_prompt,
            planner_raw_response=plan_result.raw_response,
        )
        self.repository.append_event(
            run_id=run_id,
            event_type=RunEventType.ARTIFACT_UPDATED,
            node="planner",
            summary="Recipe Tool Plan artifact updated.",
            payload={"artifact": "plan"},
        )

        try:
            result = workflow_service.compile_structured_workflow(
                plan_result.plan,
                check=request.check,
                event_callback=self._compiler_event_callback(run_id),
            )
        except Exception as exc:
            self._fail_run(run_id, str(exc), check_performed=request.check)
            return

        self._complete_run(
            run_id,
            result,
            planner_prompt=plan_result.planner_prompt,
            planner_raw_response=plan_result.raw_response,
        )

    def execute_structured_compile_run(self, run_id: str, request: CompileWorkflowRequest) -> None:
        self.repository.update_status(run_id, RunStatus.RUNNING)
        try:
            result = workflow_service.compile_structured_workflow(
                request.payload,
                check=request.check,
                event_callback=self._compiler_event_callback(run_id),
            )
        except Exception as exc:
            self._fail_run(run_id, str(exc), check_performed=request.check)
            return

        self._complete_run(run_id, result)

    def get_snapshot(self, run_id: str) -> WorkflowRunSnapshotResponse | None:
        snapshot = self.repository.get_snapshot(run_id)
        if snapshot is None:
            return None
        return WorkflowRunSnapshotResponse(
            run_id=snapshot.run.run_id,
            status=snapshot.run.status,
            request=snapshot.run.request,
            events_url=snapshot.run.events_url,
            artifacts=snapshot.artifacts,
            diagnostics=snapshot.diagnostics,
        )

    def get_events(self, run_id: str, after_sequence: int = 0) -> list[RunEvent] | None:
        if self.repository.get_run(run_id) is None:
            return None
        return self.repository.list_events(run_id, after_sequence=after_sequence)

    def iter_sse_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        poll_interval: float = DEFAULT_SSE_POLL_INTERVAL_SECONDS,
    ) -> Iterator[str]:
        if self.repository.get_run(run_id) is None:
            raise KeyError(f"unknown run: {run_id}")

        sequence = after_sequence
        while True:
            events = self.repository.list_events(run_id, after_sequence=sequence)
            for event in events:
                sequence = event.sequence
                yield _format_sse_event(event)
                if event.type == RunEventType.RUN_COMPLETED:
                    return

            run = self.repository.get_run(run_id)
            if run is None:
                return
            if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
                return
            time.sleep(poll_interval)

    def _complete_run(
        self,
        run_id: str,
        result: WorkflowCompilationResult,
        *,
        planner_prompt: str | None = None,
        planner_raw_response: str | None = None,
    ) -> None:
        self.repository.save_artifacts(
            run_id,
            WorkflowArtifacts(
                plan=result.plan,
                workflow_ir=result.workflow_ir,
                wdl=result.wdl,
            ),
            planner_prompt=planner_prompt or result.planner_prompt,
            planner_raw_response=planner_raw_response or result.planner_raw_response,
        )
        self.repository.save_diagnostics(
            run_id,
            DiagnosticReport(
                analysis_errors=result.analysis_errors,
                analysis_warnings=result.analysis_warnings,
                repair_actions=result.repair_actions,
                validation_message=result.validation_message,
                is_valid=result.is_valid,
                succeeded=result.succeeded,
                check_performed=result.check_performed,
            ),
        )
        final_status = RunStatus.SUCCEEDED if result.succeeded else RunStatus.FAILED
        self.repository.update_status(run_id, final_status)
        self.repository.append_event(
            run_id=run_id,
            event_type=RunEventType.RUN_COMPLETED,
            summary=f"Run {final_status.value}.",
            payload={"status": final_status.value},
        )

    def _fail_run(self, run_id: str, message: str, *, check_performed: bool) -> None:
        self.repository.save_artifacts(run_id, WorkflowArtifacts())
        self.repository.save_diagnostics(
            run_id,
            DiagnosticReport(
                analysis_errors=[message],
                validation_message=message,
                succeeded=False,
                check_performed=check_performed,
            ),
        )
        self.repository.update_status(run_id, RunStatus.FAILED)
        self.repository.append_event(
            run_id=run_id,
            event_type=RunEventType.RUN_COMPLETED,
            summary="Run failed.",
            payload={"status": RunStatus.FAILED.value, "error": message},
        )

    def _compiler_event_callback(self, run_id: str):
        def callback(event_type: str, node: str | None, summary: str, _state, payload):
            self.repository.append_event(
                run_id=run_id,
                event_type=RunEventType(event_type),
                node=node,
                summary=summary,
                payload=payload,
            )

        return callback


_default_run_service: RunService | None = None


def get_default_run_service() -> RunService:
    global _default_run_service
    if _default_run_service is None:
        _default_run_service = RunService()
    return _default_run_service


def set_default_run_service(service: RunService | None) -> None:
    global _default_run_service
    _default_run_service = service


def create_natural_language_run(request: NaturalLanguageRunRequest) -> RunAcceptedResponse:
    return get_default_run_service().create_natural_language_run(request)


def create_structured_compile_run(request: CompileWorkflowRequest) -> RunAcceptedResponse:
    return get_default_run_service().create_structured_compile_run(request)


def execute_natural_language_run(run_id: str, request: NaturalLanguageRunRequest) -> None:
    get_default_run_service().execute_natural_language_run(run_id, request)


def execute_structured_compile_run(run_id: str, request: CompileWorkflowRequest) -> None:
    get_default_run_service().execute_structured_compile_run(run_id, request)


def get_snapshot(run_id: str) -> WorkflowRunSnapshotResponse | None:
    return get_default_run_service().get_snapshot(run_id)


def get_events(run_id: str, after_sequence: int = 0) -> list[RunEvent] | None:
    return get_default_run_service().get_events(run_id, after_sequence=after_sequence)


def iter_sse_events(run_id: str, after_sequence: int = 0) -> Iterator[str]:
    return get_default_run_service().iter_sse_events(run_id, after_sequence=after_sequence)


def _new_run_id() -> str:
    return f"run_{uuid4().hex[:12]}"


def _events_url(run_id: str) -> str:
    return f"/api/runs/{run_id}/events"


def _format_sse_event(event: RunEvent) -> str:
    return f"id: {event.sequence}\nevent: {event.type.value}\ndata: {event.model_dump_json()}\n\n"
