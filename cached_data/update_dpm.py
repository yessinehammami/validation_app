"""DPM site (Tunisia) -> table dpm_produit_raw."""
import io
import sqlite3
from pathlib import Path

import requests
import pandas as pd

from maj_tables import DB_APP as DB, log_update
URL_XLS = "https://dpm.tn/images/pdf/liste_amm.xls"

COLUMNS = {
    "Nom": "nom", "Dosage": "dosage", "Forme": "forme", "Présentation": "presentation",
    "DCI": "dci", "Classe": "classe", "Sous Classe": "sous_classe",
    "Laboratoire": "laboratoire", "AMM": "amm", "Date AMM": "date_amm",
    "Conditionnement primaire": "conditionnement_primaire",
    "Spécifocation Conditionnement primaire": "specification_conditionnement_primaire",
    "tableau": "tableau", "Durée de conservation": "duree_conservation",
    "Indications": "indications", "G/P/B": "g_p_b", "VEIC": "veic",
}


def main():
    content = requests.get(URL_XLS, verify=False, timeout=120).content
    df = pd.read_excel(io.BytesIO(content), dtype=str)
    df = df[list(COLUMNS)].rename(columns=COLUMNS)

    conn = sqlite3.connect(DB)
    df.to_sql("dpm_produit_raw", conn, if_exists="replace", index=False)
    log_update(conn, "dpm_produit_raw", len(df))
    conn.commit()
    conn.close()
    print(f"dpm_produit_raw : {len(df)} lignes")


if __name__ == "__main__":
    main()
