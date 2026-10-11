import io
import sqlite3
from pathlib import Path

import requests
import pandas as pd

DB = Path(__file__).with_name("cached_data.db")

# --- 1. DPM site (Tunisia) -> table dpm_produit_raw ---
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
df_dpm = pd.read_excel(io.BytesIO(content), dtype=str)
df_dpm = df_dpm[list(COLUMNS)].rename(columns=COLUMNS)

# --- 2. API Médicaments FR (BDPM) -> table table_rcp ---
# one call returns every medicine with its composition (CIS_bdpm + CIS_COMPO_bdpm)
URL_EXPORT = "https://medicaments-api.giygas.dev/v1/medicaments/export"

response = requests.get(URL_EXPORT, timeout=120)
response.raise_for_status()

rows = []
for med in response.json():
    # SA = active substance (FT = therapeutic fraction is ignored)
    substances = sorted({
        c["denominationSubstance"]
        for c in med.get("composition") or []
        if c.get("natureComposant") == "SA" and c.get("denominationSubstance")
    })
    for substance in substances or [None]:
        rows.append({
            "code_cis": str(med["cis"]),
            "denomination": med["elementPharmaceutique"],
            "substance": substance,
        })

df_rcp = pd.DataFrame(rows, columns=["code_cis", "denomination", "substance"])

# write to SQLite (the tables are recreated each time)
conn = sqlite3.connect(DB)
df_dpm.to_sql("dpm_produit_raw", conn, if_exists="replace", index=False)
df_rcp.to_sql("table_rcp", conn, if_exists="replace", index=False)
conn.execute("CREATE INDEX IF NOT EXISTS idx_table_rcp_cis ON table_rcp (code_cis)")
conn.commit()
conn.close()
