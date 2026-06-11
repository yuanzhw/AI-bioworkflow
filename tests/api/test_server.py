import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.server import DEFAULT_API_HOST, DEFAULT_API_PORT, get_api_host, get_api_port


class ApiServerConfigTests(unittest.TestCase):
    def test_default_api_port_avoids_cromwell_default_port(self):
        self.assertEqual(DEFAULT_API_HOST, "127.0.0.1")
        self.assertEqual(DEFAULT_API_PORT, 8010)
        self.assertNotEqual(DEFAULT_API_PORT, 8000)

    def test_api_port_can_be_overridden_by_environment(self):
        with patch.dict("os.environ", {"AI_BIOWORKFLOW_API_PORT": "8020"}):
            self.assertEqual(get_api_port(), 8020)

    def test_api_port_rejects_invalid_environment_value(self):
        with patch.dict("os.environ", {"AI_BIOWORKFLOW_API_PORT": "not-a-port"}):
            with self.assertRaisesRegex(ValueError, "must be an integer"):
                get_api_port()

        with patch.dict("os.environ", {"AI_BIOWORKFLOW_API_PORT": "70000"}):
            with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
                get_api_port()

    def test_api_host_can_be_overridden_by_environment(self):
        with patch.dict("os.environ", {"AI_BIOWORKFLOW_API_HOST": "0.0.0.0"}):
            self.assertEqual(get_api_host(), "0.0.0.0")

    def test_root_and_health_endpoints_are_available(self):
        client = TestClient(create_app())

        root = client.get("/")
        health = client.get("/health")

        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json()["status"], "ok")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})

    def test_favicon_request_does_not_log_404(self):
        client = TestClient(create_app())

        response = client.get("/favicon.ico")

        self.assertEqual(response.status_code, 204)


if __name__ == "__main__":
    unittest.main()
