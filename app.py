import json
import os
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, redirect, render_template, request, url_for

from config_store import load_config, save_config

DB_PATH = "data/eventcrawler.sqlite"
STATUS_PATH = Path("data/crawl_status.json")
app = Flask(__name__)
app.secret_key = "eventcrawler-local"
CRAWL_PROCESS = None
CRAWL_LOCK = threading.Lock()


def conn():
    Path("data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def ensure_column(cur, table, column, ddl):
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db():
    c = conn()
    cur = c.cursor()
    cur.executescript(
        '''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_url TEXT UNIQUE NOT NULL,
            region TEXT,
            name TEXT,
            event_date TEXT,
            city TEXT,
            address TEXT,
            contact_phone TEXT,
            contact_email TEXT,
            score INTEGER DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            price_text TEXT,
            numeric_price REAL,
            is_free INTEGER DEFAULT 0,
            is_available INTEGER,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(event_id, product_name, price_text)
        );
        '''
    )
    ensure_column(cur, "events", "event_external_id", "event_external_id TEXT")
    ensure_column(cur, "events", "event_slug", "event_slug TEXT")
    ensure_column(cur, "events", "contact_website", "contact_website TEXT")
    ensure_column(cur, "events", "event_image", "event_image TEXT")
    ensure_column(cur, "events", "subtitle", "subtitle TEXT")
    c.commit()
    c.close()


def read_crawl_status():
    if not STATUS_PATH.exists():
        return {"running": False, "regions": [], "last_error": None, "started_at": None, "finished_at": None}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False, "regions": [], "last_error": "status_read_error", "started_at": None, "finished_at": None}


def launch_crawl(selected_regions):
    global CRAWL_PROCESS
    with CRAWL_LOCK:
        if CRAWL_PROCESS and CRAWL_PROCESS.poll() is None:
            return False
        env = os.environ.copy()
        env["EVENTCRAWLER_SELECTED_REGIONS"] = ",".join(selected_regions)
        env["PYTHONUNBUFFERED"] = "1"
        log_path = Path("data/crawl.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
        CRAWL_PROCESS = subprocess.Popen(["python", "crawler.py"], env=env, stdout=log_file, stderr=subprocess.STDOUT)
        return True


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


def list_events(limit=None):
    c = conn()
    select_cols = "id, event_url, region, name, subtitle, event_date, city, address, contact_phone, contact_email, score"
    if has_column("events", "contact_website"):
        select_cols += ", contact_website"
    if has_column("events", "event_image"):
        select_cols += ", event_image"
    sql = f"SELECT {select_cols} FROM events ORDER BY score DESC, last_seen_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in c.execute(sql).fetchall()]
    c.close()
    return rows


def list_free(limit=None):
    c = conn()
    select_cols = "p.*, e.name AS event_name, e.subtitle AS event_subtitle, e.event_date AS event_date, e.region, e.event_url, e.first_seen_at AS event_first_seen, e.score, e.id AS event_id"
    if has_column("events", "event_image"):
        select_cols += ", e.event_image AS event_image"
    sql = f"SELECT {select_cols} FROM products p JOIN events e ON e.id = p.event_id WHERE p.is_free = 1 ORDER BY p.last_seen_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in c.execute(sql).fetchall()]
    c.close()
    return rows


def list_opportunities(limit=None):
    rows = []
    for r in list_free():
        recent = is_recent(r.get("event_first_seen"), hours=24)
        r["is_recent"] = recent
        r["is_early_free_opportunity"] = bool(r.get("is_free")) and r.get("is_available") in (1, True) and recent
        rows.append(r)
    rows.sort(key=lambda x: (x["is_early_free_opportunity"], x.get("score", 0), x.get("event_first_seen") or ""), reverse=True)
    return rows[:limit] if limit else rows


def get_event(event_id):
    c = conn()
    event = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        c.close()
        return None
    out = dict(event)
    out["products"] = [dict(r) for r in c.execute("SELECT * FROM products WHERE event_id=? ORDER BY last_seen_at DESC", (event_id,)).fetchall()]
    c.close()
    return out


@app.route("/", methods=["GET"])
def dashboard():
    cfg = load_config()
    return render_template(
        "dashboard.html",
        stats=stats(),
        config=cfg,
        crawl_status=read_crawl_status(),
        top_events=list_events(limit=6),
        top_opportunities=list_opportunities(limit=8),
    )


@app.route("/crawl", methods=["POST"])
def run_crawl_now():
    cfg = load_config()
    selected_regions = request.form.getlist("regions")
    allowed = [name for name, region in cfg["regions"].items() if region.get("enabled")]
    selected_regions = [r for r in selected_regions if r in allowed]
    if not selected_regions:
        return redirect(url_for("dashboard", error="no_region"))
    launch_crawl(selected_regions)
    return redirect(url_for("dashboard", started=1))


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


@app.route("/config", methods=["GET", "POST"])
def config_page():
    if request.method == "POST":
        current = load_config()
        regions = {}
        for name, region in current["regions"].items():
            regions[name] = {
                "enabled": request.form.get(f"region_enabled_{name}") == "on",
                "url": request.form.get(f"region_url_{name}", region["url"]).strip() or region["url"],
            }
        new_config = {
            "max_workers": request.form.get("max_workers", current["max_workers"]),
            "request_timeout": request.form.get("request_timeout", current["request_timeout"]),
            "user_agent": request.form.get("user_agent", current["user_agent"]),
            "regions": regions,
        }
        save_config(new_config)
        return redirect(url_for("config_page", saved=1))

    saved = request.args.get("saved") == "1"
    return render_template("config.html", config=load_config(), saved=saved)


@app.route("/api/events")
def api_events():
    return jsonify(list_events())


@app.route("/api/free")
def api_free():
    return jsonify(list_free())


@app.route("/api/opportunities")
def api_opportunities():
    return jsonify(list_opportunities())


@app.route("/api/config")
def api_config():
    return jsonify(load_config())


@app.route("/api/crawl_status")
def api_crawl_status():
    return jsonify(read_crawl_status())


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
