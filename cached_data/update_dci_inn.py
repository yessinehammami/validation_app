"""WCO INN/DCI list (EN <-> FR) -> table inn_dci."""
import io
import sqlite3
from pathlib import Path

import requests
import pandas as pd

from maj_tables import DB_BUILD as DB, log_update

URL = "https://www.wcoomd.org/-/media/wco/public/global/excel/inn-dci-list.xlsx?db=web"


def main():
    response = requests.get(URL, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    if not response.content.startswith(b"PK"):  # an xlsx is a zip file
        raise SystemExit("Le fichier téléchargé n'est pas un xlsx valide")

    df = pd.read_excel(io.BytesIO(response.content), header=2)
    df = df[["Product (En)", "Produit (Fr)"]]
    df = df.rename(columns={"Product (En)": "inn", "Produit (Fr)": "dci"})

    conn = sqlite3.connect(DB)
    df.to_sql("inn_dci", conn, if_exists="replace", index=False)
    log_update(conn, "inn_dci", len(df))
    conn.commit()
    conn.close()
    print(f"inn_dci : {len(df)} lignes")


if __name__ == "__main__":
    main()
