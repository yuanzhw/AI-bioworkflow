import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from src.execution.cromwell import CromwellBackend


class FakeResponse:
    def __init__(self, payload=None, *, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if text is None and payload is not None else (text or "")
        self.content = self.text.encode("utf-8")

    def json(self):
        if self._payload is not None:
            return self._payload
        return json.loads(self.text)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, *, headers=None, timeout=None):
        return self._request("GET", url, headers=headers, timeout=timeout)

    def post(self, url, *, files=None, headers=None, timeout=None):
        return self._request("POST", url, files=files, headers=headers, timeout=timeout)

    def _request(self, method, url, *, files=None, headers=None, timeout=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "files": _snapshot_files(files or {}),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError(f"Unexpected HTTP request: {method} {url}")

        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CromwellBackendAvailabilityTests(unittest.TestCase):
    def test_availability_calls_engine_status(self):
        session = FakeSession([_json_response({"ok": True})])
        backend = CromwellBackend(base_url="http://cromwell.test", session=session)

        availability = backend.availability()

        self.assertTrue(availability.available)
        self.assertEqual(session.requests[0]["method"], "GET")
        self.assertEqual(_path(session.requests[0]), "/engine/v1/status")

    def test_availability_rejects_invalid_json(self):
        session = FakeSession([FakeResponse(status_code=200, text="not-json")])
        backend = CromwellBackend(base_url="http://cromwell.test", session=session)

        availability = backend.availability()

        self.assertFalse(availability.available)
        self.assertIn("not valid JSON", availability.reason)

    def test_availability_exposes_connection_failure_reason(self):
        session = FakeSession([OSError("connection refused")])
        backend = CromwellBackend(base_url="http://cromwell.test", session=session)

        availability = backend.availability()

        self.assertFalse(availability.available)
        self.assertIn("connection refused", availability.reason)


class CromwellBackendRunTests(unittest.TestCase):
    def test_run_does_not_submit_when_availability_check_fails(self):
        session = FakeSession([FakeResponse(status_code=503, text="down")])
        backend = CromwellBackend(base_url="http://cromwell.test", session=session)
        wdl_path, inputs_path = self._workflow_files()

        result = backend.run(wdl_path, inputs_path)

        self.assertFalse(result.succeeded)
        self.assertIn("unavailable", result.message)
        self.assertEqual(len(session.requests), 1)

    def test_submit_uses_current_cromwell_multipart_fields(self):
        session = FakeSession(
            [
                _json_response({"ok": True}),
                _json_response({"id": "wf-123", "status": "Submitted"}),
                _json_response({"id": "wf-123", "status": "Succeeded"}),
                _json_response({"outputs": {}}),
                _json_response({"id": "wf-123", "status": "Succeeded"}),
            ]
        )
        backend = CromwellBackend(
            base_url="http://cromwell.test",
            poll_interval_seconds=0,
            session=session,
        )
        wdl_path, inputs_path = self._workflow_files()
        options_path = self._write_file("options.json", "{}")
        dependencies_path = self._write_file("imports.zip", b"zip-bytes")
        labels_path = self._write_file("labels.json", "{}")

        result = backend.run(
            wdl_path,
            inputs_path,
            options_path=options_path,
            dependencies_path=dependencies_path,
            labels_path=labels_path,
        )

        self.assertTrue(result.succeeded)
        submit_request = session.requests[1]
        self.assertEqual(submit_request["method"], "POST")
        self.assertEqual(_path(submit_request), "/api/workflows/v1")
        self.assertNotIn("Content-Type", submit_request["headers"])
        self.assertEqual(
            set(submit_request["files"]),
            {"workflowSource", "workflowInputs", "workflowOptions", "workflowDependencies", "labels"},
        )
        self.assertNotIn("wdlSource", submit_request["files"])
        self.assertEqual(submit_request["files"]["workflowSource"]["content_type"], "text/plain")
        self.assertEqual(submit_request["files"]["workflowInputs"]["content_type"], "application/json")
        self.assertEqual(submit_request["files"]["workflowDependencies"]["content"], b"zip-bytes")

    def test_polling_handles_submitted_running_succeeded_and_parses_outputs_metadata(self):
        session = FakeSession(
            [
                _json_response({"ok": True}),
                _json_response({"id": "wf-123", "status": "Submitted"}),
                _json_response({"id": "wf-123", "status": "Submitted"}),
                _json_response({"id": "wf-123", "status": "Running"}),
                _json_response({"id": "wf-123", "status": "Succeeded"}),
                _json_response(
                    {
                        "id": "wf-123",
                        "outputs": {
                            "RNASeqDEG.deg_table": "/cromwell/deg.tsv",
                            "RNASeqDEG.multiqc_report": "/cromwell/multiqc.html",
                        },
                    }
                ),
                _json_response({"id": "wf-123", "status": "Succeeded", "calls": {}}),
            ]
        )
        backend = CromwellBackend(
            base_url="http://cromwell.test",
            poll_interval_seconds=0,
            session=session,
        )
        wdl_path, inputs_path = self._workflow_files()

        result = backend.run(wdl_path, inputs_path)

        self.assertTrue(result.succeeded)
        self.assertEqual(result.workflow_id, "wf-123")
        self.assertEqual(result.status, "Succeeded")
        self.assertEqual(result.outputs["RNASeqDEG.deg_table"], "/cromwell/deg.tsv")
        self.assertEqual(result.metadata["status"], "Succeeded")
        self.assertEqual(
            [_path(request) for request in session.requests if _path(request).endswith("/status")],
            [
                "/engine/v1/status",
                "/api/workflows/v1/wf-123/status",
                "/api/workflows/v1/wf-123/status",
                "/api/workflows/v1/wf-123/status",
            ],
        )

    def test_failed_status_returns_failed_result_with_metadata_summary(self):
        session = FakeSession(
            [
                _json_response({"ok": True}),
                _json_response({"id": "wf-123", "status": "Submitted"}),
                _json_response({"id": "wf-123", "status": "Failed"}),
                _json_response({"outputs": {}}),
                _json_response(
                    {
                        "id": "wf-123",
                        "status": "Failed",
                        "failures": [{"message": "task crashed"}],
                    }
                ),
            ]
        )
        backend = CromwellBackend(
            base_url="http://cromwell.test",
            poll_interval_seconds=0,
            session=session,
        )
        wdl_path, inputs_path = self._workflow_files()

        result = backend.run(wdl_path, inputs_path)

        self.assertFalse(result.succeeded)
        self.assertEqual(result.status, "Failed")
        self.assertIn("task crashed", result.message)
        self.assertEqual(result.metadata["failures"][0]["message"], "task crashed")

    def test_aborted_status_returns_failed_result(self):
        session = FakeSession(
            [
                _json_response({"ok": True}),
                _json_response({"id": "wf-123", "status": "Submitted"}),
                _json_response({"id": "wf-123", "status": "Aborted"}),
                _json_response({"outputs": {}}),
                _json_response({"id": "wf-123", "status": "Aborted"}),
            ]
        )
        backend = CromwellBackend(
            base_url="http://cromwell.test",
            poll_interval_seconds=0,
            session=session,
        )
        wdl_path, inputs_path = self._workflow_files()

        result = backend.run(wdl_path, inputs_path)

        self.assertFalse(result.succeeded)
        self.assertEqual(result.status, "Aborted")
        self.assertIn("Aborted", result.message)

    def test_timeout_returns_failed_result_with_clear_message(self):
        session = FakeSession(
            [
                _json_response({"ok": True}),
                _json_response({"id": "wf-123", "status": "Submitted"}),
                _json_response({"id": "wf-123", "status": "Running"}),
                _json_response({"id": "wf-123", "status": "Running"}),
            ]
        )
        backend = CromwellBackend(
            base_url="http://cromwell.test",
            poll_interval_seconds=0,
            timeout_seconds=0,
            session=session,
        )
        wdl_path, inputs_path = self._workflow_files()

        result = backend.run(wdl_path, inputs_path)

        self.assertFalse(result.succeeded)
        self.assertEqual(result.status, "Running")
        self.assertIn("timed out", result.message)
        self.assertEqual(result.metadata["status"], "Running")

    def _workflow_files(self):
        wdl_path = self._write_file("workflow.wdl", "version 1.0\nworkflow Test {}\n")
        inputs_path = self._write_file("inputs.json", "{}")
        return wdl_path, inputs_path

    def _write_file(self, name, content):
        if not hasattr(self, "_temp_dir"):
            self._temp_context = tempfile.TemporaryDirectory()
            self.addCleanup(self._temp_context.cleanup)
            self._temp_dir = Path(self._temp_context.name)

        path = self._temp_dir / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path


def _json_response(payload, status_code=200):
    return FakeResponse(payload, status_code=status_code)


def _snapshot_files(files):
    snapshot = {}
    for field_name, file_tuple in files.items():
        filename, file_obj, content_type = file_tuple
        offset = file_obj.tell()
        content = file_obj.read()
        file_obj.seek(offset)
        snapshot[field_name] = {
            "filename": filename,
            "content": content,
            "content_type": content_type,
        }
    return snapshot


def _path(request):
    return urlparse(request["url"]).path


if __name__ == "__main__":
    unittest.main()
