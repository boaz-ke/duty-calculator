import tempfile
import unittest
from pathlib import Path

from app import create_app, db


WORKBOOK = Path(__file__).resolve().parent.parent / "New-CRSP---July-2025.xlsx"


class AppIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vdc-test-"))
        self.db_path = self.tmp / "test.sqlite3"
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "SECRET_KEY": "test-secret",
                "ADMIN_USER": "admin",
                "ADMIN_PASSWORD": "admin123",
            }
        )
        self.client = self.app.test_client()

    def test_seed_creates_live_release(self):
        release = db.live_release(str(self.db_path))
        self.assertIsNotNone(release)
        self.assertEqual(release["status"], "live")
        self.assertEqual(len(db.get_tax_blocks(str(self.db_path), release["id"])), 11)

    def test_search_and_calculate(self):
        response = self.client.get("/api/search?q=honda civic")
        self.assertEqual(response.status_code, 200)
        results = response.get_json()["results"]
        self.assertTrue(results)
        payload = {
            "route": "direct",
            "vehicle_type": "passenger",
            "fuel": "petrol",
            "engine_cc": results[0]["engine_cc"] or 1500,
            "yom": 2020,
            "extra_depreciation": 0,
            "crsp": results[0]["crsp"],
        }
        response = self.client.post("/api/calculate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("grand_total", data["result"])
        self.assertGreater(data["result"]["grand_total"], 0)

    def test_search_deduplicates_identical_suggestions(self):
        response = self.client.get("/api/search?q=suzuki")
        self.assertEqual(response.status_code, 200)
        results = response.get_json()["results"]
        self.assertTrue(results)

        seen = set()
        duplicates = 0
        for row in results:
            key = (row["display"], row["spec"], row["crsp"])
            if key in seen:
                duplicates += 1
            seen.add(key)
        self.assertEqual(duplicates, 0)

        # Config variants (e.g. 2WD vs 4WD) stay as separate, labelled options.
        variants = self.client.get("/api/search?q=suzuki alto hybrid x").get_json()["results"]
        variant_specs = {
            row["spec"]
            for row in variants
            if row["display"] == "SUZUKI ALTO HYBRID X (5AA-HA97S/ABXB)"
        }
        self.assertGreaterEqual(len(variant_specs), 2)
        self.assertTrue(any("2WD" in spec for spec in variant_specs))
        self.assertTrue(any("4WD" in spec for spec in variant_specs))

        # Same-looking suggestions with genuinely different prices must survive.
        priced = self.client.get("/api/search?q=suzuki address v50").get_json()["results"]
        prices = {round(row["crsp"], 2) for row in priced}
        self.assertEqual(len(prices), len(priced))
        self.assertGreaterEqual(len(prices), 2)

    def test_index_loads_calculator_javascript(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"calculator.js", response.data)

    def test_public_page_has_no_admin_link(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"nav-cta", response.data)
        self.assertNotIn(b"Admin console", response.data)

    def test_admin_path_is_configurable(self):
        other = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "SECRET_KEY": "test-secret",
                "ADMIN_USER": "admin",
                "ADMIN_PASSWORD": "admin123",
                "ADMIN_PATH": "ops-console",
            }
        )
        client = other.test_client()
        self.assertEqual(client.get("/ops-console/login").status_code, 200)
        self.assertEqual(client.get("/admin/login").status_code, 404)

    def test_admin_login_is_locked_after_three_failures(self):
        wrong = {"username": "admin", "password": "wrong-password"}
        for attempt in range(3):
            response = self.client.post(
                "/admin/login", data=wrong, environ_base={"REMOTE_ADDR": "203.0.113.7"}
            )
            self.assertEqual(response.status_code, 200)
            if attempt < 2:
                self.assertIn(b"Invalid credentials", response.data)
            else:
                self.assertIn(b"locked for 30 minutes", response.data)

        blocked = self.client.post(
            "/admin/login",
            data={"username": "admin", "password": "admin123"},
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertIn(b"Too many failed sign-in attempts", blocked.data)

        allowed = self.client.post(
            "/admin/login",
            data={"username": "admin", "password": "admin123"},
            environ_base={"REMOTE_ADDR": "198.51.100.9"},
        )
        self.assertEqual(allowed.status_code, 302)

        counts = db.count_login_events(str(self.db_path))
        self.assertEqual(counts["failure"], 3)
        self.assertEqual(counts["lockout"], 1)
        self.assertEqual(counts["blocked"], 1)
        self.assertEqual(counts["success"], 1)

    def test_x_real_ip_is_used_when_trusted(self):
        trusted = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(self.db_path),
                "SECRET_KEY": "test-secret",
                "ADMIN_USER": "admin",
                "ADMIN_PASSWORD": "admin123",
                "TRUST_X_REAL_IP": True,
            }
        )
        client = trusted.test_client()
        wrong = {"username": "admin", "password": "wrong-password"}
        for attempt in range(3):
            response = client.post(
                "/admin/login",
                data=wrong,
                environ_base={"REMOTE_ADDR": "10.0.0.10"},
                headers={"X-Real-IP": "203.0.113.77"},
            )
            if attempt < 2:
                self.assertIn(b"Invalid credentials", response.data)
            else:
                self.assertIn(b"locked for 30 minutes", response.data)

        # A different socket IP with the same forwarded header must stay locked.
        blocked = client.post(
            "/admin/login",
            data={"username": "admin", "password": "admin123"},
            environ_base={"REMOTE_ADDR": "10.0.0.11"},
            headers={"X-Real-IP": "203.0.113.77"},
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertIn(b"Too many failed sign-in attempts", blocked.data)

        allowed = client.post(
            "/admin/login",
            data={"username": "admin", "password": "admin123"},
            environ_base={"REMOTE_ADDR": "10.0.0.12"},
            headers={"X-Real-IP": "198.51.100.4"},
        )
        self.assertEqual(allowed.status_code, 302)
        events = db.list_login_events(str(self.db_path), event_type="success", limit=1)
        self.assertEqual(events[0]["ip"], "198.51.100.4")

    def test_admin_activity_page(self):
        response = self.client.get("/admin/activity")
        self.assertEqual(response.status_code, 302)
        self.client.post("/admin/login", data={"username": "admin", "password": "admin123"})

        response = self.client.get("/admin/activity")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sign-in activity", response.data)
        self.assertIn(b"Successful logins", response.data)

    def test_admin_login_and_upload(self):
        login = self.client.post(
            "/admin/login", data={"username": "admin", "password": "admin123"}
        )
        self.assertEqual(login.status_code, 302)
        with open(WORKBOOK, "rb") as handle:
            upload = self.client.post(
                "/admin/upload",
                data={"file": (handle, WORKBOOK.name)},
                content_type="multipart/form-data",
            )
        self.assertEqual(upload.status_code, 302)
        releases = db.list_releases(str(self.db_path))
        self.assertGreaterEqual(len(releases), 2)
        drafts = [r for r in releases if r["status"] == "draft"]
        self.assertTrue(drafts)

    def test_admin_can_change_password(self):
        self.client.post("/admin/login", data={"username": "admin", "password": "admin123"})
        response = self.client.post(
            "/admin/password",
            data={
                "current_password": "admin123",
                "new_password": "new-secure-pass",
                "confirm_password": "new-secure-pass",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password updated", response.data)
        self.assertFalse(db.verify_admin_password(str(self.db_path), "admin", "admin123"))
        self.assertTrue(db.verify_admin_password(str(self.db_path), "admin", "new-secure-pass"))


if __name__ == "__main__":
    unittest.main()
