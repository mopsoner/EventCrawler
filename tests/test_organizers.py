import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

import app
from crawler import extract_contact_info, extract_jsonld_event, jsonld_event_fields


class OrganizerListTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db = app.DB_PATH
        app.DB_PATH = str(Path(self.tempdir.name) / "events.sqlite")
        app.init_db()

    def tearDown(self):
        app.DB_PATH = self.previous_db
        self.tempdir.cleanup()

    def add_event(self, name, organizer_name, phone):
        connection = app.conn()
        connection.execute(
            "INSERT INTO events(event_url, name, organizer_name, contact_phone) VALUES (?, ?, ?, ?)",
            (f"https://www.bizouk.com/events/{name}", name, organizer_name, phone),
        )
        connection.commit()
        connection.close()

    def test_saik_organizer_name_is_displayed_and_phone_remains_contact_only(self):
        html = (Path(__file__).parent / "fixtures" / "bizouk_saik_concert_live_130491.html").read_text()
        soup = BeautifulSoup(html, "html.parser")
        fields = jsonld_event_fields(extract_jsonld_event(soup))
        contact = extract_contact_info(
            soup, [line.strip() for line in soup.get_text("\n", strip=True).splitlines()]
        )
        self.add_event("saik-concert-live/130491", fields["organizer_name"], contact["contact_phone"])

        rows = app.list_organizers()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["organizer_name"], "LBTM")
        self.assertEqual(rows[0]["contact_phone"], "590690123456")
        self.assertNotEqual(rows[0]["organizer_name"], rows[0]["contact_phone"])

    def test_distinct_named_organizers_with_same_phone_are_not_merged(self):
        self.add_event("event-a", "LBTM", "0690 12 34 56")
        self.add_event("event-b", "Another Team", "0690 12 34 56")

        rows = app.list_organizers()

        self.assertEqual({row["organizer_name"] for row in rows}, {"LBTM", "Another Team"})
        self.assertEqual([row["events_count"] for row in rows], [1, 1])


if __name__ == "__main__":
    unittest.main()
