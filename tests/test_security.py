import base64
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "EventCrawler"
sys.path.insert(0, str(APP_DIR))

from security import UnsafeURL, credentials_match, validate_external_url


class URLValidationTests(unittest.TestCase):
    def test_accepts_known_https_source(self):
        self.assertEqual(
            validate_external_url("https://www.bizouk.com/events/1#details", resolve_dns=False),
            "https://www.bizouk.com/events/1",
        )

    def test_rejects_http_credentials_ports_and_unknown_hosts(self):
        rejected = (
            "http://www.bizouk.com/events/1",
            "https://user:pass@www.bizouk.com/events/1",
            "https://www.bizouk.com:444/events/1",
            "https://127.0.0.1/",
            "https://bizouk.com.example.org/",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(UnsafeURL):
                validate_external_url(value, resolve_dns=False)

    @patch("security.socket.getaddrinfo")
    def test_rejects_private_dns_resolution(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with self.assertRaises(UnsafeURL):
            validate_external_url("https://www.bizouk.com/")

    def test_credentials_use_exact_values(self):
        self.assertTrue(credentials_match("admin", "secret", "admin", "secret"))
        self.assertFalse(credentials_match("admin", "wrong", "admin", "secret"))


class WebSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_cwd = Path.cwd()
        cls.tempdir = tempfile.TemporaryDirectory()
        os.chdir(cls.tempdir.name)
        import app as app_module

        cls.module = app_module
        cls.application = app_module.create_app(
            {"TESTING": True, "ADMIN_USERNAME": "tester", "ADMIN_PASSWORD": "secret", "SECRET_KEY": "test-key"}
        )
        cls.client = cls.application.test_client()
        cls.auth = "Basic " + base64.b64encode(b"tester:secret").decode()

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous_cwd)
        cls.tempdir.cleanup()

    def test_authentication_is_required(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 401)

    def test_sensitive_api_is_not_cached_and_config_is_redacted(self):
        response = self.client.get("/api/config", headers={"Authorization": self.auth})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["booking_profile"], {"configured": True})

    def test_logs_page_and_api_are_available_and_not_cached(self):
        Path("data/crawl.log").write_text("worker started\npage failed\n", encoding="utf-8")
        response = self.client.get("/logs", headers={"Authorization": self.auth})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Logs & workers", response.data)
        self.assertIn(b"page failed", response.data)
        api_response = self.client.get("/api/logs", headers={"Authorization": self.auth})
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.headers["Cache-Control"], "no-store")
        self.assertEqual(api_response.json["logs"]["crawl"][-1], "page failed")
        self.assertEqual(len(api_response.json["workers"]), 3)

    def test_database_reads_continue_during_crawler_write(self):
        writer = self.module.conn()
        reader_result = {}
        writer.execute(
            "INSERT OR IGNORE INTO events(event_url, name) VALUES (?, ?)",
            ("https://www.bizouk.com/events/details/concurrent/1", "Concurrent"),
        )

        def read_event_count():
            reader = self.module.conn()
            try:
                reader_result["count"] = reader.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            finally:
                reader.close()

        thread = threading.Thread(target=read_event_count)
        thread.start()
        thread.join(timeout=2)
        writer.rollback()
        writer.close()

        self.assertFalse(thread.is_alive(), "database read waited for an uncommitted crawler write")
        self.assertIn("count", reader_result)

    def test_log_tail_is_bounded(self):
        path = Path("data/bounded.log")
        path.write_text("\n".join(f"line {number}" for number in range(20)), encoding="utf-8")
        self.assertEqual(self.module.tail_log(path, line_limit=3), ["line 17", "line 18", "line 19"])

    def test_post_requires_csrf(self):
        response = self.client.post("/scheduler/start", headers={"Authorization": self.auth})
        self.assertEqual(response.status_code, 403)

    def test_booking_requires_explicit_single_use_approval(self):
        self.client.get("/", headers={"Authorization": self.auth})
        with self.client.session_transaction() as flask_session:
            token = flask_session["csrf_token"]
        headers = {"Authorization": self.auth, "X-CSRF-Token": token}
        payload = {"event_url": "https://www.bizouk.com/events/details/test/1", "product_name": "Billet", "ticket_count": 99}
        connection = self.module.conn()
        connection.execute("INSERT OR IGNORE INTO events(event_url, name) VALUES (?, ?)", (payload["event_url"], "Test"))
        event_id = connection.execute("SELECT id FROM events WHERE event_url=?", (payload["event_url"],)).fetchone()[0]
        connection.execute("INSERT OR IGNORE INTO products(event_id, product_name, price_text, numeric_price, is_free, is_available) VALUES (?, ?, ?, ?, ?, ?)", (event_id, "Billet", "0 EUR", 0, 1, 1))
        connection.commit()
        connection.close()
        with patch.object(self.module, "validate_external_url", return_value=payload["event_url"]):
            prepared = self.client.post("/booking/prepare", json=payload, headers=headers)
        self.assertEqual(prepared.status_code, 200)
        self.assertEqual(prepared.json["status"], "approval_required")
        self.assertEqual(prepared.json["summary"]["ticket_count"], 10)
        with patch.object(self.module, "launch_booking_prepare", return_value=True):
            confirmed = self.client.post("/booking/confirm", json={"approval_token": prepared.json["approval_token"]}, headers=headers)
            replayed = self.client.post("/booking/confirm", json={"approval_token": prepared.json["approval_token"]}, headers=headers)
        self.assertEqual(confirmed.json["status"], "started")
        self.assertEqual(replayed.status_code, 400)

    def test_clear_database_requires_confirmation_and_removes_rows_and_images(self):
        self.client.get("/config", headers={"Authorization": self.auth})
        with self.client.session_transaction() as flask_session:
            token = flask_session["csrf_token"]
        headers = {"Authorization": self.auth, "X-CSRF-Token": token}

        rejected = self.client.post(
            "/config/clear-database", data={"confirmation": "non"}, headers=headers
        )
        self.assertEqual(rejected.status_code, 400)

        connection = self.module.conn()
        connection.execute(
            "INSERT OR IGNORE INTO events(event_url, name) VALUES (?, ?)",
            ("https://www.bizouk.com/events/details/to-delete/99", "À supprimer"),
        )
        connection.commit()
        connection.close()
        image_path = Path("data/booking_screens/test.png")
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"image")
        failure_path = Path("data/booking_failures/test.json")
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        failure_path.write_text("{}", encoding="utf-8")

        response = self.client.post(
            "/config/clear-database", data={"confirmation": "VIDER"}, headers=headers
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("database_cleared=1", response.location)
        connection = self.module.conn()
        for table in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            count = connection.execute(f'SELECT COUNT(*) FROM "{table[0]}"').fetchone()[0]
            self.assertEqual(count, 0, table[0])
        connection.close()
        self.assertFalse(image_path.exists())
        self.assertFalse(failure_path.exists())


if __name__ == "__main__":
    unittest.main()
