import io
import sqlite3
import requests
import pandas as pd

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


content = requests.get(URL_XLS, verify=False).content
df = pd.read_excel(io.BytesIO(content), dtype=str)
df = df[list(COLUMNS)].rename(columns=COLUMNS)

# write to SQLite (the table is recreated each time)
conn = sqlite3.connect("amm_dpm.db")
df.to_sql("dpm_produit_raw", conn, if_exists="replace", index=False)
conn.close()