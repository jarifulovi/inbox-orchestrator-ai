import unittest
from fastapi.testclient import TestClient
from app.main import app


class HealthAndRootApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_root_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("message", data)
        self.assertEqual(data["message"], "Inbox Orchestrator Server is running")

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "InboxOrchestrator AI Engine")

    def test_health_db_endpoint(self):
        response = self.client.get("/health/db")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("supabase", data)
        self.assertIn(data["status"], ["ok", "degraded"])


if __name__ == "__main__":
    unittest.main()
