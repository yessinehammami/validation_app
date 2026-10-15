import os
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

DB = Path(__file__).parent / "cached_data" / "cached_data.db"


def normalize(text):
    """minuscules et sans accents : 'paracétamol' trouve 'paracetamol'"""
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def make_label(row):
    parts = [row["nom"], row["dosage"], row["forme"]]
    return " | ".join(str(p).strip() for p in parts if pd.notna(p) and str(p).strip())


@st.cache_data
def _load(file_time):
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM dpm_produit_raw", conn)
    conn.close()
    df["label"] = df.apply(make_label, axis=1)
    df["_label"] = df["label"].map(normalize)
    df["_dci"] = df["dci"].fillna("").map(normalize)
    return df


def load_data():
    file_time = os.path.getmtime(DB)   # recharge si reference.db change
    return _load(file_time), file_time


def search(df, column, query):
    """garde les lignes où chaque mot tapé apparaît dans la colonne"""
    for word in normalize(query).split():
        df = df[df[column].str.contains(word, regex=False)]
    return df


def suggestions(df, norm_col, label_col, term, limit=20):
    """valeurs distinctes de label_col qui commencent par ce qui est tapé"""
    norm_term = normalize(term)
    matches = df[df[norm_col].str.startswith(norm_term)]
    return matches[label_col].dropna().drop_duplicates().sort_values().head(limit).tolist()


@st.cache_data
def _load_rcp(file_time):
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code_cis, denomination, forme, substance, dci FROM table_rcp", conn)
    conn.close()
    df["_dci"] = df["dci"].fillna("").map(normalize)
    return df


def load_rcp():
    return _load_rcp(os.path.getmtime(DB))


def specialites_pour_dci(rcp, dci):
    """spécialités dont la composition correspond exactement à la DCI DPM ('A+B' = A et B, rien d'autre)"""
    parts = [p for p in (normalize(p).strip() for p in str(dci).split("+")) if p]
    cis = None
    hors_dci = pd.Series(True, index=rcp.index)
    for part in parts:
        # une partie très courte (FER, FSH) doit être égale à la substance, pas seulement contenue
        if len(part) < 4:
            mask = rcp["_dci"] == part
        else:
            mask = rcp["_dci"].str.contains(part, regex=False)
        hors_dci &= ~mask
        found = set(rcp.loc[mask, "code_cis"])
        cis = found if cis is None else cis & found
    # exclut les spécialités ayant une substance étrangère à la DCI (ex. amoxicilline seule ≠ + acide clavulanique)
    en_trop = set(rcp.loc[hors_dci & (rcp["_dci"] != ""), "code_cis"])
    cis = (cis or set()) - en_trop
    result = rcp[rcp["code_cis"].isin(cis)][["code_cis", "denomination", "forme"]]
    return result.drop_duplicates().sort_values("denomination").reset_index(drop=True)


@st.cache_data
def _load_interactions(file_time):
    conn = sqlite3.connect(DB)
    tables = {
        name: pd.read_sql(f"SELECT * FROM {name}", conn)
        for name in ("dci_atc", "thesaurus_atc", "thesaurus_interactions")
    }
    conn.close()
    return tables


def load_interactions():
    return _load_interactions(os.path.getmtime(DB))


def codes_atc_pour_dci(rcp, dci_atc, dci):
    """codes ATC des substances RCP correspondant à une DCI DPM ('A+B' = A et B)"""
    parts = [normalize(p).strip() for p in str(dci).split("+")]
    noms = set()
    for part in filter(None, parts):
        if len(part) < 4:
            mask = rcp["_dci"] == part
        else:
            mask = rcp["_dci"].str.contains(part, regex=False)
        noms |= set(rcp.loc[mask, "dci"].dropna())
    return set(dci_atc.loc[dci_atc["dci"].isin(noms), "code_atc"])


def noms_thesaurus(codes, thesaurus_atc):
    """entrées du thésaurus (substances ou classes) dont le préfixe ATC couvre un des codes"""
    prefixes = thesaurus_atc["prefixe_atc"].tolist()
    ok = [any(c.startswith(p) for c in codes) for p in prefixes]
    return set(thesaurus_atc.loc[ok, "nom_thesaurus"])


GRAVITE = {"CI": 0, "ASDEC": 1, "PE": 2, "APEC": 3}
NIVEAU_LIBELLE = {
    "CI": "Contre-indication",
    "ASDEC": "Association déconseillée",
    "PE": "Précaution d'emploi",
    "APEC": "À prendre en compte",
}


def analyser_ordonnance(rcp, medicaments):
    """medicaments : {libellé: [DCI DPM]}. Renvoie (interactions, libellés sans code ATC)."""
    tables = load_interactions()
    dci_atc, tha, thi = tables["dci_atc"], tables["thesaurus_atc"], tables["thesaurus_interactions"]

    noms = {}
    sans_atc = []
    for label, dcis in medicaments.items():
        codes = set().union(*[codes_atc_pour_dci(rcp, dci_atc, d) for d in dcis]) if dcis else set()
        noms[label] = noms_thesaurus(codes, tha)
        if not codes:
            sans_atc.append(label)

    resultats, vus = [], set()
    labels = list(medicaments)
    for i, m1 in enumerate(labels):
        for m2 in labels[i + 1:]:
            mask = (thi["a"].isin(noms[m1]) & thi["b"].isin(noms[m2])) | (
                thi["a"].isin(noms[m2]) & thi["b"].isin(noms[m1])
            )
            for row in thi[mask].itertuples():
                cle = (frozenset((m1, m2)), frozenset((row.a, row.b)), row.niveaux, row.mecanisme)
                if cle in vus:
                    continue
                vus.add(cle)
                resultats.append({"m1": m1, "m2": m2, "a": row.a, "b": row.b,
                                  "niveau": row.niveau_max, "niveaux": row.niveaux,
                                  "conduite": row.conduite_a_tenir, "mecanisme": row.mecanisme})
    resultats.sort(key=lambda r: GRAVITE.get(r["niveau"], 9))
    return resultats, sans_atc


def show_results(view):
    view = view.reset_index(drop=True)
    st.write(f"{len(view)} résultat(s)")
    event = st.dataframe(
        view[["nom", "dosage", "forme", "dci", "laboratoire"]],
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    if event.selection.rows:
        row = view.iloc[event.selection.rows[0]]
        st.subheader(row["label"])
        st.table(row.drop(["_label", "_dci", "label", "nom"]).dropna().to_frame("valeur"))