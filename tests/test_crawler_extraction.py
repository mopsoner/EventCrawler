import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parents[1] / "EventCrawler"
sys.path.insert(0, str(APP_DIR))

from crawler import (
    bizouk_page_needs_rendering,
    extract_contact_info,
    extract_description,
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

    def test_current_bizouk_ticket_markup_uses_base_price_and_real_stock_state(self):
        soup = BeautifulSoup("""
          <div id="ticketing">
            <div class="panel panel-default"><div class="panel-body">
              <span style="font-weight:bold">Entrée simple</span>
              <div class="produit_prix" data-product-price="42" data-base-price="20.00">
                <span class="product-price-base">20.00€</span>
              </div>
              <button class="qty-minus" disabled></button><button class="qty-plus"></button>
            </div></div>
            <div class="panel panel-danger"><div class="panel-body">
              <span style="font-weight:bold"><s>Prévente promo</s></span>
              <div class="produit_prix" data-product-price="43" data-base-price="15.00">
                <span class="product-price-base">15.00€</span>
              </div><span class="label-danger">Sold Out</span>
            </div></div>
          </div>
          <div class="cart"><span>Total:</span><span>0.00€</span></div>
        """, "html.parser")
        products = extract_products_from_dom(soup, "bizouk")
        by_name = {product["product_name"]: product for product in products}
        self.assertEqual(set(by_name), {"Entrée simple", "Prévente promo"})
        self.assertEqual(by_name["Entrée simple"]["numeric_price"], 20)
        self.assertTrue(by_name["Entrée simple"]["is_available"])
        self.assertFalse(by_name["Prévente promo"]["is_available"])

    def test_current_bizouk_header_description_and_contact_markup(self):
        soup = BeautifulSoup("""
          <section class="evh-hero">
            <h1 class="evh-hero-title">Sunday Beach</h1>
            <p class="evh-hero-subtitle">Do Brazil</p>
            <div class="evh-hero-meta">
              <div class="evh-hero-meta-item"><i class="fa fa-calendar"></i><strong>Sunday, August 16 2026 at 3:00 PM</strong></div>
              <div class="evh-hero-meta-item"><i class="fa fa-map-marker"></i><strong>BEACH BAR</strong><span> · LE GOSIER</span></div>
            </div>
          </section>
          <div id="party_description"><p>La description complète de cet événement est conservée ici.</p></div>
          <div class="evh-contact-panel"><div class="evh-contact-panel-row"><i class="fa fa-phone"></i><span>0690805888</span></div>
            <div class="evh-contact-panel-row"><i class="fa fa-globe"></i><a href="https://organizer.example">Site</a></div></div>
        """, "html.parser")
        fields = extract_header_fields(soup)
        self.assertEqual(fields["subtitle"], "Do Brazil")
        self.assertIn("August 16", fields["event_date"])
        lines = [line.strip() for line in soup.get_text("\n", strip=True).splitlines()]
        self.assertIn("description complète", extract_description(soup, lines))
        contact = extract_contact_info(soup, lines)
        self.assertEqual(contact["contact_phone"], "0690805888")
        self.assertEqual(contact["contact_website"], "https://organizer.example")

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
