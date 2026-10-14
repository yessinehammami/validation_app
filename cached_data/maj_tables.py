"""Records the last update of each table in the single table maj_tables."""


def log_update(conn, table_name, n_lignes):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS maj_tables "
        "(table_name TEXT PRIMARY KEY, updated_at TEXT, n_lignes INTEGER)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO maj_tables VALUES (?, datetime('now'), ?)",
        (table_name, n_lignes),
    )
