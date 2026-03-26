import sqlite3
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template

DB_PATH = "data/eventcrawler.sqlite"
app = Flask(__name__)

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None

def is_recent(value, hours=24):
    dt = parse_dt(value)
    if not dt:
        return False
    return datetime.utcnow() - dt <= timedelta(hours=hours)

def has_column(table, column):
    c = conn()
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    c.close()
    return column in cols

def stats():
    c = conn()
    cur = c.cursor()
    out = {
        "events": cur.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "free_products": cur.execute("SELECT COUNT(*) FROM products WHERE is_free = 1").fetchone()[0],
        "free_available": cur.execute("SELECT COUNT(*) FROM products WHERE is_free = 1 AND is_available = 1").fetchone()[0],
        "last_seen_at": cur.execute("SELECT MAX(last_seen_at) FROM events").fetchone()[0],
    }
    c.close()
    return out

def list_events():
    c = conn()
    select_cols = "id, event_url, region, name, event_date, city, address, contact_phone, contact_email, score"
    if has_column("events", "contact_website"):
        select_cols += ", contact_website"
    rows = [dict(r) for r in c.execute(f"SELECT {select_cols} FROM events ORDER BY score DESC, last_seen_at DESC").fetchall()]
    c.close()
    return rows

def list_free():
    c = conn()
    rows = [dict(r) for r in c.execute("SELECT p.*, e.name AS event_name, e.region, e.event_url, e.first_seen_at AS event_first_seen, e.score, e.id AS event_id FROM products p JOIN events e ON e.id = p.event_id WHERE p.is_free = 1 ORDER BY p.last_seen_at DESC").fetchall()]
    c.close()
    return rows

def list_opportunities():
    rows = []
    for r in list_free():
        recent = is_recent(r.get("event_first_seen"), hours=24)
        r["is_recent"] = recent
        r["is_early_free_opportunity"] = bool(r.get("is_free")) and r.get("is_available") in (1, True) and recent
        rows.append(r)
    rows.sort(key=lambda x: (x["is_early_free_opportunity"], x.get("score", 0), x.get("event_first_seen") or ""), reverse=True)
    return rows

def get_event(event_id):
    c = conn()
    select_cols = "*"
    event = c.execute(f"SELECT {select_cols} FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        c.close()
        return None
    out = dict(event)
    out["products"] = [dict(r) for r in c.execute("SELECT * FROM products WHERE event_id=? ORDER BY last_seen_at DESC", (event_id,)).fetchall()]
    c.close()
    return out

@app.route("/")
def dashboard():
    return render_template("dashboard.html", stats=stats())

@app.route("/events")
def events():
    return render_template("events.html", events=list_events())

@app.route("/free")
def free():
    return render_template("free.html", rows=list_free())

@app.route("/opportunities")
def opportunities():
    return render_template("opportunities.html", rows=list_opportunities())

@app.route("/event/<int:event_id>")
def event_detail(event_id):
    return render_template("event.html", event=get_event(event_id))

@app.route("/api/events")
def api_events():
    return jsonify(list_events())

@app.route("/api/free")
def api_free():
    return jsonify(list_free())

@app.route("/api/opportunities")
def api_opportunities():
    return jsonify(list_opportunities())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
