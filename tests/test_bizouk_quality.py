import sys
import unittest
from unittest.mock import patch
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "EventCrawler"))

from bizouk_quality import (
    EventValidationError,
    clean_subtitle,
    clean_text,
    normalize_event_date,
    normalize_guadeloupe_city,
    normalize_phone,
    page_rejection_reason,
    validate_bizouk_event,
)
from crawler import build_event_from_item


GOOD_HTML = """
<html><head><title>Sunday Beach</title></head><body>
<section class="evh-hero"><h1 class="evh-hero-title">Sunday Beach</h1>
 <p class="evh-hero-subtitle">Description</p><div class="evh-hero-meta">
 <div class="evh-hero-meta-item"><i class="fa fa-calendar"></i><strong>Sunday August 16 2026 at 3:00 pm</strong></div>
 <div class="evh-hero-meta-item"><i class="fa fa-map-marker"></i><strong>BEACH BAR</strong><span> · .LE GOSIER</span></div>
</div></section><div id="party_description">Une\u200b belle fête.\u00a0 Bienvenue !</div>
<article class="ticket-card"><h3>Entrée</h3><span class="price">20 €</span></article>
<div class="evh-contact-panel"><div><i class="fa fa-phone"></i><span>'+33615285999</span></div></div>
</body></html>"""


class FakeResponse:
    is_redirect = False
    headers = {}
    def __init__(self, text): self.text = text
    def raise_for_status(self): return None


class FakeSession:
    def __init__(self, text): self.text = text
    def get(self, *args, **kwargs): return FakeResponse(self.text)


class BizoukQualityTests(unittest.TestCase):
    def test_unicode_cleanup_preserves_content(self):
        self.assertEqual(clean_text("  Café\u200b\u00a0 créole\r\n  demain  ", multiline=True), "Café créole\ndemain")
        self.assertIsNone(clean_subtitle(" Description "))

    def test_controlled_city_variants(self):
        expected = {".LE GOSIER": "Le Gosier", "LE GOSIER": "Le Gosier", "Gosier": "Le Gosier", "Pointe A Pitre": "Pointe-à-Pitre", "BAIE MAHAULT": "Baie-Mahault"}
        for value, city in expected.items():
            with self.subTest(value=value): self.assertEqual(normalize_guadeloupe_city(value), city)
        for value in ("3 sessions", "Guadeloupe", "BEACH BAR", "Accueil Menu principal"):
            self.assertIsNone(normalize_guadeloupe_city(value))

    def test_phone_cleanup_and_missing_phone(self):
        self.assertEqual(normalize_phone("'+33615285999"), "+33615285999")
        self.assertEqual(normalize_phone("0690 80.58-88"), "+33690805888")
        self.assertIsNone(normalize_phone(None))
        self.assertIsNone(normalize_phone("12345"))

    def test_guadeloupe_wall_time_gets_real_offset(self):
        self.assertEqual(normalize_event_date("Sunday August 16 2026 at 3:00 pm", "guadeloupe"), "2026-08-16T15:00-04:00")
        self.assertEqual(normalize_event_date("2026-08-16T15:00", "london"), "2026-08-16T15:00+01:00")

    def test_local_html_fixture_normalizes_event_without_live_site(self):
        item = {"url": "https://www.bizouk.com/events/details/sunday-beach/127852", "region": "guadeloupe", "slug": "sunday-beach", "external_id": "127852"}
        with patch("crawler.validate_external_url", side_effect=lambda url: url):
            event = build_event_from_item(item, session=FakeSession(GOOD_HTML))
        self.assertEqual(event["name"], "Sunday Beach")
        self.assertIsNone(event["subtitle"])
        self.assertEqual(event["city"], "Le Gosier")
        self.assertEqual(event["address"], "BEACH BAR")
        self.assertEqual(event["contact_phone"], "+33615285999")
        self.assertNotIn("\u200b", event["description"])
        self.assertEqual(event["event_date"], "2026-08-16T15:00-04:00")
        self.assertIsNone(event["contact_website"])

    def test_corrupt_navigation_page_is_rejected(self):
        corrupt = BeautifulSoup("<html><body><nav>Log in Register My tickets</nav><h1>Menu</h1><div>3 sessions</div></body></html>", "html.parser")
        self.assertEqual(page_rejection_reason(corrupt), "unexpected HTML: no event identity")
        item = {"url": "https://www.bizouk.com/events/details/bad/999", "region": "guadeloupe", "slug": "bad", "external_id": "999"}
        with patch("crawler.validate_external_url", side_effect=lambda url: url), patch("crawler.fetch_rendered_bizouk_html", return_value=str(corrupt)):
            with self.assertRaises(EventValidationError):
                build_event_from_item(item, session=FakeSession(str(corrupt)))

    def test_validation_is_a_final_save_barrier(self):
        event = {"event_url": "https://www.bizouk.com/events/details/good/12", "event_external_id": "12", "name": "Good event", "event_date": "2026-08-16T15:00-04:00", "city": "Le Gosier", "description": "Log in Register My tickets", "contact_phone": None}
        with self.assertRaisesRegex(EventValidationError, "navigation"):
            validate_bizouk_event(event)

    def test_end_date_cannot_precede_start(self):
        event = {"event_url": "https://www.bizouk.com/events/details/good/12", "event_external_id": "12", "name": "Good event", "event_date": "2026-08-16T15:00-04:00", "event_end_date": "2026-08-16T14:00-04:00", "city": "Le Gosier", "description": "Une fête", "contact_phone": None}
        with self.assertRaisesRegex(EventValidationError, "precedes"):
            validate_bizouk_event(event)


if __name__ == "__main__":
    unittest.main()
