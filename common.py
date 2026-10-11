import os
import sqlite3
import unicodedata

import pandas as pd
import streamlit as st

DB = "amm_dpm.db"


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