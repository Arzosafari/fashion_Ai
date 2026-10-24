#!/usr/bin/env python3
"""DB migration for GLOBAL trend module: add scope columns, isolate iranian history, ingest new sources."""
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path("./trends.db")
if not DB_PATH.exists():
    DB_PATH = Path("/home/user/trends.db")

def add_column_if_not_exists(conn, table, col, col_def):
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if col not in cols:
        print(f"Adding column {table}.{col} {col_def}")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
        conn.commit()
    else:
        print(f"Column {table}.{col} exists")

def main():
    if not DB_PATH.exists():
        print(f"No DB at {DB_PATH}, will be created on init")
        return
    print(f"Migrating DB at {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    # Add scope columns
    add_column_if_not_exists(conn, "sources", "scope", "TEXT DEFAULT 'global'")
    add_column_if_not_exists(conn, "sources", "source_region", "TEXT DEFAULT 'global'")
    add_column_if_not_exists(conn, "fashion_entities", "global_relevance", "REAL")
    add_column_if_not_exists(conn, "fashion_entities", "scope", "TEXT DEFAULT 'global'")
    add_column_if_not_exists(conn, "fashion_entities", "source_region", "TEXT")
    add_column_if_not_exists(conn, "trends", "trend_scope", "TEXT DEFAULT 'global'")
    add_column_if_not_exists(conn, "trends", "source_region", "TEXT DEFAULT 'global'")
    add_column_if_not_exists(conn, "trends", "semantic_consistency", "REAL")
    add_column_if_not_exists(conn, "trends", "recurrence_score", "REAL")
    # Check for historical Iranian trends: those from digikala/banimode sources; mark them iranian archived
    # Since trends table doesn't directly link to sources, we infer via explanation containing 'iranian' or via TrendEvidence
    conn.execute("UPDATE trends SET trend_scope = COALESCE(trend_scope, 'global')")
    conn.execute("UPDATE trends SET source_region = COALESCE(source_region, 'global')")
    # Mark existing trends as iranian if they contain Iranian evidence signature? Simpler: mark all existing as iranian archived before global run
    # But spec says isolate: new trends are global, old not deleted. So mark old with trend_scope='iranian' if scoring_version is old v1
    cur = conn.execute("SELECT canonical_name, scoring_version, trend_scope FROM trends")
    rows = cur.fetchall()
    for canon, ver, scope in rows:
        if ver and ver.startswith("v1") and scope == "global":
            # These were Iranian-era trends (pre-global)
            conn.execute("UPDATE trends SET trend_scope='iranian', source_region='iranian' WHERE canonical_name=?", (canon,))
            print(f"  Marked {canon} v={ver} as iranian archived")
        elif scope is None or scope == "global":
            # Keep as global? But existing were Iranian-era, so ensure they are iranian unless explicitly global trend like from vogue alone?
            # Heuristic: if explanation contains 'Iranian evidence' then iranian
            cur2 = conn.execute("SELECT explanation FROM trends WHERE canonical_name=?", (canon,))
            exp = cur2.fetchone()
            if exp and exp[0] and "Iranian evidence" in exp[0]:
                conn.execute("UPDATE trends SET trend_scope='iranian' WHERE canonical_name=?", (canon,))
                print(f"  Marked {canon} via explanation as iranian")
    conn.commit()

    # Ensure sources table will be refreshed from config via init
    # We can also directly upsert sources: mark old iranian sources as disabled/archived
    for src in ["digikala_mag", "banimode_mag", "modeworld"]:
        try:
            conn.execute("UPDATE sources SET enabled=0, scope='iranian', source_region='iranian' WHERE source_id=?", (src,))
            print(f"Disabled Iranian source {src}")
        except Exception as e:
            print(f"no sources table or source {src}: {e}")

    conn.commit()

    # Report counts
    cur = conn.execute("SELECT trend_scope, count(*) FROM trends GROUP BY trend_scope")
    print("Trend scope counts:", cur.fetchall())
    cur = conn.execute("SELECT source_id, enabled, scope FROM sources")
    print("Sources:", cur.fetchall())
    conn.close()
    print("Migration done")

if __name__ == "__main__":
    main()
