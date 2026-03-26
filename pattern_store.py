from db import get_conn


def save_learned_pattern(page_type: str, pattern_name: str, pattern_value: str, confidence: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO learned_patterns (page_type, pattern_name, pattern_value, confidence, updated_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (page_type, pattern_name, pattern_value, confidence),
    )
    conn.commit()
    conn.close()


def list_patterns(page_type: str | None = None):
    conn = get_conn()
    cur = conn.cursor()
    if page_type:
        cur.execute("SELECT page_type, pattern_name, pattern_value, confidence, updated_at FROM learned_patterns WHERE page_type = ? ORDER BY confidence DESC", (page_type,))
    else:
        cur.execute("SELECT page_type, pattern_name, pattern_value, confidence, updated_at FROM learned_patterns ORDER BY page_type, confidence DESC")
    rows = cur.fetchall()
    conn.close()
    return rows
