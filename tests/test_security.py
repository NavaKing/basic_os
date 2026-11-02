"""The local-only protections in app.py: foreign Host and Origin headers are refused, security headers are sent.
Only requests that are refused (or hit a missing file) are made, so no route does any work."""
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
from app import app


class LocalOnly(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_foreign_host_is_refused(self):
        # DNS rebinding: another site's domain pointed at 127.0.0.1
        self.assertEqual(self.client.get("/", headers={"Host": "evil.example"}).status_code, 403)

    def test_foreign_origin_cannot_post(self):
        response = self.client.post("/podcast/generate", headers={"Host": "127.0.0.1:5000", "Origin": "https://evil.example"}, json={})
        self.assertEqual(response.status_code, 403)
        response = self.client.delete("/events/uploads", headers={"Host": "localhost:5000", "Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_local_request_gets_security_headers(self):
        response = self.client.get("/portraits/player/no_such_file.png", headers={"Host": "127.0.0.1:5000"})
        self.assertNotEqual(response.status_code, 403)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertIn("blob:", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_debug_is_off(self):
        self.assertFalse(app.debug)


if __name__ == "__main__":
    unittest.main()
