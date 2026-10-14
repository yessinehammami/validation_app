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
    df = pd.read_sql("SELECT code_cis, denomination, substance, dci FROM table_rcp", conn)
    conn.close()
    df["_dci"] = df["dci"].fillna("").map(normalize)
    return df


def load_rcp():
    return _load_rcp(os.path.getmtime(DB))


def specialites_pour_dci(rcp, dci):
    """spécialités dont la DCI (FT de table_rcp) contient au moins une partie de la DCI DPM ('A+B' = A ou B)"""
    parts = [normalize(p).strip() for p in str(dci).split("+")]
    cis = set()
    for part in filter(None, parts):
        # une partie très courte (FER, FSH) doit être égale à la substance, pas seulement contenue
        if len(part) < 4:
            mask = rcp["_dci"] == part
        else:
            mask = rcp["_dci"].str.contains(part, regex=False)
        cis |= set(rcp.loc[mask, "code_cis"])
    result = rcp[rcp["code_cis"].isin(cis)][["code_cis", "denomination"]]
    return result.drop_duplicates().sort_values("denomination").reset_index(drop=True)


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