import os
import sqlite3

import pandas as pd
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

from common import DB, load_rcp, normalize, specialites_pour_dci

BASE = "https://medicaments-api.giygas.dev"

st.title("Résumé Caractéristiques Produits (France)")
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

rcp_df = load_rcp()
dci_liste = sorted(rcp_df["dci"].dropna().unique())
_dcis = [normalize(s) for s in dci_liste]


def suggest_dci(term):
    t = normalize(term)
    return [s for s, n in zip(dci_liste, _dcis) if t in n][:20]


dci_choisie = st_searchbox(
    suggest_dci,
    key="sb_dci",
    default_options=suggest_dci(""),
    placeholder="Ou filtrez par DCI (ex: amoxicilline)",
)

dci = st.session_state.get("rcp_dci")
if dci or dci_choisie:
    if dci_choisie:
        specs = rcp_df[rcp_df["dci"] == dci_choisie][["code_cis", "denomination", "forme"]]
        specs = specs.drop_duplicates().sort_values("denomination").reset_index(drop=True)
        titre = dci_choisie
    else:
        specs = specialites_pour_dci(rcp_df, dci)
        titre = dci
    st.divider()
    st.subheader(f"Spécialités contenant : {titre}")
    if dci and not dci_choisie and st.button("✖ Retirer le filtre DCI"):
        del st.session_state["rcp_dci"]
        st.rerun()
    specs["forme"] = specs["forme"].fillna("Non renseignée")
    formes = sorted(specs["forme"].unique())
    formes_choisies = st.multiselect(
        "Filtrer par forme pharmaceutique", formes, placeholder="Toutes les formes"
    )
    if formes_choisies:
        specs = specs[specs["forme"].isin(formes_choisies)].reset_index(drop=True)
    st.write(f"{len(specs)} spécialité(s)")
    # toutes les DCI de chaque spécialité, puis regroupement par combinaison identique
    subs = (
        rcp_df[rcp_df["code_cis"].isin(specs["code_cis"])]
        .groupby("code_cis")["dci"]
        .agg(lambda s: " + ".join(sorted(set(s.dropna()))) or "-")
    )
    specs = specs.assign(substances=specs["code_cis"].map(subs).fillna("-"))
    groupes = list(specs.groupby("substances", sort=True))
    groupes.sort(key=lambda g: -len(g[1]))
    st.write(f"{len(groupes)} groupe(s) de DCI")
    for i, (combinaison, groupe) in enumerate(groupes):
        groupe = groupe.reset_index(drop=True)
        with st.expander(f"{combinaison} — {len(groupe)} spécialité(s)"):
            event = st.dataframe(
                groupe[["denomination"]],
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"grp_{i}",
            )
            if event.selection.rows:
                cis = groupe.iloc[event.selection.rows[0]]["code_cis"]
    st.divider()

if not cis:
    st.info("Choisissez un médicament dans la liste ou dans la recherche.")
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
