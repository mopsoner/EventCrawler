"""Shared durable automatic-booking schema."""

MAX_BOOKING_ATTEMPTS = 3


def ensure_booking_jobs_schema(cur):
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS booking_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_key TEXT NOT NULL,
            product_name TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            claimed_at TEXT,
            finished_at TEXT,
            UNIQUE(event_id, product_key)
        );
        CREATE INDEX IF NOT EXISTS idx_booking_jobs_pending ON booking_jobs(state, created_at, id);
    """)


def recover_interrupted_booking_jobs(cur):
    cur.execute("""UPDATE booking_jobs SET state='pending', claimed_at=NULL,
                   last_error=COALESCE(last_error, 'worker interrupted')
                   WHERE state='running' AND attempt_count < ?
                     AND (claimed_at IS NULL OR claimed_at <= datetime('now', '-1 hour'))""",
                (MAX_BOOKING_ATTEMPTS,))
