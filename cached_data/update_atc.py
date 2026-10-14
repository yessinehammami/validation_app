"""BioPortal ATC ontology -> table atc."""
import io
import sqlite3
from pathlib import Path

import requests
import pandas as pd

from maj_tables import log_update

DB = Path(__file__).with_name("cached_data.db")
URL = "https://data.bioontology.org/ontologies/ATC/download?download_format=csv&apikey=8b5b7825-538d-40e0-9e9e-5ab9274a9aeb"


def main():
    response = requests.get(URL, timeout=300)
    response.raise_for_status()
    atc = pd.read_csv(io.BytesIO(response.content), compression="gzip", low_memory=False)

    atc = atc.rename(columns={
        "Class ID": "code", "Preferred Label": "inn", "Synonyms": "synonyms",
        "Parents": "parent_code", "ATC LEVEL": "level", "Is Drug Class": "is_drug_class",
    })

    # URL BioPortal -> code ATC seul (…/ATC/D11AX06 -> D11AX06)
    atc["code"] = atc["code"].str.rsplit("/", n=1).str[-1]
    atc["parent_code"] = atc["parent_code"].str.rsplit("/", n=1).str[-1]

    atc["level"] = atc["level"].astype("Int64")
    atc["inn"] = atc["inn"].str.lower().str.strip()
    atc["synonyms"] = atc["synonyms"].str.lower()   # séparés par "|"

    atc = atc[["code", "inn", "parent_code", "level"]]

    conn = sqlite3.connect(DB)
    atc.to_sql("atc", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atc_code ON atc (code)")
    log_update(conn, "atc", len(atc))
    conn.commit()
    conn.close()
    print(f"atc : {len(atc)} lignes")


if __name__ == "__main__":
    main()

