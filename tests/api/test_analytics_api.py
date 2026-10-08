import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps.auth import get_current_user
from app.api.deps.account import get_verified_account_id


class AnalyticsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.mock_user_id = str(uuid4())
        self.mock_account_id = str(uuid4())

        self.mock_user = {
            "id": self.mock_user_id,
            "email": "test@example.com",
            "role": "authenticated",
            "user_metadata": {}
        }
        app.dependency_overrides.clear()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_senders_analytics_unauthorized(self):
        """GET /api/analytics/senders without auth token returns 401."""
        response = self.client.get(f"/api/analytics/senders?account_id={self.mock_account_id}")
        self.assertEqual(response.status_code, 401)

    def test_system_analytics_unauthorized(self):
        """GET /api/analytics/system without auth token returns 401."""
        response = self.client.get(f"/api/analytics/system?account_id={self.mock_account_id}")
        self.assertEqual(response.status_code, 401)

    def test_senders_analytics_success(self):
        """GET /api/analytics/senders returns sender workload metrics list."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        response = self.client.get(
            f"/api/analytics/senders?account_id={self.mock_account_id}&limit=10",
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertIsInstance(data["results"], list)

    def test_system_analytics_success(self):
        """GET /api/analytics/system returns system performance metrics summary."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        response = self.client.get(
            f"/api/analytics/system?account_id={self.mock_account_id}",
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("summary", data)


if __name__ == "__main__":
    unittest.main()
