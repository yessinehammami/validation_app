import os
import sqlite3

import pandas as pd
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

from common import DB, normalize

BASE = "https://medicaments-api.giygas.dev"

st.title("Données RCP")
st.caption("Source : API Médicaments FR (BDPM / ANSM) - liste des médicaments : cached_data.db")


@st.cache_data(ttl=3600, show_spinner=False)
def api_get(path, **params):
    r = requests.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


@st.cache_data
def load_medicaments(file_time):
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT DISTINCT code_cis, denomination FROM table_rcp", conn)
    conn.close()
    df["_denomination"] = df["denomination"].map(normalize)
    return df.sort_values("denomination").reset_index(drop=True)


medicaments = load_medicaments(os.path.getmtime(DB))


def suggest(term):
    matches = medicaments[medicaments["_denomination"].str.startswith(normalize(term))]
    return list(zip(matches["denomination"], matches["code_cis"]))[:20]


cis = st_searchbox(
    suggest,
    key="sb_rcp",
    default_options=suggest(""),
    placeholder="Tapez un médicament (ex: doliprane)",
)

if not cis:
    st.info("Commencez à taper, puis choisissez un médicament.")
    st.stop()

try:
    med = api_get(f"/v1/medicaments/{cis}")
    rcp = api_get(f"/v1/medicaments/{cis}/rcp")
except requests.RequestException as e:
    st.error(f"Erreur lors de l'appel à l'API : {e}")
    st.stop()

st.subheader(med["elementPharmaceutique"])
col1, col2, col3 = st.columns(3)
col1.write(f"**Forme :** {med.get('formePharmaceutique') or '-'}")
col2.write(f"**Titulaire :** {med.get('titulaire') or '-'}")
col3.write(f"**Statut :** {med.get('statusAutorisation') or '-'}")

substances = [
    f"{c['denominationSubstance']} ({c['dosage']})"
    for c in med.get("composition") or []
    if c.get("natureComposant") == "SA"
]
st.write("**Substances actives :** " + (", ".join(substances) or "-"))

st.divider()
st.caption(f"RCP mis à jour le {rcp.get('miseAJour', '-')} - {rcp.get('source', '')}")
for section in rcp.get("sections", []):
    with st.expander(section["titre"]):
        st.html(section["contenu"])

with st.expander("Réponse JSON brute (test)"):
    st.json({"medicament": med, "rcp": rcp}, expanded=False)
