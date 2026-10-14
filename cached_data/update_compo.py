"""BDPM CIS_COMPO_bdpm.txt -> table compo_bdpm (raw composition, SA/FT with link number)."""
import io
import sqlite3
from pathlib import Path

import requests
import pandas as pd

from maj_tables import log_update

DB = Path(__file__).with_name("cached_data.db")
URL = "https://base-donnees-publique.medicaments.gouv.fr/download/file/CIS_COMPO_bdpm.txt"
COLUMNS = [
    "code_cis", "element_pharma", "code_substance", "denomination_substance",
    "dosage", "reference_dosage", "nature", "num_liaison",
]


def main():
    response = requests.get(URL, timeout=120)
    response.raise_for_status()

    df = pd.read_csv(
        io.BytesIO(response.content),
        sep="\t",
        header=None,
        encoding="latin-1",
        dtype=str,
        usecols=range(8),
        names=COLUMNS,
    )
    df = df.dropna(subset=["code_cis"]).drop_duplicates()

    conn = sqlite3.connect(DB)
    df.to_sql("compo_bdpm", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_compo_bdpm_cis ON compo_bdpm (code_cis)")
    log_update(conn, "compo_bdpm", len(df))
    conn.commit()
    conn.close()
    print(f"compo_bdpm : {len(df)} lignes")


if __name__ == "__main__":
    main()
