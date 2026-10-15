"""API Médicaments FR + BDPM CIS_COMPO -> table table_rcp (one row per CIS and active substance).

The BDPM composition file (SA = active substance, FT = therapeutic fraction, joined by
link number) is processed in memory.
"""
import io
import sqlite3

import requests
import pandas as pd

from maj_tables import DB_APP as DB, log_update

URL_EXPORT = "https://medicaments-api.giygas.dev/v1/medicaments/export"
URL_COMPO = "https://base-donnees-publique.medicaments.gouv.fr/download/file/CIS_COMPO_bdpm.txt"
COLUMNS = ["code_cis", "denomination", "forme", "substance", "dci", "code_substance"]
COMPO_COLUMNS = [
    "code_cis", "element_pharma", "code_substance", "denomination_substance",
    "dosage", "reference_dosage", "nature", "num_liaison",
]


def load_compo():
    response = requests.get(URL_COMPO, timeout=120)
    response.raise_for_status()
    compo = pd.read_csv(
        io.BytesIO(response.content), sep="\t", header=None, encoding="latin-1",
        dtype=str, usecols=range(8), names=COMPO_COLUMNS,
    )
    return compo.dropna(subset=["code_cis"]).drop_duplicates()


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
    compo = load_compo()

    response = requests.get(URL_EXPORT, timeout=120)
    response.raise_for_status()
    meds = pd.DataFrame(
        {
            "code_cis": str(m["cis"]),
            "denomination": m["elementPharmaceutique"],
            "forme": m.get("formePharmaceutique"),
        }
        for m in response.json()
    )

    df = meds.merge(build_substances(compo), on="code_cis", how="left")[COLUMNS]

    conn = sqlite3.connect(DB)
    df.to_sql("table_rcp", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_table_rcp_cis ON table_rcp (code_cis)")
    log_update(conn, "table_rcp", len(df))
    conn.commit()
    conn.close()
    print(f"table_rcp : {len(df)} lignes")


if __name__ == "__main__":
    main()
