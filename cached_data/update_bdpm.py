"""API Médicaments FR + compo_bdpm -> table table_rcp (one row per CIS and active substance).

Must run after update_compo.py (reads the compo_bdpm table).
"""
import sqlite3
from pathlib import Path

import requests
import pandas as pd

from maj_tables import log_update

DB = Path(__file__).with_name("cached_data.db")
URL_EXPORT = "https://medicaments-api.giygas.dev/v1/medicaments/export"
COLUMNS = ["code_cis", "denomination", "substance", "dci", "code_substance"]


def build_substances(compo):
    """One row per (CIS, SA) with the linked FT as dci (SA itself if no FT)."""
    key = ["code_cis", "element_pharma", "num_liaison"]
    sa = compo[compo["nature"] == "SA"]
    ft = (
        compo[compo["nature"] == "FT"]
        .sort_values("denomination_substance")
        .drop_duplicates(key)[key + ["denomination_substance"]]
        .rename(columns={"denomination_substance": "dci"})
    )
    merged = sa.merge(ft, on=key, how="left")
    merged["dci"] = merged["dci"].fillna(merged["denomination_substance"])
    merged = merged.rename(columns={"denomination_substance": "substance"})
    return (
        merged.sort_values(["code_cis", "substance"])
        .drop_duplicates(["code_cis", "substance"])[
            ["code_cis", "substance", "dci", "code_substance"]
        ]
    )


def main():
    conn = sqlite3.connect(DB)
    compo = pd.read_sql("SELECT * FROM compo_bdpm", conn, dtype=str)

    response = requests.get(URL_EXPORT, timeout=120)
    response.raise_for_status()
    meds = pd.DataFrame(
        {"code_cis": str(m["cis"]), "denomination": m["elementPharmaceutique"]}
        for m in response.json()
    )

    df = meds.merge(build_substances(compo), on="code_cis", how="left")[COLUMNS]

    df.to_sql("table_rcp", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_table_rcp_cis ON table_rcp (code_cis)")
    log_update(conn, "table_rcp", len(df))
    conn.commit()
    conn.close()
    print(f"table_rcp : {len(df)} lignes")


if __name__ == "__main__":
    main()
