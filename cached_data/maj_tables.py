"""Records the last update of each table in the single table maj_tables.

Two databases: cached_data.db (read by the app, committed) and build.db (reference
tables only needed to build the former, not committed).
"""
from pathlib import Path

DB_APP = Path(__file__).with_name("cached_data.db")
DB_BUILD = Path(__file__).with_name("build.db")


def log_update(conn, table_name, n_lignes):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS maj_tables "
        "(table_name TEXT PRIMARY KEY, updated_at TEXT, n_lignes INTEGER)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO maj_tables VALUES (?, datetime('now'), ?)",
        (table_name, n_lignes),
    )
