import copy
from pathlib import Path

import pytest

import app
import crawler
from config_store import DEFAULT_CONFIG, _merge_defaults


def event(product):
    return {"source": "kiwol", "event_url": "https://www.kiwol.com/events/durable-test",
            "name": "Durable test", "products": [product]}


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = str(tmp_path / "events.sqlite")
    monkeypatch.setattr(crawler, "DB_PATH", path)
    monkeypatch.setattr(app, "DB_PATH", path)
    crawler.init_db()
    return path


@pytest.mark.parametrize("product", [
    {"product_name": "Paid", "numeric_price": 5, "is_free": False, "is_available": True},
    {"product_name": "Unavailable", "numeric_price": 0, "is_free": True, "is_available": False},
    {"product_name": "Not marked free", "numeric_price": 0, "is_free": False, "is_available": True},
])
def test_ineligible_new_product_does_not_queue(database, monkeypatch, product):
    monkeypatch.setattr(crawler, "CONFIG", {"booking_profile": {"auto_book_new_free_products": True}})
    crawler.upsert_event(event(product))
    with crawler.conn() as c:
        assert c.execute("SELECT count(*) FROM booking_jobs").fetchone()[0] == 0


def test_new_free_product_queues_once_and_rescan_is_idempotent(database, monkeypatch):
    monkeypatch.setattr(crawler, "CONFIG", {"booking_profile": {"auto_book_new_free_products": True}})
    product = {"product_name": "Exact discovered name", "numeric_price": 0, "is_free": True, "is_available": True}
    crawler.upsert_event(event(product)); crawler.upsert_event(event(product))
    with crawler.conn() as c:
        rows = c.execute("SELECT * FROM booking_jobs").fetchall()
    assert len(rows) == 1 and rows[0]["product_name"] == "Exact discovered name"


def test_automatic_booking_is_enabled_by_default(database, monkeypatch):
    default_config = _merge_defaults({})
    assert default_config["booking_profile"]["email"] == "contact@sejourcarnaval.com"
    assert default_config["booking_profile"]["default_ticket_count"] == 2
    monkeypatch.setattr(crawler, "CONFIG", default_config)
    crawler.upsert_event(event({"product_name": "Free", "numeric_price": 0, "is_free": True, "is_available": True}))
    with crawler.conn() as c:
        assert c.execute("SELECT count(*) FROM booking_jobs").fetchone()[0] == 1
    assert default_config["booking_profile"]["auto_book_new_free_products"] is True


def test_worker_passes_profile_and_busy_launcher_keeps_pending(database, monkeypatch):
    monkeypatch.setattr(crawler, "CONFIG", {"booking_profile": {"auto_book_new_free_products": True}})
    crawler.upsert_event(event({"product_name": "Free exact", "numeric_price": 0, "is_free": True, "is_available": True}))
    profile = copy.deepcopy(DEFAULT_CONFIG)
    profile["booking_profile"].update(auto_book_new_free_products=True, default_ticket_count=4, email="book@example.test")
    monkeypatch.setattr(app, "load_config", lambda: profile)
    monkeypatch.setattr(app, "booking_is_running", lambda: False)
    received = []
    assert app.process_booking_job_once(lambda *args: received.append(args) or False) is False
    assert received == [("https://www.kiwol.com/events/durable-test", 4, "book@example.test", "Free exact")]
    with app.conn() as c:
        row = c.execute("SELECT state, attempt_count FROM booking_jobs").fetchone()
    assert tuple(row) == ("pending", 0)
