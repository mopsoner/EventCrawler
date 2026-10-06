"""Public Kiwol captures and controlled pages for transport and storage checks."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

import app
import crawler
from bizouk_quality import EventValidationError


URL = "https://www.kiwol.com/billetterie/13402"
FIXTURES = Path(__file__).parent / "fixtures"


def test_captured_kiwol_event_extracts_visible_organizer_original_flyer_and_prices():
    with patch.object(crawler, "fetch_html", return_value=(FIXTURES / "kiwol_naim_13402.html").read_text()), \
         patch.object(crawler, "fetch_rendered_kiwol_html") as render:
        event = crawler.build_event_from_item(item())
    render.assert_not_called()
    assert event["name"] == "SPECTACLE DE NAIM"
    assert event["organizer_name"] == "ECLATSPROD"
    assert event["event_date"] == "2027-03-06 20:00-21:30"
    assert event["city"] == "LE GOSIER"
    assert event["contact_email"] == "info@eclatsprod.com"
    assert event["contact_website"] == "https://www.instagram.com/eclatsprod/"
    assert event["event_image"].endswith('/8e3b546652cb79f9d93c723ccf323c19.png')
    assert [p["numeric_price"] for p in event["products"]] == [35, 40, 45]
    assert all(p["is_available"] is True and p["is_free"] is False for p in event["products"])


def test_captured_agenda_card_metadata():
    links = crawler.extract_event_links((FIXTURES / "kiwol_agenda.html").read_text(), 'https://www.kiwol.com/agenda')
    assert len(links) == 2
    assert links[0]["external_id"] == "14276"
    assert links[0]["list_title"] == "Yoga à la maison - Meiline Yoga"
    assert links[0]["list_date"] == "01 octobre - 19h30"


def detail_html(price=0, availability="https://schema.org/InStock"):
    data = {
        "@context": "https://schema.org", "@type": "Event", "name": "Concert test Kiwol",
        "startDate": "2026-12-12T20:00:00-04:00", "endDate": "2026-12-13T01:00:00-04:00",
        "description": "Présentation complète du concert.",
        "location": [{"@type": "Place", "name": "Salle test", "address": {
            "streetAddress": "1 rue du concert", "addressLocality": "Le Gosier"}}],
        "organizer": [{"name": "Organisateur test"}],
        "image": [{"url": "/flyer.jpg", "width": 1200, "height": 1600}],
        "offers": {"@type": "AggregateOffer", "offers": [
            {"@type": "Offer", "name": "Entrée test", "price": price,
             "priceCurrency": "EUR", "availability": availability}]},
    }
    return '<h1>Concert test Kiwol</h1><script type="application/ld+json">' + json.dumps(data) + '</script>'


def item():
    return {"url": URL, "region": "kiwol_agenda", "source": "kiwol",
            "external_id": "13402", "slug": "kiwol-13402"}


def test_agenda_links_preserve_card_fields_and_reject_other_hosts():
    html = '''<a class="ticketing-card-search-container" href="/billetterie/13402?tracking=1">
      <span class="ticketing-card-title">Concert test</span>
      <span class="ticketing-card-date">12 décembre 2026</span>
      <span class="ticketing-card-location">Le Gosier</span></a>
      <a href="/billetterie/13402">Voir le billet</a>
      <a href="https://evil.example/billetterie/13403">Autre site</a>
      <a href="/billetterie/13402/checkout">Commander</a>'''
    links = crawler.extract_event_links(html, "https://www.kiwol.com/agenda")
    assert len(links) == 1
    assert links[0]["url"] == URL
    assert links[0]["list_title"] == "Concert test"
    assert links[0]["list_location"] == "Le Gosier"


def test_listing_routes_kiwol_to_browser_and_keeps_bizouk_static():
    with patch.object(crawler, "fetch_rendered_kiwol_html", return_value="dynamic") as rendered, \
         patch.object(crawler, "fetch_html", return_value="static") as static:
        assert crawler.fetch_listing_html("https://www.kiwol.com/agenda?location=GP") == "dynamic"
        assert crawler.fetch_listing_html("https://www.bizouk.com/?region=paris") == "static"
        assert rendered.call_count == static.call_count == 1


def test_detail_uses_structured_metadata_and_end_date():
    with patch.object(crawler, "fetch_html", return_value=detail_html()), \
         patch.object(crawler, "fetch_rendered_kiwol_html") as render:
        event = crawler.build_event_from_item(item())
    render.assert_not_called()
    assert event["name"] == "Concert test Kiwol"
    assert event["organizer_name"] == "Organisateur test"
    assert event["city"] == "Le Gosier"
    assert event["address"] == "1 rue du concert"
    assert event["event_image"] == "https://www.kiwol.com/flyer.jpg"
    assert event["event_end_date"] == "2026-12-13T01:00:00-04:00"
    assert event["products"][0]["is_free"] is True


def test_detail_renders_when_tickets_are_loaded_by_javascript():
    with patch.object(crawler, "fetch_html", return_value="<h1>Concert</h1>"), \
         patch.object(crawler, "fetch_rendered_kiwol_html", return_value=detail_html(12)) as render:
        event = crawler.build_event_from_item(item())
    render.assert_called_once_with(URL)
    assert event["products"][0]["numeric_price"] == 12


def test_blocked_http_page_uses_browser_but_error_html_is_not_saved():
    response = requests.Response()
    response.status_code = 403
    with patch.object(crawler, "fetch_html", side_effect=requests.HTTPError(response=response)), \
         patch.object(crawler, "fetch_rendered_kiwol_html", return_value=detail_html()):
        assert crawler.build_event_from_item(item())["source"] == "kiwol"
    with patch.object(crawler, "fetch_html", return_value="<title>Just a moment</title>"), \
         patch.object(crawler, "fetch_rendered_kiwol_html", return_value="<title>Just a moment</title>"):
        with pytest.raises(EventValidationError):
            crawler.build_event_from_item(item())


@pytest.mark.parametrize("stock,expected", [("InStock", True), ("SoldOut", False),
                                         ("PreOrder", None), (None, None)])
def test_free_ticket_stock_is_not_assumed(stock, expected):
    product = crawler.extract_kiwol_products({"offers": {"price": 0, "name": "Entrée", "availability": stock}})[0]
    assert product["is_available"] is expected


def test_unknown_price_does_not_make_a_free_ticket_and_paid_label_is_not_free():
    offers = [{"name": "Gratuit pour enfants", "price": "10"},
              {"name": "Gratuit", "price": None}, {"name": "Bad", "price": "nan"}]
    products = crawler.extract_kiwol_products({"offers": offers})
    assert len(products) == 1
    assert products[0]["is_free"] is False


def test_kiwol_persistence_history_and_existing_pages(tmp_path, monkeypatch):
    database = str(tmp_path / "events.sqlite")
    monkeypatch.setattr(crawler, "DB_PATH", database)
    monkeypatch.setattr(app, "DB_PATH", database)
    monkeypatch.setattr(crawler, "CONFIG", {"booking_profile": {"auto_book_new_free_products": False}})
    crawler.init_db()
    with crawler.conn() as connection:
        connection.execute("INSERT INTO events(source,event_url,event_external_id,name,region) VALUES (?,?,?,?,?)",
                           ("bizouk", "https://www.bizouk.com/events/details/other/13402", "13402", "Bizouk intact", "guadeloupe"))
    with patch.object(crawler, "fetch_html", return_value=detail_html(15)):
        event_id = crawler.upsert_event(crawler.build_event_from_item(item()))
    with patch.object(crawler, "fetch_html", return_value=detail_html(0)):
        assert crawler.upsert_event(crawler.build_event_from_item(item())) == event_id
    with crawler.conn() as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT name FROM events WHERE source='bizouk'").fetchone()[0] == "Bizouk intact"
        assert connection.execute("SELECT count(*) FROM products WHERE event_id=?", (event_id,)).fetchone()[0] == 1
        change = connection.execute("SELECT old_price,new_price FROM product_history WHERE change_type='PRICE_CHANGE'").fetchone()
        assert tuple(change) == (15, 0)
    monkeypatch.chdir(tmp_path)
    with patch.dict(app.app.config):
        application = app.create_app({"TESTING": True, "ADMIN_USERNAME": "test", "ADMIN_PASSWORD": "test", "SECRET_KEY": "test"})
        client = application.test_client()
        for route in ("/events", "/free", "/opportunities", f"/event/{event_id}"):
            response = client.get(route, auth=("test", "test"))
            assert response.status_code == 200, route
        assert b"Concert test Kiwol" in client.get("/free", auth=("test", "test")).data
