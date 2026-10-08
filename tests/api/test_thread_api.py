import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps.auth import get_current_user
from app.api.deps.account import get_verified_account_id


class ThreadApiTests(unittest.TestCase):
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

    def test_list_threads_unauthorized(self):
        """GET /api/emails/threads without auth header returns 401."""
        response = self.client.get(f"/api/emails/threads?account_id={self.mock_account_id}")
        self.assertEqual(response.status_code, 401)

    def test_list_threads_success_with_filters(self):
        """GET /api/emails/threads returns paginated threads list when authenticated."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        response = self.client.get(
            f"/api/emails/threads?account_id={self.mock_account_id}&category=focused&priority=high&status=needs_action&limit=10&offset=0",
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("threads", data)
        self.assertIsInstance(data["threads"], list)

    def test_get_thread_details_not_found(self):
        """GET /api/emails/threads/{thread_id} returns 404 if thread does not exist."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        nonexistent_id = str(uuid4())
        response = self.client.get(
            f"/api/emails/threads/{nonexistent_id}?account_id={self.mock_account_id}",
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_update_thread_status_invalid_payload(self):
        """PATCH /api/emails/threads/{thread_id}/status with invalid status returns 400."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        thread_id = str(uuid4())
        response = self.client.patch(
            f"/api/emails/threads/{thread_id}/status?account_id={self.mock_account_id}",
            json={"workflow_status": "invalid_status_label"},
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
