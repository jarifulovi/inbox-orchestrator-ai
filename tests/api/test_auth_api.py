import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps.auth import get_current_user


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides.clear()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_get_me_unauthorized(self):
        """GET /api/auth/me without token should return 401 Unauthorized."""
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Missing token", response.json()["detail"])

    def test_get_me_success_with_override(self):
        """GET /api/auth/me with valid mock token returns user profile."""
        mock_user = {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "test@example.com",
            "role": "authenticated",
            "user_metadata": {}
        }
        app.dependency_overrides[get_current_user] = lambda: mock_user

        response = self.client.get("/api/auth/me", headers={"Authorization": "Bearer fake-token"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("user", data)
        self.assertIn("gmail", data)
        self.assertEqual(data["user"]["email"], "test@example.com")

    def test_google_connect_unauthorized(self):
        """GET /api/auth/google/connect without token should return 401."""
        response = self.client.get("/api/auth/google/connect")
        self.assertEqual(response.status_code, 401)

    def test_google_callback_missing_params(self):
        """GET /api/auth/google/callback missing code/state parameters returns 422 Unprocessable Entity."""
        response = self.client.get("/api/auth/google/callback")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
