import sys
import tempfile
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
    stable_product_key,
)
import crawler
from opportunity_scoring import classify_product


class BizoukExtractionTests(unittest.TestCase):
    def test_product_identity_does_not_change_with_price(self):
        self.assertEqual(
            stable_product_key("bizouk", "Single entry", 10),
            stable_product_key("bizouk", "Single entry", 20),
        )

    def test_inconsistent_ticket_names_share_a_comparable_family(self):
        names = ["single entry", "Single entry - BIZOUK PROMO", "SINGLE ENTRY - LAST MINUTE"]
        self.assertEqual({classify_product(name)["family_key"] for name in names}, {"single_entry"})
        self.assertEqual(classify_product("BEACH LOUNGE - 6 PEOPLE")["capacity"], 6)
        self.assertEqual(classify_product("VIP BEACH LOUNGE - 15 PEOPLE")["capacity"], 15)

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

    def test_page_without_product_does_not_infer_one_from_unrelated_prices(self):
        soup = BeautifulSoup("""
          <main>
            <h1>Soirée sur la plage</h1>
            <section class="event-description">
              <h2>Sur place</h2>
              <p>Formule repas : 25 €</p>
              <p>Parking gratuit à proximité.</p>
            </section>
          </main>
        """, "html.parser")
        self.assertEqual(extract_products_from_dom(soup, "bizouk"), [])

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
        self.assertEqual(contact["contact_phone"], "+590690805888")
        self.assertEqual(contact["contact_website"], "https://organizer.example")

    def test_nested_aggregate_offer_is_extracted(self):
        event = {"offers": {"@type": "AggregateOffer", "priceCurrency": "EUR", "offers": [
            {"@type": "Offer", "name": "Prévente", "price": "12.50", "availability": "https://schema.org/InStock"}
        ]}}
        products = extract_products_from_jsonld(event, "bizouk")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["numeric_price"], 12.5)
        self.assertTrue(products[0]["is_available"])


class PriceOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db = crawler.DB_PATH
        crawler.DB_PATH = str(Path(self.tempdir.name) / "events.sqlite")
        crawler.init_db()

    def tearDown(self):
        crawler.DB_PATH = self.previous_db
        self.tempdir.cleanup()

    def event(self, price, name="Single entry", available=True):
        return {
            "source": "kiwol",
            "event_url": "https://example.test/event/price-steps",
            "event_url_normalized": "https://example.test/event/price-steps",
            "name": "Price steps",
            "products": [{"product_name": name, "numeric_price": price,
                          "price_text": f"{price} €", "is_free": False,
                          "is_available": available}],
        }

    def test_successive_price_increases_are_changes_not_new_products(self):
        event_id = crawler.upsert_event(self.event(10))
        crawler.upsert_event(self.event(15))
        crawler.upsert_event(self.event(20))
        connection = crawler.conn()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products WHERE event_id=?", (event_id,)).fetchone()[0], 1)
            history = connection.execute("SELECT old_price, new_price, change_type FROM product_history WHERE event_id=? ORDER BY id", (event_id,)).fetchall()
            self.assertEqual([(row[0], row[1], row[2]) for row in history], [
                (None, 10, "NEW_PRODUCT"), (10, 15, "PRICE_CHANGE"), (15, 20, "PRICE_CHANGE")
            ])
            opportunity = connection.execute("SELECT opportunity_type, reference_price, current_price, is_active FROM price_opportunities WHERE event_id=? AND is_active=1", (event_id,)).fetchone()
            self.assertEqual(tuple(opportunity), ("PRICE_INCREASE", 15, 20, 1))
        finally:
            connection.close()

    def test_available_products_form_ascending_price_steps_within_family(self):
        crawler.upsert_event(self.event(15, "Single entry - PROMO", True))
        crawler.upsert_event({**self.event(20, "Single entry", True), "products": [
            self.event(15, "Single entry - PROMO", True)["products"][0],
            self.event(20, "Single entry", True)["products"][0],
            self.event(35, "Single entry - LAST MINUTE", True)["products"][0],
        ]})
        connection = crawler.conn()
        try:
            rows = connection.execute("SELECT opportunity_type, current_price, reference_price, increase_amount FROM price_opportunities WHERE opportunity_type='PRICE_STEP_UP' AND is_active=1 ORDER BY current_price").fetchall()
            self.assertEqual([tuple(row) for row in rows], [
                ("PRICE_STEP_UP", 15, 20, 5),
                ("PRICE_STEP_UP", 20, 35, 15),
            ])
        finally:
            connection.close()

    def test_non_increase_does_not_create_an_opportunity(self):
        event_id = crawler.upsert_event(self.event(20))
        crawler.upsert_event(self.event(10))
        connection = crawler.conn()
        try:
            history = connection.execute(
                "SELECT old_price, new_price FROM product_history WHERE event_id=? AND change_type='PRICE_CHANGE'",
                (event_id,),
            ).fetchall()
            self.assertEqual([tuple(row) for row in history], [(20, 10)])
            active = connection.execute(
                "SELECT COUNT(*) FROM price_opportunities WHERE event_id=? AND is_active=1",
                (event_id,),
            ).fetchone()[0]
            self.assertEqual(active, 0)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
