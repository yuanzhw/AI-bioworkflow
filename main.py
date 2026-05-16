import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Mapping, cast

import yaml
from dotenv import load_dotenv

from src.graph import agent
from src.nodes.analyzer import analyzer_node
from src.nodes.planner import planner_node
from src.nodes.renderer import renderer_node
from src.nodes.repairer import repairer_node
from src.state import WorkflowState


load_dotenv()


DEMO_INPUT: dict[str, Any] = {
    "workflow": {
        "name": "RNASeqPipeline",
        "inputs": {
            "raw_r1": "File",
            "raw_r2": "File",
            "reference": "File",
        },
        "calls": [
            {
                "id": "qc",
                "task": "fastp",
                "inputs": {
                    "r1": "raw_r1",
                    "r2": "raw_r2",
                },
            },
            {
                "id": "align",
                "task": "bwa_mem",
                "inputs": {
                    "r1": "qc.clean_r1",
                    "r2": "qc.clean_r2",
                    "ref": "reference",
                },
            },
        ],
        "outputs": {
            "bam": "align.bam",
        },
    },
    "tasks": {
        "fastp": {
            "inputs": {
                "r1": "File",
                "r2": "File",
            },
            "command": "fastp -i ~{r1} -I ~{r2} -o clean_R1.fq.gz -O clean_R2.fq.gz",
            "outputs": {
                "clean_r1": {
                    "type": "File",
                    "value": "\"clean_R1.fq.gz\"",
                },
                "clean_r2": {
                    "type": "File",
                    "value": "\"clean_R2.fq.gz\"",
                },
            },
            "runtime": {
                "docker": "quay.io/biocontainers/fastp:0.23.2",
                "cpu": 4,
                "memory": "8G",
            },
        },
        "bwa_mem": {
            "inputs": {
                "r1": "File",
                "r2": "File",
                "ref": "File",
            },
            "command": "bwa mem ~{ref} ~{r1} ~{r2} > aligned.sam",
            "outputs": {
                "bam": {
                    "type": "File",
                    "value": "\"aligned.sam\"",
                },
            },
            "runtime": {
                "docker": "quay.io/biocontainers/bwa:0.7.17--hed695b0_7",
                "cpu": 8,
                "memory": "32G",
            },
        },
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile a Workflow IR or Recipe Tool Plan into WDL.",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        help="Path to a JSON/YAML Workflow IR or Recipe Tool Plan. Uses a built-in demo if omitted.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Path where the generated WDL should be written. Prints WDL when omitted.",
    )
    parser.add_argument(
        "--print-ir",
        action="store_true",
        help="Print the normalized Workflow IR after compilation.",
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Skip miniwdl syntax validation after rendering.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Write workflow progress logs to stderr.",
    )
    return parser.parse_args(argv)


def load_workflow_input(path: Path | None) -> dict[str, Any]:
    if path is None:
        return DEMO_INPUT

    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(raw_text)
    else:
        data = json.loads(raw_text)

    if not isinstance(data, dict):
        raise ValueError(f"workflow input must be a JSON/YAML object: {path}")
    return data


def build_initial_state(parsed_json: dict[str, Any]) -> WorkflowState:
    return {
        "parsed_json": parsed_json,
        "workflow_ir": {},
        "analysis_errors": [],
        "analysis_warnings": [],
        "messages": [],
        "current_wdl": "",
        "validation_message": "",
        "error_count": 0,
        "repair_count": 0,
        "repair_actions": [],
        "is_valid": False,
    }


def compile_workflow(parsed_json: dict[str, Any], check: bool = True) -> WorkflowState:
    state = build_initial_state(parsed_json)
    if check:
        return cast(WorkflowState, agent.invoke(state))

    _merge_state(state, planner_node(state))
    if state["analysis_errors"]:
        return state

    _analyze_with_repair(state)
    if state["analysis_errors"]:
        return state

    _merge_state(state, renderer_node(state))
    state["validation_message"] = "WDL syntax validation skipped (--no-check)."
    return state


def write_wdl_output(path: Path, wdl_code: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(wdl_code, encoding="utf-8")


def workflow_succeeded(state: WorkflowState, check: bool) -> bool:
    if state["analysis_errors"]:
        return False
    if not state["current_wdl"]:
        return False
    return state["is_valid"] if check else True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(verbose=args.verbose)
    check = not args.no_check

    try:
        parsed_json = load_workflow_input(args.input)
        final_state = compile_workflow(parsed_json, check=check)
    except Exception as exc:
        print(f"Compilation failed before workflow execution: {exc}", file=sys.stderr)
        return 1

    _print_report(final_state, check=check)

    if args.print_ir and final_state["workflow_ir"]:
        print(json.dumps(final_state["workflow_ir"], indent=2, ensure_ascii=False))

    if not workflow_succeeded(final_state, check=check):
        return 1

    if args.output:
        write_wdl_output(args.output, final_state["current_wdl"])
        print(f"WDL written to {args.output}", file=sys.stderr)
    else:
        print(final_state["current_wdl"])

    return 0


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(message)s",
        stream=sys.stderr,
        force=True,
    )


def _analyze_with_repair(state: WorkflowState) -> None:
    while True:
        _merge_state(state, analyzer_node(state))
        if not state["analysis_errors"]:
            return

        _merge_state(state, repairer_node(state))
        if not state["repair_actions"]:
            return


def _merge_state(state: WorkflowState, update: Mapping[str, Any]) -> None:
    for key, value in update.items():
        if key == "messages":
            state["messages"] = state["messages"] + value
        elif key == "parsed_json":
            state["parsed_json"] = value
        elif key == "workflow_ir":
            state["workflow_ir"] = value
        elif key == "analysis_errors":
            state["analysis_errors"] = value
        elif key == "analysis_warnings":
            state["analysis_warnings"] = value
        elif key == "current_wdl":
            state["current_wdl"] = value
        elif key == "validation_message":
            state["validation_message"] = value
        elif key == "error_count":
            state["error_count"] = value
        elif key == "repair_count":
            state["repair_count"] = value
        elif key == "repair_actions":
            state["repair_actions"] = value
        elif key == "is_valid":
            state["is_valid"] = value


def _print_report(state: WorkflowState, check: bool) -> None:
    for action in state["repair_actions"]:
        print(f"repair: {action}", file=sys.stderr)

    for warning in state["analysis_warnings"]:
        print(f"warning: {warning}", file=sys.stderr)

    for error in state["analysis_errors"]:
        print(f"error: {error}", file=sys.stderr)

    if check and state["validation_message"]:
        print(state["validation_message"], file=sys.stderr)
    elif not check and state["validation_message"]:
        print(state["validation_message"], file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
