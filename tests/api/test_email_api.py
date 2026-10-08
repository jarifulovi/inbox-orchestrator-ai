import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps.auth import get_current_user
from app.api.deps.account import get_verified_account_id


class EmailApiTests(unittest.TestCase):
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

    def test_list_emails_unauthorized(self):
        """GET /api/emails without auth token returns 401."""
        response = self.client.get(f"/api/emails?account_id={self.mock_account_id}")
        self.assertEqual(response.status_code, 401)

    def test_view_email_not_found(self):
        """GET /api/emails/{email_id} returns 404 if email does not exist."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        nonexistent_id = str(uuid4())
        response = self.client.get(
            f"/api/emails/{nonexistent_id}?account_id={self.mock_account_id}",
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Email not found")

    def test_unsubscribe_sender_missing_email(self):
        """POST /api/emails/senders/unsubscribe with empty sender_email returns 400 Bad Request."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        response = self.client.post(
            f"/api/emails/senders/unsubscribe?account_id={self.mock_account_id}",
            json={"sender_email": ""},
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("sender_email is required", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
