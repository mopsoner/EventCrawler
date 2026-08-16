import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "EventCrawler"
sys.path.insert(0, str(APP_DIR))

from crawler import (
    bizouk_page_needs_rendering,
    extract_header_fields,
    extract_jsonld_event,
    extract_products_from_dom,
    extract_products_from_jsonld,
    jsonld_event_fields,
    looks_like_date_line,
)


class BizoukExtractionTests(unittest.TestCase):
    def test_dates_with_and_without_year_are_recognized(self):
        for value in ("Dimanche 16 août · 15h00", "Sunday August 16 at 3:00 pm", "16 août 2026"):
            with self.subTest(value=value):
                self.assertTrue(looks_like_date_line(value))

    def test_semantic_header_fields_take_priority(self):
        soup = BeautifulSoup("""
            <h1>Sunday Beach</h1><h2>Une fausse sous-section</h2>
            <time datetime="2026-08-16T15:00">Dimanche 16 août, 15h</time>
            <span itemprop="location">Le Gosier</span>
            <address>Plage de la Datcha</address>
        """, "html.parser")
        fields = extract_header_fields(soup)
        self.assertEqual(fields["event_date"], "Dimanche 16 août, 15h")
        self.assertEqual(fields["city"], "Le Gosier")
        self.assertEqual(fields["address"], "Plage de la Datcha")

    def test_jsonld_graph_and_event_metadata(self):
        soup = BeautifulSoup("""
          <script type="application/ld+json">{
            "@context":"https://schema.org", "@graph":[
              {"@type":"WebPage", "name":"Page"},
              {"@type":["Thing", "MusicEvent"], "name":"Sunday Beach",
               "startDate":"2026-08-16", "endDate":"2026-08-16",
               "image":{"url":"https://img.example/event.jpg"},
               "organizer":{"name":"Beach Team"},
               "location":{"name":"La Datcha", "address":{"streetAddress":"Rue de la plage", "addressLocality":"Le Gosier"}}}
            ]}
          </script>
        """, "html.parser")
        event = extract_jsonld_event(soup)
        fields = jsonld_event_fields(event)
        self.assertEqual(event["name"], "Sunday Beach")
        self.assertEqual(fields["city"], "Le Gosier")
        self.assertEqual(fields["subtitle"], "Beach Team")
        self.assertEqual(fields["image"], "https://img.example/event.jpg")

    def test_page_without_server_rendered_offers_needs_browser(self):
        soup = BeautifulSoup('<h1>Sunday Beach</h1><script type="application/ld+json">{"@type":"Event","name":"Sunday Beach"}</script>', "html.parser")
        self.assertTrue(bizouk_page_needs_rendering(soup))

        rendered = BeautifulSoup('<h1>Sunday Beach</h1><article class="ticket-card"><h3>Entrée</h3><span class="price">20 €</span></article>', "html.parser")
        self.assertFalse(bizouk_page_needs_rendering(rendered))

    def test_targeted_products_include_free_and_disabled_tickets(self):
        soup = BeautifulSoup("""
          <section class="ticket-list">
            <article class="ticket-card"><h3>Invitation</h3><span class="price">Gratuit</span></article>
            <article class="ticket-card"><h3>Early bird</h3><span data-price="15">15 €</span><button disabled>Complet</button></article>
          </section>
        """, "html.parser")
        products = extract_products_from_dom(soup, "bizouk")
        by_name = {product["product_name"]: product for product in products}
        self.assertEqual(by_name["Invitation"]["numeric_price"], 0)
        self.assertTrue(by_name["Invitation"]["is_free"])
        self.assertFalse(by_name["Early bird"]["is_available"])

    def test_nested_aggregate_offer_is_extracted(self):
        event = {"offers": {"@type": "AggregateOffer", "priceCurrency": "EUR", "offers": [
            {"@type": "Offer", "name": "Prévente", "price": "12.50", "availability": "https://schema.org/InStock"}
        ]}}
        products = extract_products_from_jsonld(event, "bizouk")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["numeric_price"], 12.5)
        self.assertTrue(products[0]["is_available"])


if __name__ == "__main__":
    unittest.main()
