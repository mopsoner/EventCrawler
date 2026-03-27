import json
import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, redirect, render_template, request, url_for

from config_store import load_config, save_config

DB_PATH = "data/eventcrawler.sqlite"
STATUS_PATH = Path("data/crawl_status.json")
SCHEDULER_STATE_PATH = Path("data/scheduler_state.json")
app = Flask(__name__)
app.secret_key = "eventcrawler-local"
CRAWL_PROCESS = None
CRAWL_LOCK = threading.Lock()
SCHEDULER_THREAD = None
SCHEDULER_THREAD_LOCK = threading.Lock()
SCHEDULER_LOOP_SECONDS = 30


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
        CREATE TABLE IF NOT EXISTS product_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            product_name TEXT,
            change_type TEXT,
            old_price REAL,
            new_price REAL,
            old_is_free INTEGER,
            new_is_free INTEGER,
            old_is_available INTEGER,
            new_is_available INTEGER,
            observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT,
            regions TEXT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            status TEXT,
            events_queued INTEGER DEFAULT 0,
            events_processed INTEGER DEFAULT 0,
            errors_count INTEGER DEFAULT 0,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS crawl_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_run_id INTEGER,
            scope TEXT,
            target TEXT,
            error_text TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        '''
    )
    ensure_column(cur, "events", "event_external_id", "event_external_id TEXT")
    ensure_column(cur, "events", "event_slug", "event_slug TEXT")
    ensure_column(cur, "events", "contact_website", "contact_website TEXT")
    ensure_column(cur, "events", "event_image", "event_image TEXT")
    ensure_column(cur, "events", "subtitle", "subtitle TEXT")
    ensure_column(cur, "events", "manual_status", "manual_status TEXT")
    ensure_column(cur, "events", "private_note", "private_note TEXT")
    ensure_column(cur, "events", "is_watchlisted", "is_watchlisted INTEGER DEFAULT 0")
    c.commit()
    c.close()


def default_scheduler_state():
    return {
        "enabled": False,
        "last_region_scan_at": None,
        "last_free_refresh_at": None,
        "current_job": None,
        "updated_at": None,
    }


def read_scheduler_state():
    if not SCHEDULER_STATE_PATH.exists():
        state = default_scheduler_state()
        write_scheduler_state(state)
        return state
    try:
        data = json.loads(SCHEDULER_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = default_scheduler_state()
    state = default_scheduler_state()
    state.update(data if isinstance(data, dict) else {})
    return state


def write_scheduler_state(state):
    state = dict(default_scheduler_state(), **(state or {}))
    state["updated_at"] = datetime.utcnow().isoformat()
    SCHEDULER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULER_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def patch_scheduler_state(**fields):
    state = read_scheduler_state()
    state.update(fields)
    return write_scheduler_state(state)


def crawl_is_running():
    global CRAWL_PROCESS
    return bool(CRAWL_PROCESS and CRAWL_PROCESS.poll() is None)


def stop_crawl_process():
    global CRAWL_PROCESS
    with CRAWL_LOCK:
        if not CRAWL_PROCESS or CRAWL_PROCESS.poll() is not None:
            return False
        try:
            CRAWL_PROCESS.terminate()
            CRAWL_PROCESS.wait(timeout=10)
        except Exception:
            try:
                CRAWL_PROCESS.kill()
            except Exception:
                pass
        patch_scheduler_state(current_job=None)
        return True


def read_crawl_status():
    if not STATUS_PATH.exists():
        return {"running": False, "regions": [], "last_error": None, "started_at": None, "finished_at": None}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False, "regions": [], "last_error": "status_read_error", "started_at": None, "finished_at": None}


def launch_crawl(selected_regions, trigger="manual"):
    global CRAWL_PROCESS
    with CRAWL_LOCK:
        if CRAWL_PROCESS and CRAWL_PROCESS.poll() is None:
            return False
        env = os.environ.copy()
        env["EVENTCRAWLER_SELECTED_REGIONS"] = ",".join(selected_regions)
        env["EVENTCRAWLER_TRIGGER"] = trigger
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
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def is_recent(value, hours=24):
    dt = parse_dt(value)
    if not dt:
        return False
    return datetime.utcnow() - dt.replace(tzinfo=None) <= timedelta(hours=hours)


def is_due(last_run_at, minutes=0, hours=0):
    dt = parse_dt(last_run_at)
    if not dt:
        return True
    delta = datetime.utcnow() - dt.replace(tzinfo=None)
    return delta >= timedelta(minutes=minutes, hours=hours)


def time_ago(value):
    dt = parse_dt(value)
    if not dt:
        return "—"
    delta = datetime.utcnow() - dt.replace(tzinfo=None)
    seconds = int(max(delta.total_seconds(), 0))
    if seconds < 60:
        return "à l’instant"
    minutes = seconds // 60
    if minutes < 60:
        return f"il y a {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"il y a {hours} h"
    days = hours // 24
    if days < 30:
        return f"il y a {days} jour{'s' if days > 1 else ''}"
    months = days // 30
    if months < 12:
        return f"il y a {months} mois"
    years = days // 365
    return f"il y a {years} an{'s' if years > 1 else ''}"


def has_column(table, column):
    c = conn()
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    c.close()
    return column in cols


def decorate_rows(rows):
    for row in rows:
        row["added_at"] = row.get("first_seen_at") or row.get("event_first_seen")
        row["added_ago"] = time_ago(row.get("added_at"))
        row["is_watchlisted"] = bool(row.get("is_watchlisted", 0))
    return rows


def stats():
    c = conn()
    cur = c.cursor()
    out = {
        "events": cur.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "free_products": cur.execute("SELECT COUNT(*) FROM products WHERE COALESCE(numeric_price, -1) = 0 AND is_free = 1").fetchone()[0],
        "free_available": cur.execute("SELECT COUNT(*) FROM products WHERE COALESCE(numeric_price, -1) = 0 AND is_free = 1 AND is_available = 1").fetchone()[0],
        "watchlist": cur.execute("SELECT COUNT(*) FROM events WHERE COALESCE(is_watchlisted,0)=1").fetchone()[0],
        "organizers": cur.execute("SELECT COUNT(*) FROM (SELECT COALESCE(NULLIF(contact_website,''), NULLIF(contact_email,''), NULLIF(contact_phone,'')) AS organizer_key FROM events WHERE COALESCE(NULLIF(contact_website,''), NULLIF(contact_email,''), NULLIF(contact_phone,'')) IS NOT NULL GROUP BY organizer_key)").fetchone()[0],
        "last_seen_at": cur.execute("SELECT MAX(last_seen_at) FROM events").fetchone()[0],
    }
    c.close()
    return out


def list_events(limit=None, watchlist_only=False):
    c = conn()
    select_cols = "id, event_url, region, name, subtitle, event_date, city, address, contact_phone, contact_email, first_seen_at, score, manual_status, private_note, is_watchlisted"
    if has_column("events", "contact_website"):
        select_cols += ", contact_website"
    if has_column("events", "event_image"):
        select_cols += ", event_image"
    sql = f"SELECT {select_cols} FROM events"
    if watchlist_only:
        sql += " WHERE COALESCE(is_watchlisted,0)=1"
    sql += " ORDER BY score DESC, last_seen_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in c.execute(sql).fetchall()]
    c.close()
    return decorate_rows(rows)


def list_free(limit=None):
    c = conn()
    select_cols = "p.*, e.name AS event_name, e.subtitle AS event_subtitle, e.event_date AS event_date, e.region, e.event_url, e.first_seen_at AS event_first_seen, e.score, e.id AS event_id, e.manual_status AS manual_status, e.is_watchlisted AS is_watchlisted"
    if has_column("events", "event_image"):
        select_cols += ", e.event_image AS event_image"
    sql = f"SELECT {select_cols} FROM products p JOIN events e ON e.id = p.event_id WHERE p.is_free = 1 AND COALESCE(p.numeric_price, -1) = 0 ORDER BY p.last_seen_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in c.execute(sql).fetchall()]
    c.close()
    return decorate_rows(rows)


def list_opportunities(limit=None):
    rows = []
    for r in list_free():
        recent = is_recent(r.get("event_first_seen"), hours=24)
        r["is_recent"] = recent
        r["is_early_free_opportunity"] = bool(r.get("is_free")) and r.get("is_available") in (1, True) and recent
        rows.append(r)
    rows.sort(key=lambda x: (x["is_early_free_opportunity"], x.get("score", 0), x.get("event_first_seen") or ""), reverse=True)
    return rows[:limit] if limit else rows


def list_activity(limit=100):
    c = conn()
    sql = '''
    SELECT ph.*, e.name AS event_name, e.region, e.event_url, e.id AS event_id
    FROM product_history ph
    LEFT JOIN events e ON e.id = ph.event_id
    ORDER BY ph.observed_at DESC
    LIMIT ?
    '''
    rows = [dict(r) for r in c.execute(sql, (limit,)).fetchall()]
    c.close()
    for row in rows:
        row["observed_ago"] = time_ago(row.get("observed_at"))
    return rows


def list_crawl_runs(limit=30):
    c = conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    c.close()
    for row in rows:
        row["started_ago"] = time_ago(row.get("started_at"))
    return rows


def list_organizers():
    c = conn()
    sql = '''
    SELECT
      COALESCE(NULLIF(contact_website,''), NULLIF(contact_email,''), NULLIF(contact_phone,'')) AS organizer_key,
      MIN(name) AS sample_event_name,
      COUNT(*) AS events_count,
      SUM(CASE WHEN EXISTS (
        SELECT 1 FROM products p WHERE p.event_id = events.id AND COALESCE(p.numeric_price, -1)=0 AND p.is_free=1
      ) THEN 1 ELSE 0 END) AS free_event_count,
      MAX(first_seen_at) AS last_seen_at,
      MAX(contact_phone) AS contact_phone,
      MAX(contact_email) AS contact_email,
      MAX(contact_website) AS contact_website
    FROM events
    WHERE COALESCE(NULLIF(contact_website,''), NULLIF(contact_email,''), NULLIF(contact_phone,'')) IS NOT NULL
    GROUP BY organizer_key
    ORDER BY free_event_count DESC, events_count DESC, last_seen_at DESC
    '''
    rows = [dict(r) for r in c.execute(sql).fetchall()]
    c.close()
    for row in rows:
        row["last_seen_ago"] = time_ago(row.get("last_seen_at"))
    return rows


def get_event(event_id):
    c = conn()
    event = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        c.close()
        return None
    out = dict(event)
    out["added_at"] = out.get("first_seen_at")
    out["added_ago"] = time_ago(out.get("first_seen_at"))
    out["is_watchlisted"] = bool(out.get("is_watchlisted", 0))
    out["products"] = [dict(r) for r in c.execute("SELECT * FROM products WHERE event_id=? ORDER BY last_seen_at DESC", (event_id,)).fetchall()]
    out["history"] = [dict(r) for r in c.execute("SELECT * FROM product_history WHERE event_id=? ORDER BY observed_at DESC LIMIT 50", (event_id,)).fetchall()]
    for row in out["history"]:
        row["observed_ago"] = time_ago(row.get("observed_at"))
    c.close()
    return out


def scheduler_tick():
    state = read_scheduler_state()
    if not state.get("enabled"):
        return
    if crawl_is_running():
        return
    cfg = load_config()
    enabled_regions = [name for name, region in cfg["regions"].items() if region.get("enabled")]
    if not enabled_regions:
        return
    region_due = is_due(state.get("last_region_scan_at"), minutes=int(cfg.get("region_scan_frequency_minutes", 60)))
    free_due = is_due(state.get("last_free_refresh_at"), hours=int(cfg.get("free_product_refresh_frequency_hours", 24)))
    if region_due:
        if launch_crawl(enabled_regions, trigger="scheduler_region_scan"):
            patch_scheduler_state(last_region_scan_at=datetime.utcnow().isoformat(), current_job="region_scan")
            return
    if free_due:
        if launch_crawl(enabled_regions, trigger="scheduler_free_refresh"):
            patch_scheduler_state(last_free_refresh_at=datetime.utcnow().isoformat(), current_job="free_refresh")
            return
    if not crawl_is_running() and state.get("current_job"):
        patch_scheduler_state(current_job=None)


def scheduler_loop():
    while True:
        try:
            scheduler_tick()
        except Exception:
            pass
        time.sleep(SCHEDULER_LOOP_SECONDS)


def ensure_scheduler_thread():
    global SCHEDULER_THREAD
    with SCHEDULER_THREAD_LOCK:
        if SCHEDULER_THREAD and SCHEDULER_THREAD.is_alive():
            return
        SCHEDULER_THREAD = threading.Thread(target=scheduler_loop, daemon=True, name="eventcrawler-scheduler")
        SCHEDULER_THREAD.start()


@app.route("/", methods=["GET"])
def dashboard():
    cfg = load_config()
    return render_template(
        "dashboard.html",
        stats=stats(),
        config=cfg,
        crawl_status=read_crawl_status(),
        scheduler_state=read_scheduler_state(),
        top_events=list_events(limit=6),
        top_opportunities=list_opportunities(limit=8),
        watchlist_events=list_events(limit=6, watchlist_only=True),
        recent_activity=list_activity(limit=8),
        recent_runs=list_crawl_runs(limit=6),
    )


@app.route("/crawl", methods=["POST"])
def run_crawl_now():
    cfg = load_config()
    selected_regions = request.form.getlist("regions")
    allowed = [name for name, region in cfg["regions"].items() if region.get("enabled")]
    selected_regions = [r for r in selected_regions if r in allowed]
    if not selected_regions:
        return redirect(url_for("dashboard", error="no_region"))
    launch_crawl(selected_regions, trigger="manual_dashboard")
    return redirect(url_for("dashboard", started=1))


@app.route("/crawl/stop", methods=["POST"])
def stop_crawl_now():
    stop_crawl_process()
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/scheduler/start", methods=["POST"])
def scheduler_start():
    ensure_scheduler_thread()
    patch_scheduler_state(enabled=True)
    return redirect(request.referrer or url_for("config_page", scheduler_saved=1))


@app.route("/scheduler/stop", methods=["POST"])
def scheduler_stop():
    patch_scheduler_state(enabled=False, current_job=None)
    return redirect(request.referrer or url_for("config_page", scheduler_saved=1))


@app.route("/scheduler/run-region-scan", methods=["POST"])
def scheduler_run_region_scan():
    cfg = load_config()
    enabled_regions = [name for name, region in cfg["regions"].items() if region.get("enabled")]
    if enabled_regions and launch_crawl(enabled_regions, trigger="manual_region_scan"):
        patch_scheduler_state(last_region_scan_at=datetime.utcnow().isoformat(), current_job="region_scan")
    return redirect(request.referrer or url_for("config_page"))


@app.route("/scheduler/run-free-refresh", methods=["POST"])
def scheduler_run_free_refresh():
    cfg = load_config()
    enabled_regions = [name for name, region in cfg["regions"].items() if region.get("enabled")]
    if enabled_regions and launch_crawl(enabled_regions, trigger="manual_free_refresh"):
        patch_scheduler_state(last_free_refresh_at=datetime.utcnow().isoformat(), current_job="free_refresh")
    return redirect(request.referrer or url_for("config_page"))


@app.route("/events")
def events():
    return render_template("events.html", events=list_events())


@app.route("/watchlist")
def watchlist():
    return render_template("watchlist.html", events=list_events(watchlist_only=True))


@app.route("/free")
def free():
    return render_template("free.html", rows=list_free())


@app.route("/opportunities")
def opportunities():
    return render_template("opportunities.html", rows=list_opportunities())


@app.route("/activity")
def activity():
    return render_template("activity.html", rows=list_activity(200), crawl_runs=list_crawl_runs(30))


@app.route("/organizers")
def organizers():
    return render_template("organizers.html", rows=list_organizers())


@app.route("/event/<int:event_id>")
def event_detail(event_id):
    return render_template("event.html", event=get_event(event_id))


@app.route("/event/<int:event_id>/watchlist", methods=["POST"])
def toggle_watchlist(event_id):
    c = conn()
    c.execute("UPDATE events SET is_watchlisted = CASE WHEN COALESCE(is_watchlisted,0)=1 THEN 0 ELSE 1 END WHERE id=?", (event_id,))
    c.commit()
    c.close()
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/event/<int:event_id>/notes", methods=["POST"])
def save_event_notes(event_id):
    manual_status = (request.form.get("manual_status") or "").strip()
    private_note = (request.form.get("private_note") or "").strip()
    c = conn()
    c.execute("UPDATE events SET manual_status=?, private_note=? WHERE id=?", (manual_status, private_note, event_id))
    c.commit()
    c.close()
    return redirect(url_for("event_detail", event_id=event_id))


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
            "region_scan_frequency_minutes": request.form.get("region_scan_frequency_minutes", current.get("region_scan_frequency_minutes", 60)),
            "free_product_refresh_frequency_hours": request.form.get("free_product_refresh_frequency_hours", current.get("free_product_refresh_frequency_hours", 24)),
            "user_agent": request.form.get("user_agent", current["user_agent"]),
            "regions": regions,
        }
        save_config(new_config)
        return redirect(url_for("config_page", saved=1))
    saved = request.args.get("saved") == "1"
    scheduler_saved = request.args.get("scheduler_saved") == "1"
    return render_template("config.html", config=load_config(), saved=saved, scheduler_saved=scheduler_saved, scheduler_state=read_scheduler_state(), crawl_status=read_crawl_status())


@app.route("/api/events")
def api_events():
    return jsonify(list_events())


@app.route("/api/free")
def api_free():
    return jsonify(list_free())


@app.route("/api/opportunities")
def api_opportunities():
    return jsonify(list_opportunities())


@app.route("/api/activity")
def api_activity():
    return jsonify(list_activity())


@app.route("/api/config")
def api_config():
    return jsonify(load_config())


@app.route("/api/crawl_status")
def api_crawl_status():
    return jsonify(read_crawl_status())


@app.route("/api/scheduler_status")
def api_scheduler_status():
    return jsonify(read_scheduler_state())


init_db()
ensure_scheduler_thread()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
