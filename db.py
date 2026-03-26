import json
import sqlite3
from config import DB_PATH, DATA_DIR


def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_url TEXT UNIQUE NOT NULL,
        region TEXT,
        name TEXT,
        subtitle TEXT,
        event_date TEXT,
        city TEXT,
        address TEXT,
        contact_phone TEXT,
        contact_email TEXT,
        contact_website TEXT,
        google_maps_url TEXT,
        score INTEGER DEFAULT 0,
        is_watchlisted INTEGER DEFAULT 0,
        extraction_mode TEXT,
        extraction_confidence INTEGER DEFAULT 0,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        raw_json TEXT
    );
    CREATE TABLE IF NOT EXISTS flyers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        image_url TEXT NOT NULL,
        UNIQUE(event_id, image_url)
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        category TEXT,
        price_text TEXT,
        numeric_price REAL,
        is_free INTEGER DEFAULT 0,
        is_available INTEGER,
        availability_text TEXT,
        buy_link TEXT,
        details TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        UNIQUE(event_id, product_name, price_text)
    );
    CREATE TABLE IF NOT EXISTS product_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        old_price TEXT,
        new_price TEXT,
        old_available INTEGER,
        new_available INTEGER,
        changed_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS learned_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_type TEXT NOT NULL,
        pattern_name TEXT NOT NULL,
        pattern_value TEXT NOT NULL,
        confidence INTEGER DEFAULT 50,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS page_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_url TEXT,
        page_type TEXT,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS extraction_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_url TEXT,
        mode TEXT,
        confidence INTEGER,
        validation_ok INTEGER,
        issues_json TEXT,
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


def _int_bool(value):
    if value is None:
        return None
    return 1 if value else 0


def upsert_event(event: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM events WHERE event_url = ?", (event["event_url"],))
    existing = cur.fetchone()

    if existing:
        event_id = existing["id"]
        cur.execute(
            "UPDATE events SET region=?, name=?, subtitle=?, event_date=?, city=?, address=?, contact_phone=?, contact_email=?, contact_website=?, google_maps_url=?, score=?, extraction_mode=?, extraction_confidence=?, last_seen_at=datetime('now'), raw_json=? WHERE id=?",
            (
                event.get("region"), event.get("name"), event.get("subtitle"), event.get("event_date"),
                event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"),
                event.get("contact_website"), event.get("google_maps_url"), event.get("score", 0),
                event.get("extraction_mode"), event.get("extraction_confidence", 0),
                json.dumps(event, ensure_ascii=False), event_id,
            ),
        )
    else:
        cur.execute(
            "INSERT INTO events (event_url, region, name, subtitle, event_date, city, address, contact_phone, contact_email, contact_website, google_maps_url, score, extraction_mode, extraction_confidence, first_seen_at, last_seen_at, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
            (
                event["event_url"], event.get("region"), event.get("name"), event.get("subtitle"),
                event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"),
                event.get("contact_email"), event.get("contact_website"), event.get("google_maps_url"),
                event.get("score", 0), event.get("extraction_mode"), event.get("extraction_confidence", 0),
                json.dumps(event, ensure_ascii=False),
            ),
        )
        event_id = cur.lastrowid

    cur.execute("DELETE FROM flyers WHERE event_id = ?", (event_id,))
    for flyer in event.get("flyers", []):
        cur.execute("INSERT OR IGNORE INTO flyers (event_id, image_url) VALUES (?, ?)", (event_id, flyer))

    for product in event.get("products", []):
        cur.execute(
            "SELECT id, price_text, is_available FROM products WHERE event_id=? AND product_name=? AND price_text IS ?",
            (event_id, product.get("product_name"), product.get("price_text")),
        )
        old = cur.fetchone()
        if old:
            cur.execute(
                "UPDATE products SET category=?, numeric_price=?, is_free=?, is_available=?, availability_text=?, buy_link=?, details=?, last_seen_at=datetime('now') WHERE id=?",
                (
                    product.get("category"), product.get("numeric_price"), _int_bool(product.get("is_free")),
                    _int_bool(product.get("is_available")), product.get("availability_text"), product.get("buy_link"),
                    product.get("details"), old["id"],
                ),
            )
            if old["price_text"] != product.get("price_text") or old["is_available"] != _int_bool(product.get("is_available")):
                cur.execute(
                    "INSERT INTO product_history (product_id, old_price, new_price, old_available, new_available, changed_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                    (old["id"], old["price_text"], product.get("price_text"), old["is_available"], _int_bool(product.get("is_available"))),
                )
        else:
            cur.execute(
                "INSERT INTO products (event_id, product_name, category, price_text, numeric_price, is_free, is_available, availability_text, buy_link, details, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (
                    event_id, product.get("product_name"), product.get("category"), product.get("price_text"),
                    product.get("numeric_price"), _int_bool(product.get("is_free")), _int_bool(product.get("is_available")),
                    product.get("availability_text"), product.get("buy_link"), product.get("details"),
                ),
            )

    conn.commit()
    conn.close()


def save_page_snapshot(event_url: str, page_type: str, snapshot: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO page_snapshots (event_url, page_type, snapshot_json, created_at) VALUES (?, ?, ?, datetime('now'))", (event_url, page_type, json.dumps(snapshot, ensure_ascii=False)))
    conn.commit()
    conn.close()


def log_extraction_run(event_url: str, mode: str, confidence: int, validation_ok: bool, issues: list[str]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO extraction_runs (event_url, mode, confidence, validation_ok, issues_json, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))", (event_url, mode, confidence, _int_bool(validation_ok), json.dumps(issues, ensure_ascii=False)))
    conn.commit()
    conn.close()


def get_db_stats():
    conn = get_conn()
    cur = conn.cursor()
    stats = {
        "events": cur.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "products": cur.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "free_products": cur.execute("SELECT COUNT(*) FROM products WHERE is_free = 1").fetchone()[0],
        "free_available": cur.execute("SELECT COUNT(*) FROM products WHERE is_free = 1 AND is_available = 1").fetchone()[0],
        "last_seen_at": cur.execute("SELECT MAX(last_seen_at) FROM events").fetchone()[0],
    }
    conn.close()
    return stats


def list_events():
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY score DESC, last_seen_at DESC").fetchall()]
    conn.close()
    return rows


def list_free_products():
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT p.*, e.name AS event_name, e.event_url FROM products p JOIN events e ON e.id = p.event_id WHERE p.is_free = 1 ORDER BY p.last_seen_at DESC").fetchall()]
    conn.close()
    return rows


def get_event(event_id: int):
    conn = get_conn()
    event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return None
    event = dict(event)
    event["flyers"] = [r[0] for r in conn.execute("SELECT image_url FROM flyers WHERE event_id = ?", (event_id,)).fetchall()]
    event["products"] = [dict(r) for r in conn.execute("SELECT * FROM products WHERE event_id = ? ORDER BY last_seen_at DESC", (event_id,)).fetchall()]
    conn.close()
    return event


def list_patterns():
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM learned_patterns ORDER BY updated_at DESC").fetchall()]
    conn.close()
    return rows


def list_extraction_runs(limit: int = 100):
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM extraction_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
    conn.close()
    return rows
