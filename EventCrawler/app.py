import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, url_for

from ai_automation import enrich_event_labels, suggest_selector_repair
from config_store import load_config, save_config, slugify_region_name

DB_PATH = "data/eventcrawler.sqlite"
STATUS_PATH = Path("data/crawl_status.json")
SCHEDULER_STATE_PATH = Path("data/scheduler_state.json")
BOOKING_STATE_PATH = Path("data/booking_state.json")
BOOKING_FAILURES_DIR = Path("data/booking_failures")
BOOKING_SCRIPT_PATH = Path("booking_prepare.js")
NOISE_ORGANIZER_HOSTS = {
    "bizouk.com",
    "www.bizouk.com",
    "maps.google.com",
    "www.google.com",
    "google.com",
    "gov.uk",
    "www.gov.uk",
}
app = Flask(__name__)
app.secret_key = "eventcrawler-local"
CRAWL_PROCESS = None
CRAWL_LOCK = threading.Lock()
SCHEDULER_THREAD = None
SCHEDULER_THREAD_LOCK = threading.Lock()
SCHEDULER_LOOP_SECONDS = 30
BOOKING_PROCESS = None
BOOKING_LOCK = threading.Lock()


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
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_started_at TEXT,
            booked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            event_id INTEGER,
            event_url TEXT,
            event_name TEXT,
            event_date TEXT,
            region TEXT,
            product_name TEXT,
            ticket_count INTEGER DEFAULT 1,
            email TEXT,
            status TEXT,
            confirmation_text TEXT,
            UNIQUE(booking_started_at, event_url, product_name, email)
        );
        CREATE TABLE IF NOT EXISTS booking_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            failure_key TEXT UNIQUE,
            booking_started_at TEXT,
            event_url TEXT,
            product_name TEXT,
            step_name TEXT,
            intent TEXT,
            error_text TEXT,
            page_url TEXT,
            page_title TEXT,
            html_excerpt TEXT,
            visible_text_excerpt TEXT,
            tried_selectors_json TEXT,
            ai_suggestion_json TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS selector_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intent TEXT NOT NULL,
            selectors_json TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            confidence REAL DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            is_enabled INTEGER DEFAULT 1,
            last_validated_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_ai_labels (
            event_id INTEGER PRIMARY KEY,
            language TEXT,
            summary_short TEXT,
            event_type TEXT,
            genres_json TEXT,
            audience_tags_json TEXT,
            confidence REAL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        '''
    )
    ensure_column(cur, "events", "event_external_id", "event_external_id TEXT")
    ensure_column(cur, "events", "event_slug", "event_slug TEXT")
    ensure_column(cur, "events", "contact_website", "contact_website TEXT")
    ensure_column(cur, "events", "event_image", "event_image TEXT")
    ensure_column(cur, "events", "subtitle", "subtitle TEXT")
    ensure_column(cur, "events", "description", "description TEXT")
    ensure_column(cur, "events", "manual_status", "manual_status TEXT")
    ensure_column(cur, "events", "private_note", "private_note TEXT")
    ensure_column(cur, "events", "is_watchlisted", "is_watchlisted INTEGER DEFAULT 0")
    ensure_column(cur, "products", "family_key", "family_key TEXT")
    ensure_column(cur, "products", "early_bird_score", "early_bird_score INTEGER DEFAULT 0")
    ensure_column(cur, "products", "is_early_bird", "is_early_bird INTEGER DEFAULT 0")
    ensure_column(cur, "products", "early_bird_confidence", "early_bird_confidence TEXT")
    ensure_column(cur, "products", "early_bird_reason", "early_bird_reason TEXT")
    c.commit()
    c.close()


def default_scheduler_state():
    return {"enabled": False, "last_region_scan_at": None, "last_free_refresh_at": None, "current_job": None, "updated_at": None}


def default_booking_state():
    return {"running": False, "status": "idle", "mode": "auto_confirm", "event_url": None, "product_name": None, "ticket_count": 0, "email": None, "started_at": None, "finished_at": None, "last_error": None, "log_path": "data/booking.log", "confirmation_text": None}


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


def save_selector_rule(intent, selectors, source="manual", confidence=0.0):
    selectors = [str(s).strip() for s in (selectors or []) if str(s).strip()]
    if not intent or not selectors:
        return
    normalized_json = json.dumps(selectors, ensure_ascii=False)
    c = conn()
    try:
        existing = c.execute("SELECT id FROM selector_rules WHERE intent=? AND selectors_json=?", (intent, normalized_json)).fetchone()
        if existing:
            c.execute(
                "UPDATE selector_rules SET source=?, confidence=?, last_validated_at=?, is_enabled=1 WHERE id=?",
                (source, float(confidence or 0), datetime.utcnow().isoformat(), existing["id"]),
            )
        else:
            c.execute(
                "INSERT INTO selector_rules(intent, selectors_json, source, confidence, is_enabled, last_validated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (intent, normalized_json, source, float(confidence or 0), 1, datetime.utcnow().isoformat()),
            )
        c.commit()
    finally:
        c.close()


def reanalyze_failure_row(row):
    suggestion = suggest_selector_repair(dict(row))
    if not suggestion:
        return False
    c = conn()
    try:
        c.execute(
            "UPDATE booking_failures SET ai_suggestion_json=?, status=? WHERE id=?",
            (json.dumps(suggestion, ensure_ascii=False), "suggested", row["id"]),
        )
        intent = suggestion.get("intent")
        selectors = suggestion.get("candidate_selectors") or []
        if intent and selectors:
            save_selector_rule(intent, selectors, source="ai_reanalyze", confidence=float(suggestion.get("confidence") or 0))
            c.execute("UPDATE booking_failures SET status=? WHERE id=?", ("validated", row["id"]))
        c.commit()
        return True
    finally:
        c.close()


def upsert_failure_report(report: dict):
    failure_key = report.get("failure_key") or report.get("booking_started_at") or f"failure-{time.time()}"
    tried_json = json.dumps(report.get("tried_selectors") or [], ensure_ascii=False)
    c = conn()
    try:
        c.execute(
            "INSERT OR IGNORE INTO booking_failures(failure_key, booking_started_at, event_url, product_name, step_name, intent, error_text, page_url, page_title, html_excerpt, visible_text_excerpt, tried_selectors_json, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (failure_key, report.get("booking_started_at"), report.get("event_url"), report.get("product_name"), report.get("step_name"), report.get("intent"), report.get("error_text"), report.get("page_url"), report.get("page_title"), report.get("html_excerpt"), report.get("visible_text_excerpt"), tried_json, "new"),
        )
        row = c.execute("SELECT * FROM booking_failures WHERE failure_key=?", (failure_key,)).fetchone()
    finally:
        c.commit()
        c.close()
    if row and row["status"] == "new":
        reanalyze_failure_row(row)


def sync_booking_failures_from_disk():
    BOOKING_FAILURES_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(BOOKING_FAILURES_DIR.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(report, dict):
                upsert_failure_report(report)
        except Exception:
            continue


def sync_ticket_from_booking_state(state=None):
    state = state or read_booking_state(raw=True)
    if state.get("status") not in {"confirmed", "submitted_unconfirmed"}:
        return
    event_url = (state.get("event_url") or "").strip()
    product_name = (state.get("product_name") or "").strip()
    email = (state.get("email") or "").strip().lower()
    booking_started_at = state.get("started_at") or state.get("finished_at") or datetime.utcnow().isoformat()
    if not event_url or not product_name or not email:
        return
    c = conn()
    event = c.execute("SELECT id, name, event_date, region FROM events WHERE event_url=?", (event_url,)).fetchone()
    try:
        c.execute(
            "INSERT OR IGNORE INTO tickets(booking_started_at, booked_at, event_id, event_url, event_name, event_date, region, product_name, ticket_count, email, status, confirmation_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (booking_started_at, state.get("finished_at") or datetime.utcnow().isoformat(), event["id"] if event else None, event_url, event["name"] if event else event_url, event["event_date"] if event else None, event["region"] if event else None, product_name, int(state.get("ticket_count") or 1), email, state.get("status"), state.get("confirmation_text")),
        )
        c.commit()
    finally:
        c.close()


def read_booking_state(raw=False):
    if not BOOKING_STATE_PATH.exists():
        return default_booking_state()
    try:
        data = json.loads(BOOKING_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = default_booking_state()
    state = default_booking_state()
    state.update(data if isinstance(data, dict) else {})
    if not raw:
        sync_ticket_from_booking_state(state)
        sync_booking_failures_from_disk()
    return state


def booking_is_running():
    global BOOKING_PROCESS
    return bool(BOOKING_PROCESS and BOOKING_PROCESS.poll() is None)


def selector_rules_env():
    c = conn()
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM selector_rules WHERE COALESCE(is_enabled,1)=1 ORDER BY confidence DESC, id DESC").fetchall()]
    finally:
        c.close()
    grouped = {}
    for row in rows:
        try:
            selectors = json.loads(row.get("selectors_json") or "[]")
        except Exception:
            selectors = []
        if not selectors:
            continue
        grouped.setdefault(row["intent"], [])
        for sel in selectors:
            if sel not in grouped[row["intent"]]:
                grouped[row["intent"]].append(sel)
    return grouped


def launch_booking_prepare(event_url: str, ticket_count: int, email: str, product_name: str):
    global BOOKING_PROCESS
    with BOOKING_LOCK:
        if BOOKING_PROCESS and BOOKING_PROCESS.poll() is None:
            return False
        cfg = load_config()
        profile = cfg.get("booking_profile", {})
        log_path = Path("data/booking_runner.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["BOOKING_FIRST_NAME"] = str(profile.get("first_name") or "Olivier")
        env["BOOKING_LAST_NAME"] = str(profile.get("last_name") or "Mops")
        env["BOOKING_FULL_NAME"] = str(profile.get("full_name") or f"{profile.get('first_name', 'Olivier')} {profile.get('last_name', 'Mops')}")
        env["BOOKING_PHONE"] = str(profile.get("phone") or "0691243236")
        env["BOOKING_GENDER"] = str(profile.get("gender") or "Homme")
        env["BOOKING_SELECTOR_RULES_JSON"] = json.dumps(selector_rules_env(), ensure_ascii=False)
        BOOKING_PROCESS = subprocess.Popen([
            "node", str(BOOKING_SCRIPT_PATH), "--event-url", event_url, "--ticket-count", str(ticket_count), "--email", email, "--product-name", product_name
        ], env=env, stdout=log_file, stderr=subprocess.STDOUT)
        return True


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


def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    return digits if len(digits) >= 9 else None


def normalize_email(value):
    value = (value or "").strip().lower()
    return value or None


def normalize_website(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
    except Exception:
        return None
    host = (parsed.netloc or parsed.path or "").strip().lower()
    if not host:
        return None
    if "/" in host:
        host = host.split("/", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    if host in {h.replace('www.', '') for h in NOISE_ORGANIZER_HOSTS}:
        return None
    if host.endswith("google.com") or host.endswith("gov.uk"):
        return None
    return host


def organizer_identity(row):
    phone = normalize_phone(row.get("contact_phone"))
    if phone:
        return (f"phone:{phone}", "phone", phone)
    email = normalize_email(row.get("contact_email"))
    if email:
        return (f"email:{email}", "email", email)
    website = normalize_website(row.get("contact_website"))
    if website:
        return (f"website:{website}", "website", website)
    return (None, None, None)


def has_column(table, column):
    c = conn()
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    c.close()
    return column in cols


def decorate_rows(rows):
    for row in rows:
        row["added_at"] = row.get("first_seen_at") or row.get("event_first_seen") or row.get("booked_at")
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
        "tickets": cur.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
        "failures": cur.execute("SELECT COUNT(*) FROM booking_failures").fetchone()[0],
        "organizers": 0,
        "last_seen_at": cur.execute("SELECT MAX(last_seen_at) FROM events").fetchone()[0],
    }
    c.close()
    out["organizers"] = len(list_organizers())
    return out


def list_events(limit=None, watchlist_only=False):
    c = conn()
    select_cols = "id, event_url, region, name, subtitle, description, event_date, city, address, contact_phone, contact_email, contact_website, first_seen_at, score, manual_status, private_note, is_watchlisted"
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
    select_cols = "p.*, e.name AS event_name, e.subtitle AS event_subtitle, e.description AS event_description, e.event_date AS event_date, e.region, e.event_url, e.first_seen_at AS event_first_seen, e.score, e.id AS event_id, e.manual_status AS manual_status, e.is_watchlisted AS is_watchlisted"
    if has_column("events", "event_image"):
        select_cols += ", e.event_image AS event_image"
    sql = f"SELECT {select_cols} FROM products p JOIN events e ON e.id = p.event_id WHERE p.is_free = 1 AND COALESCE(p.numeric_price, -1) = 0 ORDER BY p.last_seen_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in c.execute(sql).fetchall()]
    c.close()
    return decorate_rows(rows)


def list_tickets(limit=None):
    c = conn()
    sql = "SELECT * FROM tickets ORDER BY booked_at DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in c.execute(sql).fetchall()]
    c.close()
    return decorate_rows(rows)


def list_failures(limit=200):
    sync_booking_failures_from_disk()
    c = conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM booking_failures ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()]
    c.close()
    for row in rows:
        row["created_ago"] = time_ago(row.get("created_at"))
        try:
            row["tried_selectors"] = json.loads(row.get("tried_selectors_json") or "[]")
        except Exception:
            row["tried_selectors"] = []
        try:
            row["ai_suggestion"] = json.loads(row.get("ai_suggestion_json") or "{}")
        except Exception:
            row["ai_suggestion"] = {}
    return rows


def list_selector_rules(limit=200):
    c = conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM selector_rules ORDER BY is_enabled DESC, confidence DESC, id DESC LIMIT ?", (limit,)).fetchall()]
    failure_counts = {r[0]: r[1] for r in c.execute("SELECT intent, COUNT(*) FROM booking_failures GROUP BY intent").fetchall()}
    c.close()
    for row in rows:
        try:
            row["selectors"] = json.loads(row.get("selectors_json") or "[]")
        except Exception:
            row["selectors"] = []
        row["created_ago"] = time_ago(row.get("created_at"))
        row["selectors_count"] = len(row["selectors"])
        row["failures_for_intent"] = int(failure_counts.get(row.get("intent"), 0))
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


def list_activity(limit=100):
    c = conn()
    sql = '''SELECT ph.*, e.name AS event_name, e.region, e.event_url, e.id AS event_id FROM product_history ph LEFT JOIN events e ON e.id = ph.event_id ORDER BY ph.observed_at DESC LIMIT ?'''
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
    events = list_events()
    c = conn()
    free_event_ids = {r[0] for r in c.execute("SELECT DISTINCT event_id FROM products WHERE COALESCE(numeric_price, -1)=0 AND is_free=1").fetchall()}
    c.close()
    groups = {}
    for event in events:
        organizer_key, organizer_type, organizer_value = organizer_identity(event)
        if not organizer_key:
            continue
        group = groups.setdefault(organizer_key, {"organizer_key": organizer_value, "organizer_type": organizer_type, "sample_event_name": event.get("name"), "events_count": 0, "free_event_count": 0, "last_seen_at": event.get("first_seen_at"), "contact_phone": normalize_phone(event.get("contact_phone")) or event.get("contact_phone"), "contact_email": normalize_email(event.get("contact_email")) or event.get("contact_email"), "contact_website": normalize_website(event.get("contact_website")) or event.get("contact_website")})
        group["events_count"] += 1
        if event.get("id") in free_event_ids:
            group["free_event_count"] += 1
        if event.get("first_seen_at") and (not group["last_seen_at"] or str(event.get("first_seen_at")) > str(group["last_seen_at"])):
            group["last_seen_at"] = event.get("first_seen_at")
    rows = list(groups.values())
    for row in rows:
        row["last_seen_ago"] = time_ago(row.get("last_seen_at"))
    rows.sort(key=lambda x: (x.get("free_event_count", 0), x.get("events_count", 0), x.get("last_seen_at") or ""), reverse=True)
    return rows


def enrich_event_now(event_id):
    c = conn()
    try:
        event = c.execute("SELECT id, event_url, region, name, subtitle, description, event_date FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            return False
        products = [dict(r) for r in c.execute("SELECT product_name, price_text, numeric_price, is_free, is_available FROM products WHERE event_id=? ORDER BY last_seen_at DESC", (event_id,)).fetchall()]
        payload = dict(event)
        payload["products"] = products
        labels = enrich_event_labels(payload)
        c.execute(
            "INSERT OR REPLACE INTO event_ai_labels(event_id, language, summary_short, event_type, genres_json, audience_tags_json, confidence, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (event_id, labels.get("language"), labels.get("summary_short"), labels.get("event_type"), json.dumps(labels.get("genres_json") or [], ensure_ascii=False), json.dumps(labels.get("audience_tags_json") or [], ensure_ascii=False), float(labels.get("confidence") or 0)),
        )
        c.commit()
        return True
    finally:
        c.close()


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
    ai_row = c.execute("SELECT * FROM event_ai_labels WHERE event_id=?", (event_id,)).fetchone()
    out["ai_labels"] = None
    if ai_row:
        ai = dict(ai_row)
        try:
            ai["genres"] = json.loads(ai.get("genres_json") or "[]")
        except Exception:
            ai["genres"] = []
        try:
            ai["audience_tags"] = json.loads(ai.get("audience_tags_json") or "[]")
        except Exception:
            ai["audience_tags"] = []
        out["ai_labels"] = ai
    for row in out["history"]:
        row["observed_ago"] = time_ago(row.get("observed_at"))
    c.close()
    return out


def scheduler_tick():
    state = read_scheduler_state()
    if not state.get("enabled") or crawl_is_running():
        return
    cfg = load_config()
    enabled_regions = [name for name, region in cfg["regions"].items() if region.get("enabled")]
    if not enabled_regions:
        return
    region_due = is_due(state.get("last_region_scan_at"), minutes=int(cfg.get("region_scan_frequency_minutes", 60)))
    free_due = is_due(state.get("last_free_refresh_at"), hours=int(cfg.get("free_product_refresh_frequency_hours", 24)))
    if region_due and launch_crawl(enabled_regions, trigger="scheduler_region_scan"):
        patch_scheduler_state(last_region_scan_at=datetime.utcnow().isoformat(), current_job="region_scan")
        return
    if free_due and launch_crawl(enabled_regions, trigger="scheduler_free_refresh"):
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


@app.route("/")
def dashboard():
    cfg = load_config()
    return render_template("dashboard.html", stats=stats(), config=cfg, crawl_status=read_crawl_status(), scheduler_state=read_scheduler_state(), top_events=list_events(limit=6), top_opportunities=list_opportunities(limit=8), watchlist_events=list_events(limit=6, watchlist_only=True), recent_activity=list_activity(limit=8), recent_runs=list_crawl_runs(limit=6))


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


@app.route("/booking/prepare", methods=["POST"])
def booking_prepare():
    data = request.get_json(silent=True) or request.form
    cfg = load_config()
    profile = cfg.get("booking_profile", {})
    event_url = (data.get("event_url") or "").strip()
    product_name = (data.get("product_name") or "").strip()
    email = (data.get("email") or profile.get("email") or "contact@sejourcarnaval.com").strip()
    try:
        ticket_count = max(1, int(data.get("ticket_count", profile.get("default_ticket_count", 2))))
    except Exception:
        ticket_count = int(profile.get("default_ticket_count", 2) or 2)
    if not event_url or not product_name:
        return jsonify({"status": "error", "message": "missing event_url or product_name"}), 400
    started = launch_booking_prepare(event_url, ticket_count, email, product_name)
    return jsonify({"status": "started" if started else "busy", "state": read_booking_state()})


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
    return render_template("free.html", rows=list_free(), booking_state=read_booking_state())


@app.route("/tickets")
def tickets():
    return render_template("tickets.html", rows=list_tickets())


@app.route("/failures")
def failures():
    return render_template("failures.html", failures=list_failures(), rules=list_selector_rules())


@app.route("/failures/<int:failure_id>/reanalyze", methods=["POST"])
def reanalyze_failure(failure_id):
    c = conn()
    try:
        row = c.execute("SELECT * FROM booking_failures WHERE id=?", (failure_id,)).fetchone()
    finally:
        c.close()
    if row:
        reanalyze_failure_row(row)
    return redirect(request.referrer or url_for("failures"))


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


@app.route("/event/<int:event_id>/refresh-ai", methods=["POST"])
def refresh_event_ai(event_id):
    enrich_event_now(event_id)
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/selector-rules/<int:rule_id>/toggle", methods=["POST"])
def toggle_selector_rule(rule_id):
    c = conn()
    c.execute("UPDATE selector_rules SET is_enabled = CASE WHEN COALESCE(is_enabled,1)=1 THEN 0 ELSE 1 END WHERE id=?", (rule_id,))
    c.commit()
    c.close()
    return redirect(request.referrer or url_for("failures"))


@app.route("/config", methods=["GET", "POST"])
def config_page():
    if request.method == "POST":
        current = load_config()
        regions = {}
        region_names = request.form.getlist("region_names")
        for raw_name in region_names:
            name = slugify_region_name(raw_name)
            if not name:
                continue
            if request.form.get(f"region_delete_{name}") == "on":
                continue
            previous = current["regions"].get(name, {})
            url_value = (request.form.get(f"region_url_{name}", previous.get("url", "")) or "").strip()
            if not url_value:
                continue
            regions[name] = {"enabled": request.form.get(f"region_enabled_{name}") == "on", "url": url_value}
        new_region_name = slugify_region_name(request.form.get("new_region_name", ""))
        new_region_url = (request.form.get("new_region_url") or "").strip()
        if new_region_name and new_region_url:
            regions[new_region_name] = {"enabled": request.form.get("new_region_enabled") == "on", "url": new_region_url}
        new_config = {
            "max_workers": request.form.get("max_workers", current["max_workers"]),
            "request_timeout": request.form.get("request_timeout", current["request_timeout"]),
            "region_scan_frequency_minutes": request.form.get("region_scan_frequency_minutes", current.get("region_scan_frequency_minutes", 60)),
            "free_product_refresh_frequency_hours": request.form.get("free_product_refresh_frequency_hours", current.get("free_product_refresh_frequency_hours", 24)),
            "user_agent": request.form.get("user_agent", current["user_agent"]),
            "booking_profile": {
                "first_name": request.form.get("booking_first_name", current.get("booking_profile", {}).get("first_name", "Olivier")),
                "last_name": request.form.get("booking_last_name", current.get("booking_profile", {}).get("last_name", "Mops")),
                "full_name": request.form.get("booking_full_name", current.get("booking_profile", {}).get("full_name", "Olivier Mops")),
                "phone": request.form.get("booking_phone", current.get("booking_profile", {}).get("phone", "0691243236")),
                "gender": request.form.get("booking_gender", current.get("booking_profile", {}).get("gender", "Homme")),
                "email": request.form.get("booking_email", current.get("booking_profile", {}).get("email", "contact@sejourcarnaval.com")),
                "default_ticket_count": request.form.get("booking_default_ticket_count", current.get("booking_profile", {}).get("default_ticket_count", 2)),
            },
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


@app.route("/api/tickets")
def api_tickets():
    return jsonify(list_tickets())


@app.route("/api/failures")
def api_failures():
    return jsonify(list_failures())


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


@app.route("/api/booking_status")
def api_booking_status():
    return jsonify(read_booking_state())


init_db()
ensure_scheduler_thread()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
