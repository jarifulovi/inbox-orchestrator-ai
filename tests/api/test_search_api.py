import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps.auth import get_current_user
from app.api.deps.account import get_verified_account_id


class SearchApiTests(unittest.TestCase):
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

    def test_search_unauthorized(self):
        """GET /api/emails/search without auth token returns 401."""
        response = self.client.get(f"/api/emails/search?account_id={self.mock_account_id}&q=test")
        self.assertEqual(response.status_code, 401)

    def test_search_missing_query(self):
        """GET /api/emails/search without q query parameter returns 422 Unprocessable Entity."""
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        app.dependency_overrides[get_verified_account_id] = lambda: self.mock_account_id

        response = self.client.get(
            f"/api/emails/search?account_id={self.mock_account_id}",
            headers={"Authorization": "Bearer fake-token"}
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
